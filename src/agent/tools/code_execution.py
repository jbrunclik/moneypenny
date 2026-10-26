"""Code execution tool using Docker sandbox."""

import base64
import contextlib
import json
import os as local_os
import subprocess
import tempfile
import threading
from typing import Any

from langchain_core.tools import tool

from src.agent.cancellation import TurnCancelled, on_cancel, raise_if_cancelled
from src.agent.tools.code_execution_output import (
    build_execution_response,
    extract_plots,
    get_mime_type,
    parse_output_files_from_stdout,
    wrap_user_code,
)
from src.agent.tools.context import get_conversation_context
from src.agent.tools.errors import tool_error
from src.agent.tools.permission_check import check_autonomous_permission
from src.agent.tools.sandbox_sessions import OWNER_PID_LABEL, get_sandbox_pool
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Flag to track if Docker is available for code execution
# per-worker: a cached probe of this host's Docker, the same answer in every worker
_docker_available: bool | None = None
_docker_available_lock = threading.Lock()

# Session settings shared by the availability probe and execute_code (S4):
# probing with different settings than real executions can pass while
# executions fail (or vice versa).
# - network_disabled: generated code must not have network access; llm-sandbox
#   does NOT disable networking by default (verified on 0.3.31)
# - skip_environment_setup: every library is pre-installed in the custom image
#   (make sandbox-image); the default setup runs an in-container pip upgrade,
#   which needs the network we just disabled
SANDBOX_SESSION_KWARGS: dict[str, Any] = {
    "lang": "python",
    "verbose": False,
    "skip_environment_setup": True,
}


def sandbox_runtime_configs() -> dict[str, Any]:
    return {
        "network_disabled": True,
        "mem_limit": Config.CODE_SANDBOX_MEMORY_LIMIT,
        "nano_cpus": int(Config.CODE_SANDBOX_CPU_LIMIT * 1_000_000_000),
        # Run an init (tini) as PID 1. Without it, the sandbox's PID 1 ignores
        # SIGTERM, so container teardown waits the full ~10s docker-stop grace
        # before SIGKILL - on EVERY execute_code call. With init, SIGTERM is
        # handled and teardown drops from ~10s to ~0.1s (measured).
        "init": True,
        "labels": {OWNER_PID_LABEL: str(local_os.getpid())},
    }


def _check_docker_available() -> bool:
    """Check if Docker is available for code execution.

    Caches the result to avoid repeated checks. Double-checked locking: two
    gthread request threads racing the first check would each spin up a
    probe sandbox container.
    """
    global _docker_available
    if _docker_available is not None:
        return _docker_available
    with _docker_available_lock:
        if _docker_available is not None:
            return _docker_available
        return _probe_docker_available()


