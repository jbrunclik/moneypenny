"""The protocol between execute_code and the user's program in the sandbox.

The user's code is wrapped so it starts with a clean /output and prints a
marker line listing the files it left there; the result's stdout is parsed
for that marker and its plots collected, and the tool's response built
(file data under _full_result, which the server strips before the LLM).
"""

import base64
import contextlib
import json
import mimetypes
from typing import Any

from src.config import Config


def get_mime_type(filename: str) -> str:
    """Get MIME type from filename extension using the standard library."""
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type or "application/octet-stream"


def wrap_user_code(code: str) -> str:
    """Wrap user code with setup and file listing logic.

    The wrapped code:
    1. Resets /output (sessions persist across calls - a previous run's files
       must not be re-extracted) and ensures the persistent /work directory
    2. Runs the user code
    3. Lists files in /output for extraction

    Args:
        code: The user's Python code to wrap

    Returns:
        Wrapped code ready for sandbox execution
    """
    return f"""
import os, shutil
shutil.rmtree('/output', ignore_errors=True)
os.makedirs('/output', exist_ok=True)
os.makedirs('/work', exist_ok=True)

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


def parse_output_files_from_stdout(stdout: str) -> tuple[list[str], str]:
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
            with contextlib.suppress(json.JSONDecodeError):
                output_files = json.loads(line[17:])
        else:
            clean_lines.append(line)

    return output_files, "\n".join(clean_lines).rstrip()


def extract_plots(result: Any) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
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


def build_execution_response(
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

    # Cap output sizes - both land verbatim in LLM context (a print(df) on a
    # large DataFrame would otherwise be unbounded)
    max_chars = Config.CODE_EXECUTION_MAX_STDOUT_CHARS
    if len(clean_stdout) > max_chars:
        clean_stdout = clean_stdout[:max_chars] + "\n[...stdout truncated]"
    if len(stderr) > max_chars:
        stderr = stderr[:max_chars] + "\n[...stderr truncated]"

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
