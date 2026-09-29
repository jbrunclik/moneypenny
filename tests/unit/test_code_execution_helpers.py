"""Unit tests for code execution helper functions (src/agent/tools/code_execution.py)."""

from unittest.mock import MagicMock

from src.agent.tools.code_execution import (
    _build_execution_response,
    _extract_plots,
    _parse_output_files_from_stdout,
    _wrap_user_code,
)

# ============================================================================
# Tests for Code Execution Helper Functions
# ============================================================================


class TestWrapUserCode:
    """Tests for _wrap_user_code helper function."""

    def test_creates_output_directory(self) -> None:
        """Should create /output directory at start."""
        result = _wrap_user_code("print('test')")
        assert "os.makedirs('/output', exist_ok=True)" in result

    def test_includes_user_code(self) -> None:
        """Should include the user's code."""
        user_code = "x = 1 + 1\nprint(x)"
        result = _wrap_user_code(user_code)
        assert user_code in result

    def test_adds_file_listing(self) -> None:
        """Should add code to list output files."""
        result = _wrap_user_code("print('test')")
        assert "__OUTPUT_FILES__" in result
        assert "os.listdir('/output')" in result


class TestParseOutputFilesFromStdout:
    """Tests for _parse_output_files_from_stdout helper function."""

    def test_extracts_single_file(self) -> None:
        """Should extract a single file from stdout."""
        stdout = 'Some output\n__OUTPUT_FILES__:["report.pdf"]\n'
        files, clean = _parse_output_files_from_stdout(stdout)
        assert files == ["report.pdf"]
        assert "__OUTPUT_FILES__" not in clean

    def test_extracts_multiple_files(self) -> None:
        """Should extract multiple files from stdout."""
        stdout = '__OUTPUT_FILES__:["file1.txt", "file2.png", "file3.pdf"]\n'
        files, clean = _parse_output_files_from_stdout(stdout)
        assert files == ["file1.txt", "file2.png", "file3.pdf"]

    def test_preserves_other_output(self) -> None:
        """Should preserve stdout content that's not the marker."""
        stdout = "Hello World\nCalculation result: 42\n__OUTPUT_FILES__:[]\n"
        files, clean = _parse_output_files_from_stdout(stdout)
        assert "Hello World" in clean
        assert "Calculation result: 42" in clean
        assert "__OUTPUT_FILES__" not in clean

    def test_handles_no_marker(self) -> None:
        """Should handle stdout without the marker."""
        stdout = "Just some regular output\n"
        files, clean = _parse_output_files_from_stdout(stdout)
        assert files == []
        assert "Just some regular output" in clean

    def test_handles_invalid_json(self) -> None:
        """Should handle malformed JSON gracefully."""
        stdout = "__OUTPUT_FILES__:not valid json\n"
        files, clean = _parse_output_files_from_stdout(stdout)
        assert files == []

    def test_handles_empty_stdout(self) -> None:
        """Should handle empty stdout."""
        files, clean = _parse_output_files_from_stdout("")
        assert files == []
        assert clean == ""


