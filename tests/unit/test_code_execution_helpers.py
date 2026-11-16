"""Unit tests for code execution helper functions (src/agent/tools/code_execution.py)."""

from unittest.mock import MagicMock

from src.agent.tools.code_execution_output import (
    build_execution_response,
    parse_output_files_from_stdout,
    wrap_user_code,
)

# ============================================================================
# Tests for Code Execution Helper Functions
# ============================================================================


class TestWrapUserCode:
    """Tests for wrap_user_code helper function."""

    def test_creates_output_directory(self) -> None:
        """Should create /output directory at start."""
        result = wrap_user_code("print('test')")
        assert "os.makedirs('/output', exist_ok=True)" in result

    def test_includes_user_code(self) -> None:
        """Should include the user's code."""
        user_code = "x = 1 + 1\nprint(x)"
        result = wrap_user_code(user_code)
        assert user_code in result

    def test_adds_file_listing(self) -> None:
        """Should add code to list output files."""
        result = wrap_user_code("print('test')")
        assert "__OUTPUT_FILES__" in result
        assert "os.listdir('/output')" in result


class TestParseOutputFilesFromStdout:
    """Tests for parse_output_files_from_stdout helper function."""

    def test_extracts_single_file(self) -> None:
        """Should extract a single file from stdout."""
        stdout = 'Some output\n__OUTPUT_FILES__:["report.pdf"]\n'
        files, clean = parse_output_files_from_stdout(stdout)
        assert files == ["report.pdf"]
        assert "__OUTPUT_FILES__" not in clean

    def test_extracts_multiple_files(self) -> None:
        """Should extract multiple files from stdout."""
        stdout = '__OUTPUT_FILES__:["file1.txt", "file2.png", "file3.pdf"]\n'
        files, _clean = parse_output_files_from_stdout(stdout)
        assert files == ["file1.txt", "file2.png", "file3.pdf"]

    def test_preserves_other_output(self) -> None:
        """Should preserve stdout content that's not the marker."""
        stdout = "Hello World\nCalculation result: 42\n__OUTPUT_FILES__:[]\n"
        _files, clean = parse_output_files_from_stdout(stdout)
        assert "Hello World" in clean
        assert "Calculation result: 42" in clean
        assert "__OUTPUT_FILES__" not in clean

    def test_handles_no_marker(self) -> None:
        """Should handle stdout without the marker."""
        stdout = "Just some regular output\n"
        files, clean = parse_output_files_from_stdout(stdout)
        assert files == []
        assert "Just some regular output" in clean

    def test_handles_invalid_json(self) -> None:
        """Should handle malformed JSON gracefully."""
        stdout = "__OUTPUT_FILES__:not valid json\n"
        files, _clean = parse_output_files_from_stdout(stdout)
        assert files == []

    def test_handles_empty_stdout(self) -> None:
        """Should handle empty stdout."""
        files, clean = parse_output_files_from_stdout("")
        assert files == []
        assert clean == ""


class TestBuildExecutionResponse:
    """Tests for build_execution_response helper function."""

    def test_builds_success_response(self) -> None:
        """Should build response for successful execution."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stderr = ""

        response = build_execution_response(
            result=mock_result,
            clean_stdout="Hello World",
            file_metadata=[],
            full_result_files=[],
        )

        assert response["success"] is True
        assert response["exit_code"] == 0
        assert response["stdout"] == "Hello World"
        assert response["stderr"] == ""

    def test_builds_failure_response(self) -> None:
        """Should build response for failed execution."""
        mock_result = MagicMock()
        mock_result.exit_code = 1
        mock_result.stderr = "Error: something went wrong"

        response = build_execution_response(
            result=mock_result,
            clean_stdout="",
            file_metadata=[],
            full_result_files=[],
        )

        assert response["success"] is False
        assert response["exit_code"] == 1
        assert response["stderr"] == "Error: something went wrong"

    def test_includes_file_metadata(self) -> None:
        """Should include file metadata in response."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stderr = ""

        file_metadata = [
            {"name": "report.pdf", "mime_type": "application/pdf", "size": 1024},
        ]

        response = build_execution_response(
            result=mock_result,
            clean_stdout="",
            file_metadata=file_metadata,
            full_result_files=[],
        )

        assert "files" in response
        assert response["files"] == file_metadata
        assert "message" in response
        assert "report.pdf" in response["message"]

    def test_includes_full_result_files(self) -> None:
        """Should include _full_result with file data."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stderr = ""

        full_files = [{"name": "report.pdf", "data": "base64data", "size": 1024}]

        response = build_execution_response(
            result=mock_result,
            clean_stdout="",
            file_metadata=[],
            full_result_files=full_files,
        )

        assert "_full_result" in response
        assert response["_full_result"]["files"] == full_files

    def test_omits_empty_sections(self) -> None:
        """Should not include files keys when empty."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stderr = ""

        response = build_execution_response(
            result=mock_result,
            clean_stdout="output",
            file_metadata=[],
            full_result_files=[],
        )

        assert "files" not in response
        assert "_full_result" not in response
        assert "message" not in response

    def test_handles_none_stderr(self) -> None:
        """Should handle None stderr gracefully."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stderr = None

        response = build_execution_response(
            result=mock_result,
            clean_stdout="",
            file_metadata=[],
            full_result_files=[],
        )

        assert response["stderr"] == ""


class TestDiskFull:
    def test_a_full_sandbox_disk_is_explained(self) -> None:
        """/work is memory-backed and capped (Nov 16 2026): say so on ENOSPC."""
        result = MagicMock(exit_code=1, stderr="OSError: [Errno 28] No space left on device")
        response = build_execution_response(
            result=result, clean_stdout="", file_metadata=[], full_result_files=[]
        )
        assert "The sandbox disk is full: /work holds 256 MB, /output 64 MB" in response["stderr"]
