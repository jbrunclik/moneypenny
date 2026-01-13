"""Code execution tool using Docker sandbox."""

import base64
import json
import os as local_os
import tempfile
from typing import Any

from langchain_core.tools import tool

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Flag to track if Docker is available for code execution
_docker_available: bool | None = None


def _check_docker_available() -> bool:
    """Check if Docker is available for code execution.

    Caches the result to avoid repeated checks.
    Verifies that the custom sandbox image exists.
    """
    global _docker_available
    if _docker_available is not None:
        return _docker_available

    try:
        import subprocess

        # Check if the custom sandbox image exists
        result = subprocess.run(
            ["docker", "images", "-q", Config.CODE_SANDBOX_IMAGE],
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

        # Verify Docker connectivity with a quick test
        from llm_sandbox import SandboxSession

        with SandboxSession(lang="python", image=Config.CODE_SANDBOX_IMAGE) as session:
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
    except Exception as e:
        _docker_available = False
        logger.warning(
            "Docker not available for code execution",
            extra={"error": str(e), "note": "Code execution tool will be disabled"},
        )

    return _docker_available


def is_code_sandbox_available() -> bool:
    """Check if code sandbox is available and enabled."""
    if not Config.CODE_SANDBOX_ENABLED:
        return False
    return _check_docker_available()


def _get_mime_type(filename: str) -> str:
    """Get MIME type from filename extension."""
    ext = filename.lower().split(".")[-1] if "." in filename else ""
    mime_types = {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "svg": "image/svg+xml",
        "csv": "text/csv",
        "json": "application/json",
        "txt": "text/plain",
        "html": "text/html",
        "xml": "application/xml",
    }
    return mime_types.get(ext, "application/octet-stream")


def _wrap_user_code(code: str) -> str:
    """Wrap user code with setup and file listing logic.

    The wrapped code:
    1. Creates /output directory for file saving
    2. Runs the user code
    3. Lists files in /output for extraction

    Args:
        code: The user's Python code to wrap

    Returns:
        Wrapped code ready for sandbox execution
    """
    return f"""
import os
os.makedirs('/output', exist_ok=True)

# User code starts here
{code}
# User code ends here

# List generated files for extraction
import json as _json
_output_files = []
if os.path.exists('/output'):
    for _f in os.listdir('/output'):
        _path = os.path.join('/output', _f)
        if os.path.isfile(_path):
            _output_files.append(_f)
if _output_files:
    print('__OUTPUT_FILES__:' + _json.dumps(_output_files))
"""


def _parse_output_files_from_stdout(stdout: str) -> tuple[list[str], str]:
    """Parse output file list from stdout and return cleaned stdout.

    The wrapped code prints a special marker line with the list of files
    in /output directory. This function extracts that list and removes
    the marker line from stdout.

    Args:
        stdout: Raw stdout from sandbox execution

    Returns:
        Tuple of (list of filenames, cleaned stdout without marker line)
    """
    output_files: list[str] = []
    clean_lines = []

    for line in stdout.split("\n"):
        if line.startswith("__OUTPUT_FILES__:"):
            try:
                output_files = json.loads(line[17:])
            except json.JSONDecodeError:
                pass
        else:
            clean_lines.append(line)

    return output_files, "\n".join(clean_lines).rstrip()


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
    try:
        # Create a temp file to receive the data
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        # Copy file from sandbox
        session.copy_from_runtime(f"/output/{filename}", tmp_path)

        # Read and encode the file
        with open(tmp_path, "rb") as f:
            file_data = f.read()

        mime_type = _get_mime_type(filename)
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

        # Clean up temp file
        local_os.unlink(tmp_path)

        return full_file_data, file_metadata

    except Exception as e:
        logger.warning(
            "Failed to extract file from sandbox",
            extra={"filename": filename, "error": str(e)},
        )
        return None, None


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


def _extract_plots(result: Any) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Extract matplotlib plots from sandbox execution result.

    Args:
        result: The execution result from SandboxSession.run()

    Returns:
        Tuple of (full_plots_list, metadata_list).
        full_plots_list contains base64 data for server storage.
        metadata_list contains only format/name for the LLM.
    """
    full_plots: list[dict[str, Any]] = []
    metadata: list[dict[str, str]] = []

    if not hasattr(result, "plots") or not result.plots:
        return full_plots, metadata

    for i, plot in enumerate(result.plots):
        plot_format = plot.format.value if hasattr(plot.format, "value") else str(plot.format)
        plot_name = f"plot_{i + 1}.{plot_format}"

        # Full data for server-side extraction
        full_plots.append(
            {
                "name": plot_name,
                "mime_type": f"image/{plot_format}",
                "data": plot.content_base64,
                "size": len(base64.b64decode(plot.content_base64)) if plot.content_base64 else 0,
            }
        )

        # Metadata for LLM
        metadata.append({"format": plot_format, "name": plot_name})

    return full_plots, metadata


def _build_execution_response(
    result: Any,
    clean_stdout: str,
    file_metadata: list[dict[str, Any]],
    plot_metadata: list[dict[str, str]],
    full_result_files: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the final response dictionary for code execution.

    Uses the _full_result pattern: LLM sees only metadata, server extracts
    full file data from _full_result for storage and display.

    Args:
        result: The execution result from SandboxSession.run()
        clean_stdout: Stdout with marker lines removed
        file_metadata: Metadata for files (no base64) - shown to LLM
        plot_metadata: Metadata for plots - shown to LLM
        full_result_files: Full file data (with base64) - extracted server-side

    Returns:
        Response dictionary ready for JSON serialization
    """
    stderr = result.stderr or ""

    response: dict[str, Any] = {
        "success": result.exit_code == 0,
        "exit_code": result.exit_code,
        "stdout": clean_stdout,
        "stderr": stderr,
    }

    # Add file metadata for LLM
    if file_metadata:
        response["files"] = file_metadata
        response["message"] = (
            f"Generated {len(file_metadata)} file(s): "
            + ", ".join(f["name"] for f in file_metadata)
            + ". Files will be displayed to the user."
        )

    # Add plot metadata for LLM
    if plot_metadata:
        response["plots"] = plot_metadata

    # Store full file data in _full_result (stripped before sending to LLM)
    if full_result_files:
        response["_full_result"] = {"files": full_result_files}

    return response


@tool
def execute_code(code: str) -> str:
    """Execute Python code in a secure, isolated sandbox environment.

    Use this tool for tasks that require computation, data processing, or generating files.
    The sandbox has NO network access and NO access to local files outside the sandbox.

    ## Capabilities
    - Mathematical calculations (numpy, scipy, sympy)
    - Data analysis and manipulation (pandas, numpy)
    - Creating charts and plots (matplotlib) - returned as base64 images
    - Generating PDF documents (reportlab)
    - Image processing (pillow)
    - Text parsing and processing
    - JSON/CSV data transformation

    ## Pre-installed Libraries
    numpy, pandas, matplotlib, scipy, sympy, pillow, reportlab

    ## Limitations
    - NO network access (cannot fetch URLs, APIs, or download anything)
    - NO access to user's local files (cannot read/write files outside sandbox)
    - 30 second execution timeout
    - 512MB memory limit

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
    # Check if sandbox is available
    if not Config.CODE_SANDBOX_ENABLED:
        return json.dumps({"error": "Code execution is disabled on this server."})

    if not _check_docker_available():
        return json.dumps(
            {
                "error": "Code execution is not available. Docker is not running or accessible.",
                "hint": "The server administrator needs to ensure Docker is running and accessible.",
            }
        )

    if not code or not code.strip():
        return json.dumps({"error": "Code cannot be empty."})

    logger.info(
        "execute_code called",
        extra={"code_length": len(code), "code_preview": code[:200] if len(code) > 200 else code},
    )

    try:
        from llm_sandbox import SandboxSession

        wrapped_code = _wrap_user_code(code)

        # Create sandbox session with security constraints
        # Note: llm-sandbox runs containers with --network none by default for security
        with SandboxSession(
            lang="python",
            image=Config.CODE_SANDBOX_IMAGE,
            verbose=False,
        ) as session:
            logger.debug("Sandbox session created, executing code")

            # Execute code with pre-installed libraries
            result = session.run(
                wrapped_code,
                libraries=Config.CODE_SANDBOX_LIBRARIES,
            )

            # Parse output and extract files
            stdout = result.stdout or ""
            output_files, clean_stdout = _parse_output_files_from_stdout(stdout)

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
            plot_full_data, plot_metadata = _extract_plots(result)
            full_result_files.extend(plot_full_data)
            if plot_metadata:
                logger.info(
                    "Code execution captured plots", extra={"plot_count": len(plot_metadata)}
                )

            # Build response
            response = _build_execution_response(
                result, clean_stdout, file_metadata, plot_metadata, full_result_files
            )

            # Log execution result
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

            return json.dumps(response)

    except TimeoutError:
        logger.warning("Code execution timed out")
        return json.dumps(
            {
                "error": f"Code execution timed out after {Config.CODE_SANDBOX_TIMEOUT} seconds.",
                "hint": "Try optimizing your code or breaking it into smaller pieces.",
            }
        )
    except Exception as e:
        error_msg = str(e)
        logger.error("Code execution error", extra={"error": error_msg}, exc_info=True)

        # Provide helpful error messages for common issues
        if "docker" in error_msg.lower() or "connection" in error_msg.lower():
            return json.dumps(
                {
                    "error": "Docker connection failed. The sandbox service is temporarily unavailable.",
                    "hint": "Please try again later or contact the administrator.",
                }
            )

        return json.dumps({"error": f"Code execution failed: {error_msg}"})