class TestExtractPlots:
    """Tests for _extract_plots helper function."""

    def test_extracts_single_plot(self) -> None:
        """Should extract a single matplotlib plot."""
        mock_plot = MagicMock()
        mock_plot.format = MagicMock()
        mock_plot.format.value = "png"
        mock_plot.content_base64 = "iVBORw0KGgo="

        mock_result = MagicMock()
        mock_result.plots = [mock_plot]

        full_plots, metadata = _extract_plots(mock_result)

        assert len(full_plots) == 1
        assert full_plots[0]["name"] == "plot_1.png"
        assert full_plots[0]["data"] == "iVBORw0KGgo="
        assert full_plots[0]["mime_type"] == "image/png"

        assert len(metadata) == 1
        assert metadata[0]["name"] == "plot_1.png"
        assert metadata[0]["format"] == "png"

    def test_extracts_multiple_plots(self) -> None:
        """Should extract multiple plots with sequential names."""
        mock_plot1 = MagicMock()
        mock_plot1.format = MagicMock()
        mock_plot1.format.value = "png"
        mock_plot1.content_base64 = "aGVsbG8="  # Valid base64 for "hello"

        mock_plot2 = MagicMock()
        mock_plot2.format = MagicMock()
        mock_plot2.format.value = "jpeg"
        mock_plot2.content_base64 = "d29ybGQ="  # Valid base64 for "world"

        mock_result = MagicMock()
        mock_result.plots = [mock_plot1, mock_plot2]

        full_plots, metadata = _extract_plots(mock_result)

        assert len(full_plots) == 2
        assert full_plots[0]["name"] == "plot_1.png"
        assert full_plots[1]["name"] == "plot_2.jpeg"

    def test_handles_no_plots(self) -> None:
        """Should handle result with no plots."""
        mock_result = MagicMock()
        mock_result.plots = []

        full_plots, metadata = _extract_plots(mock_result)

        assert full_plots == []
        assert metadata == []

    def test_handles_missing_plots_attribute(self) -> None:
        """Should handle result without plots attribute."""
        mock_result = MagicMock(spec=[])  # No attributes

        full_plots, metadata = _extract_plots(mock_result)

        assert full_plots == []
        assert metadata == []

    def test_handles_string_format(self) -> None:
        """Should handle format as string instead of enum."""
        mock_plot = MagicMock()
        mock_plot.format = "svg"  # String, not enum
        mock_plot.content_base64 = "c3ZnX2RhdGE="  # Valid base64 for "svg_data"

        mock_result = MagicMock()
        mock_result.plots = [mock_plot]

        full_plots, metadata = _extract_plots(mock_result)

        assert full_plots[0]["name"] == "plot_1.svg"
        assert full_plots[0]["mime_type"] == "image/svg"


class TestBuildExecutionResponse:
    """Tests for _build_execution_response helper function."""

    def test_builds_success_response(self) -> None:
        """Should build response for successful execution."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stderr = ""

        response = _build_execution_response(
            result=mock_result,
            clean_stdout="Hello World",
            file_metadata=[],
            plot_metadata=[],
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

        response = _build_execution_response(
            result=mock_result,
            clean_stdout="",
            file_metadata=[],
            plot_metadata=[],
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

        response = _build_execution_response(
            result=mock_result,
            clean_stdout="",
            file_metadata=file_metadata,
            plot_metadata=[],
            full_result_files=[],
        )

        assert "files" in response
        assert response["files"] == file_metadata
        assert "message" in response
        assert "report.pdf" in response["message"]

    def test_includes_plot_metadata(self) -> None:
        """Should include plot metadata in response."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stderr = ""

        plot_metadata = [{"format": "png", "name": "plot_1.png"}]

        response = _build_execution_response(
            result=mock_result,
            clean_stdout="",
            file_metadata=[],
            plot_metadata=plot_metadata,
            full_result_files=[],
        )

        assert "plots" in response
        assert response["plots"] == plot_metadata

    def test_includes_full_result_files(self) -> None:
        """Should include _full_result with file data."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stderr = ""

        full_files = [{"name": "report.pdf", "data": "base64data", "size": 1024}]

        response = _build_execution_response(
            result=mock_result,
            clean_stdout="",
            file_metadata=[],
            plot_metadata=[],
            full_result_files=full_files,
        )

        assert "_full_result" in response
        assert response["_full_result"]["files"] == full_files

    def test_omits_empty_sections(self) -> None:
        """Should not include files/plots keys when empty."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stderr = ""

        response = _build_execution_response(
            result=mock_result,
            clean_stdout="output",
            file_metadata=[],
            plot_metadata=[],
            full_result_files=[],
        )

        assert "files" not in response
        assert "plots" not in response
        assert "_full_result" not in response
        assert "message" not in response

    def test_handles_none_stderr(self) -> None:
        """Should handle None stderr gracefully."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stderr = None

        response = _build_execution_response(
            result=mock_result,
            clean_stdout="",
            file_metadata=[],
            plot_metadata=[],
            full_result_files=[],
        )

        assert response["stderr"] == ""
