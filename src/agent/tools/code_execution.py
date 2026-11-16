"""Code execution tool using Docker sandbox."""

import base64
import json
import os as local_os
import re
import subprocess
import threading
import time
from typing import Any, Protocol

from langchain_core.tools import tool

from src.agent.cancellation import TurnCancelled, on_cancel, raise_if_cancelled
from src.agent.tools.code_execution_output import (
    build_execution_response,
    get_mime_type,
    parse_output_files_from_stdout,
    wrap_user_code,
)
from src.agent.tools.context import get_conversation_context
from src.agent.tools.conversation_files import (
    ConversationFile,
    load_conversation_file,
    parse_file_id,
)
from src.agent.tools.errors import tool_error
from src.agent.tools.permission_check import check_autonomous_permission
from src.agent.tools.sandbox_sessions import get_sandbox_pool, make_sandbox_session
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Flag to track if Docker is available for code execution
# per-worker: a cached probe of this host's Docker, the same answer in every worker
_docker_available: bool | None = None
_docker_available_lock = threading.Lock()
# Why the last probe failed, for the tool result: the agent relays it to the
# user, and "Docker is not running" for a missing image sent everyone looking
# at the wrong thing (Nov 2026)
_DOCKER_DOWN = "Docker is not running or accessible."
# per-worker: describes this worker's own cached probe, like _docker_available
_unavailable_reason = _DOCKER_DOWN
# per-worker: when this worker last probed; each worker re-probes on its own
_probed_at = 0.0
# A failed probe is retried after this long, so fixing Docker or rebuilding
# the image takes effect without a restart; a passing probe stays cached
_RECHECK_UNAVAILABLE_SECONDS = 60.0


def _now() -> float:
    return time.monotonic()


def _check_docker_available() -> bool:
    """Check if Docker is available for code execution.

    Caches a pass for the worker's life and a failure for
    _RECHECK_UNAVAILABLE_SECONDS. Double-checked locking: two gthread request
    threads racing the first check would each spin up a probe sandbox
    container.
    """
    if _probe_is_fresh():
        return bool(_docker_available)
    with _docker_available_lock:
        if _probe_is_fresh():
            return bool(_docker_available)
        return _probe_docker_available()


def _probe_is_fresh() -> bool:
    if _docker_available is None:
        return False
    return _docker_available or _now() - _probed_at < _RECHECK_UNAVAILABLE_SECONDS


def _probe_docker_available() -> bool:
    """Run the actual Docker/sandbox probe (callers hold the lock)."""
    global _docker_available, _unavailable_reason, _probed_at

    _probed_at = _now()
    _unavailable_reason = _DOCKER_DOWN
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
            _unavailable_reason = (
                f"The sandbox image {Config.CODE_SANDBOX_IMAGE} is missing on this server "
                "(Docker itself is running)."
            )
            logger.warning(
                "Custom sandbox image not found",
                extra={
                    "image": Config.CODE_SANDBOX_IMAGE,
                    "note": "Run 'make sandbox-image' to build the custom image",
                },
            )
            return _docker_available

        # Verify Docker connectivity with a quick run under the SAME
        # constraints as execute_code (a probe with other settings can pass
        # while executions fail)
        session = make_sandbox_session()
        try:
            session.open()
            probe = session.run("print('ok')", timeout_s=Config.CODE_SANDBOX_TIMEOUT_SECONDS)
        finally:
            session.close()
        _docker_available = probe.exit_code == 0
        if _docker_available:
            logger.info("Docker sandbox available for code execution")
        else:
            logger.warning(
                "Docker sandbox test failed",
                extra={"exit_code": probe.exit_code, "stderr": probe.stderr[:300]},
            )
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