def _probe_docker_available() -> bool:
    """Run the actual Docker/sandbox probe (callers hold the lock)."""
    global _docker_available

    try:
        # Check if the custom sandbox image exists
        result = subprocess.run(  # noqa: S603 - fixed args, no untrusted input
            ["docker", "images", "-q", Config.CODE_SANDBOX_IMAGE],  # noqa: S607 - docker from PATH: its location differs per host
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            _docker_available = False
            logger.warning(
                "Docker command failed",
                extra={"error": result.stderr, "note": "Ensure Docker is running"},
            )
            return _docker_available

        if not result.stdout.strip():
            _docker_available = False
            logger.warning(
                "Custom sandbox image not found",
                extra={
                    "image": Config.CODE_SANDBOX_IMAGE,
                    "note": "Run 'make sandbox-image' to build the custom image",
                },
            )
            return _docker_available

        # Verify Docker connectivity with a quick test, using the SAME
        # session settings as execute_code
        from llm_sandbox import SandboxSession  # noqa: PLC0415 - docker client kept off startup

        with SandboxSession(
            image=Config.CODE_SANDBOX_IMAGE,
            runtime_configs=sandbox_runtime_configs(),
            **SANDBOX_SESSION_KWARGS,
        ) as session:
            result = session.run("print('ok')")
            _docker_available = result.exit_code == 0
            if _docker_available:
                logger.info("Docker sandbox available for code execution")
            else:
                logger.warning("Docker sandbox test failed", extra={"exit_code": result.exit_code})
    except subprocess.TimeoutExpired:
        _docker_available = False
        logger.warning("Docker command timed out", extra={"note": "Ensure Docker is running"})
    except FileNotFoundError:
        _docker_available = False
        logger.warning("Docker command not found", extra={"note": "Ensure Docker is installed"})
    except Exception as e:  # any probe failure disables the tool
        _docker_available = False
        logger.warning(
            "Docker not available for code execution",
            extra={"error": str(e), "note": "Code execution tool will be disabled"},
            exc_info=True,
        )

    return _docker_available


# Kills the user's program inside a live session container without touching
# the container: /work must survive a Stop. Spares PID 1 (docker-init), its
# oldest child (the container's keep-alive command) and itself; everything
# else is user code - exec'd programs, their children (whatever their argv)
# and orphans re-parented to PID 1. No procps in the slim image, so scan
# /proc from Python (always present in the image).
_KILL_USER_CODE = (
    "import os\n"
    "me = os.getpid()\n"
    "procs = {}\n"
    "for p in filter(str.isdigit, os.listdir('/proc')):\n"
    "    try:\n"
    "        stat = open(f'/proc/{p}/stat').read().rsplit(')', 1)[1].split()\n"
    "        procs[int(p)] = (int(stat[1]), int(stat[19]))\n"
    "    except OSError:\n"
    "        pass\n"
    "init_children = [p for p, (ppid, _) in procs.items() if ppid == 1]\n"
    "keep = {1, me}\n"
    "if init_children:\n"
    "    keep.add(min(init_children, key=lambda p: procs[p][1]))\n"
    "for p in procs.keys() - keep:\n"
    "    try:\n"
    "        os.kill(p, 9)\n"
    "    except OSError:\n"
    "        pass\n"
)


def _kill_user_code(session: Any) -> None:
    """Cancel callback: SIGKILL the running user program (Stop pressed).

    Runs on its own daemon thread: callbacks run on the stop poller, and a
    slow or hung Docker exec must not hold it.
    """
    logger.info("Stop requested - killing sandbox user code")

    def _kill() -> None:
        try:
            session.container.exec_run(["python", "-c", _KILL_USER_CODE], user="root")
        except Exception:
            logger.warning("Sandbox kill on Stop failed", exc_info=True)

    threading.Thread(target=_kill, daemon=True, name="sandbox-kill").start()


def is_code_sandbox_available() -> bool:
    """Check if code sandbox is available and enabled."""
    if not Config.CODE_SANDBOX_ENABLED:
        return False
    return _check_docker_available()


def _extract_file_from_sandbox(
    session: Any, filename: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Extract a single file from the sandbox and return metadata and full data.

    Args:
        session: The SandboxSession instance
        filename: Name of the file to extract from /output/

    Returns:
        Tuple of (full_file_data, file_metadata) or (None, None) on failure.
        full_file_data contains the base64 encoded data for server storage.
        file_metadata contains only name, type, size for the LLM.
    """
    # Create a temp file to receive the data
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name

    try:
        # Copy file from sandbox
        session.copy_from_runtime(f"/output/{filename}", tmp_path)

        # Read and encode the file
        with open(tmp_path, "rb") as f:
            file_data = f.read()

        mime_type = get_mime_type(filename)
        file_size = len(file_data)

        # Full data for server-side extraction (includes base64)
        full_file_data = {
            "name": filename,
            "mime_type": mime_type,
            "data": base64.b64encode(file_data).decode("utf-8"),
            "size": file_size,
        }

        # Metadata for LLM (no base64 data - saves tokens)
        file_metadata = {
            "name": filename,
            "mime_type": mime_type,
            "size": file_size,
        }

        return full_file_data, file_metadata

    except Exception as e:  # one unreadable output file must not fail the run
        logger.warning(
            "Failed to extract file from sandbox",
            extra={"file_name": filename, "error": str(e)},
            exc_info=True,
        )
        return None, None
    finally:
        # Always remove the host temp file - error paths leaked it before
        with contextlib.suppress(OSError):
            local_os.unlink(tmp_path)


def _extract_output_files(
    session: Any, filenames: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract all output files from the sandbox.

    Args:
        session: The SandboxSession instance
        filenames: List of filenames to extract from /output/

    Returns:
        Tuple of (full_files_list, metadata_list).
        full_files_list contains base64 data for server storage.
        metadata_list contains only name/type/size for the LLM.
    """
    full_files: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []

    for filename in filenames:
        full_data, meta = _extract_file_from_sandbox(session, filename)
        if full_data and meta:
            full_files.append(full_data)
            metadata.append(meta)

    return full_files, metadata


def _collect_execution_response(session: Any, result: Any) -> dict[str, Any]:
    """The response for a finished run, with the files and plots it produced."""
    # Parse output and extract files
    stdout = result.stdout or ""
    output_files, clean_stdout = parse_output_files_from_stdout(stdout)

    # Extract files from sandbox
    full_result_files: list[dict[str, Any]] = []
    file_metadata: list[dict[str, Any]] = []

    if output_files and result.exit_code == 0:
        full_files, file_metadata = _extract_output_files(session, output_files)
        full_result_files.extend(full_files)
        if file_metadata:
            logger.info(
                "Code execution extracted files",
                extra={
                    "file_count": len(file_metadata),
                    "filenames": [f["name"] for f in file_metadata],
                },
            )

    # Extract matplotlib plots
    plot_full_data, plot_metadata = extract_plots(result)
    full_result_files.extend(plot_full_data)
    if plot_metadata:
        logger.info("Code execution captured plots", extra={"plot_count": len(plot_metadata)})

    return build_execution_response(
        result, clean_stdout, file_metadata, plot_metadata, full_result_files
    )


def _log_execution_result(result: Any, response: dict[str, Any]) -> None:
    if result.exit_code == 0:
        logger.info(
            "Code execution succeeded",
            extra={
                "stdout_length": len(response["stdout"]),
                "has_files": bool(response.get("files")),
                "has_plots": bool(response.get("plots")),
            },
        )
    else:
        logger.warning(
            "Code execution failed",
            extra={
                "exit_code": result.exit_code,
                "stderr_preview": (result.stderr or "")[:500],
            },
        )


@tool
def execute_code(code: str) -> str:
    """Execute Python code in a secure, isolated sandbox environment.

    Use this tool for tasks that require computation, data processing, or generating files.
    The sandbox has NO network access and NO access to local files outside the sandbox.

    ## Capabilities
    - Mathematical calculations (numpy, scipy, sympy)
    - Data analysis and manipulation (pandas, numpy)
    - Creating charts and plots (matplotlib) - returned as base64 images
    - Generating PDF documents (reportlab, fpdf2)
    - Generating Word, PowerPoint and Excel files (python-docx, python-pptx, openpyxl)
      (for Word/PowerPoint/Excel or PDF output, call load_skill('office-documents') /
      load_skill('pdf-documents') first)
    - Image processing (pillow)
    - Text parsing and processing
    - JSON/CSV data transformation

    ## Pre-installed Libraries
    numpy, pandas, matplotlib, scipy, sympy, pillow, reportlab, fpdf2, requests, beautifulsoup4, lxml, openpyxl, python-docx, python-pptx, python-dateutil, pytz

    ## Limitations
    - NO network access (cannot fetch URLs, APIs, or download anything)
    - NO access to user's local files (cannot read/write files outside sandbox)
    - 30 second execution timeout
    - 512MB memory limit

    ## Persistence Across Calls
    - Files saved to /work/ persist across execute_code calls within this
      conversation (e.g. save a dataset once, analyze it in later calls)
    - Variables do NOT persist - each call is a fresh Python process
    - /output/ is cleared at the start of every call

    ## Best Practices
    - Print results you want to show the user
    - For plots: use plt.savefig() or plt.show() - plots are captured automatically
    - For generated files (PDFs, images): save to /output/ directory and they will be
      returned as base64-encoded data in the response

    ## Example: Generate a PDF
    ```python
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas("/output/report.pdf", pagesize=letter)
    c.drawString(100, 750, "Hello World!")
    c.save()
    print("PDF generated successfully")
    ```

    ## Example: Generate a plot
    ```python
    import matplotlib.pyplot as plt
    import numpy as np

    x = np.linspace(0, 10, 100)
    plt.plot(x, np.sin(x))
    plt.title("Sine Wave")
    plt.savefig("/output/plot.png")
    print("Plot saved")
    ```

    Args:
        code: Python code to execute. Should be complete, runnable code.

    Returns:
        JSON with stdout, stderr, exit_code, and any generated files.
        Files saved to /output/ are returned as base64-encoded data.
    """
    # Check permission for autonomous agents (always requires approval)
    check_autonomous_permission("execute_code", {"code": code})

    # Check if sandbox is available
    if not Config.CODE_SANDBOX_ENABLED:
        return tool_error("Code execution is disabled on this server.", retriable=False)

    if not _check_docker_available():
        return tool_error(
            "Code execution is not available. Docker is not running or accessible.",
            hint="The server administrator needs to ensure Docker is running and accessible.",
        )

    if not code or not code.strip():
        return tool_error("Code cannot be empty.")

    logger.info(
        "execute_code called",
        extra={"code_length": len(code), "code_preview": code[:200] if len(code) > 200 else code},
    )

    try:
        wrapped_code = wrap_user_code(code)

        # Sessions come from the per-conversation pool (security constraints
        # unchanged: networking disabled + resource limits, shared settings
        # with the availability probe - see SANDBOX_SESSION_KWARGS). Without
        # a conversation context the session is ephemeral, as before.
        conversation_id, _user_id = get_conversation_context()
        with get_sandbox_pool().session(conversation_id) as session:
            logger.debug(
                "Sandbox session acquired",
                extra={"pooled": conversation_id is not None},
            )

            # Libraries are pre-installed in the image - run the code directly.
            # Server-side Stop kills the running program (not the container:
            # /work must survive) and the turn ends at the next checkpoint.
            raise_if_cancelled()
            with on_cancel(lambda: _kill_user_code(session)):
                result = session.run(wrapped_code)

            response = _collect_execution_response(session, result)
            _log_execution_result(result, response)
            return json.dumps(response)

    except TurnCancelled:
        raise  # Stop pressed: end the turn, not an error result
    except TimeoutError:
        logger.warning("Code execution timed out")
        return tool_error(
            f"Code execution timed out after {Config.CODE_SANDBOX_TIMEOUT} seconds.",
            hint="Try optimizing your code or breaking it into smaller pieces.",
        )
    except Exception as e:
        error_msg = str(e)
        logger.exception("Code execution error", extra={"error": error_msg})

        # Provide helpful error messages for common issues
        if "docker" in error_msg.lower() or "connection" in error_msg.lower():
            return tool_error(
                "Docker connection failed. The sandbox service is temporarily unavailable.",
                hint="Please try again later or contact the administrator.",
            )

        return tool_error(f"Code execution failed: {error_msg}")