def _kill_user_code(session: Any) -> None:
    """Cancel callback: SIGKILL the running user program (Stop pressed).

    Runs on its own daemon thread: callbacks run on the stop poller, and a
    slow or hung Docker exec must not hold it.
    """
    logger.info("Stop requested - killing sandbox user code")

    def _kill() -> None:
        try:
            session.kill_user_code()
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
        session: The DockerSandbox
        filename: Name of the file to extract from /output/

    Returns:
        Tuple of (full_file_data, file_metadata) or (None, None) on failure.
        full_file_data contains the base64 encoded data for server storage.
        file_metadata contains only name, type, size for the LLM.
    """
    try:
        file_data = session.read_file(f"/output/{filename}")

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


def _extract_output_files(
    session: Any, filenames: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract all output files from the sandbox.

    Args:
        session: The DockerSandbox
        filenames: List of filenames to extract from /output/

    Returns:
        Tuple of (full_files_list, metadata_list).
        full_files_list contains base64 data for server storage.
        metadata_list contains only name/type/size for the LLM.
    """
    full_files: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []

    for filename in filenames:
        # The list is parsed from stdout, which user code can forge: plain
        # names only (read_file also refuses anything outside /output)
        if not isinstance(filename, str) or not filename or "/" in filename:
            continue
        if filename in {".", ".."}:
            continue
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

    return build_execution_response(result, clean_stdout, file_metadata, full_result_files)


def _log_execution_result(result: Any, response: dict[str, Any], work_bytes: int | None) -> None:
    if result.exit_code == 0:
        logger.info(
            "Code execution succeeded",
            extra={
                "stdout_length": len(response["stdout"]),
                "has_files": bool(response.get("files")),
                "work_bytes": work_bytes,
            },
        )
    else:
        logger.warning(
            "Code execution failed",
            extra={
                "exit_code": result.exit_code,
                "stderr_preview": (result.stderr or "")[:500],
                "work_bytes": work_bytes,
            },
        )


ATTACHMENTS_DIR = "/work/attachments"


class _CopyTarget(Protocol):
    """The sandbox session's copy-in method (DockerSandbox)."""

    def put_file(self, data: bytes, dest: str, /) -> None: ...


def _attachment_path(name: str, taken: set[str]) -> str:
    """A safe, unused path in ATTACHMENTS_DIR for an uploaded file's name.

    Directories and leading dots are dropped (no traversal, no hidden files);
    a repeated name gets -2, -3... before its extension.
    """
    base = (
        re.sub(r"[^\w.\- ]", "_", local_os.path.basename(name.replace("\\", "/"))).lstrip(". ")
        or "file"
    )
    stem, ext = local_os.path.splitext(base)
    candidate, n = base, 1
    while candidate in taken:
        n += 1
        candidate = f"{stem}-{n}{ext}"
    taken.add(candidate)
    return f"{ATTACHMENTS_DIR}/{candidate}"


def _load_attachments(file_ids: list[str]) -> list[ConversationFile] | str:
    """Every requested attachment, or the tool error for the first that fails.

    All are checked before anything is copied: the code must not run on a
    partial set of inputs.
    """
    limit = Config.CODE_SANDBOX_MAX_ATTACHMENTS
    if len(file_ids) > limit:
        return tool_error(f"At most {limit} files per call; {len(file_ids)} were listed.")
    loaded: list[ConversationFile] = []
    for file_id in file_ids:
        parsed = parse_file_id(str(file_id))
        if parsed is None:
            return tool_error(
                f"'{file_id}' is not a file id. Use the history's 'message_id:file_index' form."
            )
        result = load_conversation_file(*parsed)
        if isinstance(result, str):
            return result
        if len(result.data) > Config.MAX_FILE_SIZE_BYTES:
            return tool_error(
                f"'{result.name}' is {len(result.data)} bytes; the limit is {Config.MAX_FILE_SIZE_BYTES}."
            )
        loaded.append(result)
    return loaded


def _copy_attachments(
    session: _CopyTarget, files: list[ConversationFile]
) -> list[dict[str, object]]:
    """Copy the attachments into the sandbox; their paths for the result."""
    taken: set[str] = set()
    copied: list[dict[str, object]] = []
    for file in files:
        path = _attachment_path(file.name, taken)
        session.put_file(file.data, path)
        copied.append(
            {"file_id": file.file_id, "path": path, "name": file.name, "size": len(file.data)}
        )
    return copied


def _execution_error(error: Exception) -> str:
    """The tool result for a failed execution, with a hint for common causes."""
    error_msg = str(error)
    logger.error("Code execution error", extra={"error": error_msg}, exc_info=error)
    if "docker" in error_msg.lower() or "connection" in error_msg.lower():
        return tool_error(
            "Docker connection failed. The sandbox service is temporarily unavailable.",
            hint="Please try again later or contact the administrator.",
        )
    return tool_error(f"Code execution failed: {error_msg}")


def _timed_out() -> str:
    logger.warning("Code execution timed out")
    return tool_error(
        f"Code execution timed out after {Config.CODE_SANDBOX_TIMEOUT_SECONDS} seconds.",
        hint="Try optimizing your code or breaking it into smaller pieces.",
    )


@tool
def execute_code(code: str, files: list[str] | None = None) -> str:
    """Run Python in an isolated sandbox: calculations, data processing, charts, and files
    (PDF, Word, PowerPoint, Excel, images). Write ONE complete script that does the whole
    task - the environment below is fixed, so never spend calls probing it.

    ## Pre-installed Libraries
    numpy, pandas, matplotlib, scipy, sympy, pillow, reportlab, fpdf2, requests, beautifulsoup4, lxml, openpyxl, python-docx, python-pptx, python-dateutil, pytz, pypdf, pdfplumber

    - Limits: NO network, no access to the user's local files, 30 s timeout, 512 MB memory.
    - Output: print what the user should see; save files (and plots via plt.savefig) to
      /output/ - they are attached to your reply (tell the user what you attached).
      /output/ is cleared every call; files in /work/ persist within the conversation,
      variables do not (each call is a fresh process).
    - Uploads are NOT in the sandbox until you list their ids ("message_id:file_index"
      from the history metadata) in `files`: they are copied to /work/attachments/ and
      the result's `attachments` gives each path - the only way to measure, parse or
      convert an uploaded file.
    - Reading a PDF: start with `from sandbox_helpers import pdf_overview;
      pdf_overview(path)` (what each page holds, which pages are scanned; 20 pages per
      call, `first_page=21` next), then pdfplumber (`extract_text`, `extract_words`,
      `page.lines`/`page.rects` to measure plans, `find_tables`, `to_image` to render).
    - Writing PDF / Word / PowerPoint / Excel: load_skill('pdf-documents') /
      load_skill('office-documents') first.

    Args:
        code: Python code to execute. Should be complete, runnable code.
        files: Optional ids of conversation files ("message_id:file_index")
            to copy into /work/attachments/ first (at most 5 per call).
    """
    # Unattended runs: blocked unless the job grants it
    check_autonomous_permission("execute_code", {"code": code})

    # Check if sandbox is available
    if not Config.CODE_SANDBOX_ENABLED:
        return tool_error("Code execution is disabled on this server.", retriable=False)

    if not _check_docker_available():
        image_missing = _unavailable_reason != _DOCKER_DOWN
        return tool_error(
            f"Code execution is not available. {_unavailable_reason}",
            retriable=False,
            hint=(
                "The server administrator needs to run 'make sandbox-image'."
                if image_missing
                else "The server administrator needs to ensure Docker is running and accessible."
            ),
        )

    if not code or not code.strip():
        return tool_error("Code cannot be empty.")

    attachments = _load_attachments(files) if files else []
    if isinstance(attachments, str):
        return attachments

    logger.info(
        "execute_code called",
        extra={"code_length": len(code), "code_preview": code[:200] if len(code) > 200 else code},
    )

    try:
        wrapped_code = wrap_user_code(code)

        # Sessions come from the per-conversation pool (the constraints in
        # docker_sandbox.sandbox_container_config, shared with the
        # availability probe). Without a conversation context the session is
        # ephemeral.
        conversation_id, _user_id = get_conversation_context()
        with get_sandbox_pool().session(conversation_id) as session:
            logger.debug(
                "Sandbox session acquired",
                extra={"pooled": conversation_id is not None},
            )

            # Libraries are pre-installed in the image - run the code directly.
            # Server-side Stop kills the running program (not the container:
            # /work must survive) and the turn ends at the next checkpoint.
            copied = _copy_attachments(session, attachments)
            raise_if_cancelled()
            with on_cancel(lambda: _kill_user_code(session)):
                result = session.run(wrapped_code, timeout_s=Config.CODE_SANDBOX_TIMEOUT_SECONDS)

            response = _collect_execution_response(session, result)
            if files:
                response["attachments"] = copied
            _log_execution_result(result, response, session.work_bytes())
            return json.dumps(response)

    except TurnCancelled:
        raise  # Stop pressed: end the turn, not an error result
    except TimeoutError:
        return _timed_out()
    except Exception as e:  # noqa: BLE001 - every sandbox failure becomes a tool error, logged there
        return _execution_error(e)
