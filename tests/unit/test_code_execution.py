"""Unit tests for the execute_code tool (src/agent/tools/code_execution.py)."""

import json
from unittest.mock import MagicMock, patch

from src.agent.tools import (
    execute_code,
    is_code_sandbox_available,
)
from src.agent.tools.code_execution import _get_mime_type


class TestGetMimeType:
    """Tests for _get_mime_type helper function."""

    def test_pdf_mime_type(self) -> None:
        """Should return correct MIME type for PDF."""
        assert _get_mime_type("report.pdf") == "application/pdf"

    def test_png_mime_type(self) -> None:
        """Should return correct MIME type for PNG."""
        assert _get_mime_type("image.png") == "image/png"

    def test_jpg_mime_type(self) -> None:
        """Should return correct MIME type for JPG."""
        assert _get_mime_type("photo.jpg") == "image/jpeg"
        assert _get_mime_type("photo.jpeg") == "image/jpeg"

    def test_csv_mime_type(self) -> None:
        """Should return correct MIME type for CSV."""
        assert _get_mime_type("data.csv") == "text/csv"

    def test_unknown_extension(self) -> None:
        """Should return octet-stream for unknown extensions."""
        assert _get_mime_type("file.qwxyz123") == "application/octet-stream"

    def test_no_extension(self) -> None:
        """Should return octet-stream for files without extension."""
        assert _get_mime_type("filename") == "application/octet-stream"


class TestExecuteCode:
    """Tests for execute_code tool."""

    def test_wrapped_code_resets_output_and_creates_work(self) -> None:
        """Each run starts with a clean /output; /work persists across runs."""
        from src.agent.tools.code_execution import _wrap_user_code

        wrapped = _wrap_user_code("print('hi')")
        assert "shutil.rmtree('/output', ignore_errors=True)" in wrapped
        assert "os.makedirs('/output', exist_ok=True)" in wrapped
        assert "os.makedirs('/work', exist_ok=True)" in wrapped

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    @patch("src.agent.tools.code_execution.get_sandbox_pool")
    def test_uses_pooled_session_for_conversation(
        self, mock_get_pool: MagicMock, mock_check: MagicMock
    ) -> None:
        """execute_code must request the pool session keyed by conversation id."""
        from src.agent.tools.context import set_conversation_context

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = "1\n"
        mock_result.stderr = ""
        mock_result.plots = []

        fake_session = MagicMock()
        fake_session.run.return_value = mock_result

        pool = MagicMock()
        pool.session.return_value.__enter__ = MagicMock(return_value=fake_session)
        pool.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_pool.return_value = pool

        set_conversation_context("conv-42", "user-1")
        try:
            result = execute_code.invoke({"code": "print(1)"})
        finally:
            set_conversation_context(None, None)

        parsed = json.loads(result)
        assert parsed["success"] is True
        assert pool.session.call_args[0][0] == "conv-42"

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", False)
    def test_returns_error_when_disabled(self) -> None:
        """Should return error when sandbox is disabled."""
        result = execute_code.invoke({"code": "print('hello')"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "disabled" in parsed["error"].lower()

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=False)
    def test_returns_error_when_docker_unavailable(self, mock_check: MagicMock) -> None:
        """Should return error when Docker is not available."""
        result = execute_code.invoke({"code": "print('hello')"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "Docker" in parsed["error"] or "not available" in parsed["error"].lower()

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    def test_rejects_empty_code(self, mock_check: MagicMock) -> None:
        """Should reject empty code."""
        result = execute_code.invoke({"code": ""})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "empty" in parsed["error"].lower()

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    def test_rejects_whitespace_only_code(self, mock_check: MagicMock) -> None:
        """Should reject whitespace-only code."""
        result = execute_code.invoke({"code": "   "})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "empty" in parsed["error"].lower()

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    @patch("llm_sandbox.SandboxSession")
    def test_successful_execution(
        self, mock_session_class: MagicMock, mock_check: MagicMock
    ) -> None:
        """Should return success for valid code execution."""
        # Mock the sandbox session
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = "Hello, World!\n"
        mock_result.stderr = ""
        mock_result.plots = []

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = mock_result
        mock_session_class.return_value = mock_session

        result = execute_code.invoke({"code": "print('Hello, World!')"})
        parsed = json.loads(result)

        assert parsed["success"] is True
        assert parsed["exit_code"] == 0
        assert "Hello, World!" in parsed["stdout"]

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    @patch("llm_sandbox.SandboxSession")
    def test_sandbox_network_disabled_and_limited(
        self, mock_session_class: MagicMock, mock_check: MagicMock
    ) -> None:
        """The sandbox container must be created with networking disabled and
        resource limits applied (S4) - llm-sandbox does NOT do this by default."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.plots = []

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = mock_result
        mock_session_class.return_value = mock_session

        execute_code.invoke({"code": "print('hi')"})

        kwargs = mock_session_class.call_args.kwargs
        assert kwargs["runtime_configs"]["network_disabled"] is True
        assert kwargs["runtime_configs"]["mem_limit"]
        assert kwargs["runtime_configs"]["nano_cpus"] > 0
        # init (tini) as PID 1 so SIGTERM is handled - without it container
        # teardown waits the full ~10s docker-stop grace on every call
        assert kwargs["runtime_configs"]["init"] is True
        # Setup is skipped: libraries are baked into the image, and the
        # default setup's pip upgrade would need the disabled network
        assert kwargs["skip_environment_setup"] is True
        # No libraries arg: install() raises with skip_environment_setup=True
        assert mock_session.run.call_args.kwargs.get("libraries") is None
        assert len(mock_session.run.call_args.args) == 1

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    @patch("llm_sandbox.SandboxSession")
    def test_captures_stderr(self, mock_session_class: MagicMock, mock_check: MagicMock) -> None:
        """Should capture stderr from execution."""
        mock_result = MagicMock()
        mock_result.exit_code = 1
        mock_result.stdout = ""
        mock_result.stderr = "NameError: name 'undefined_var' is not defined"
        mock_result.plots = []

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = mock_result
        mock_session_class.return_value = mock_session

        result = execute_code.invoke({"code": "print(undefined_var)"})
        parsed = json.loads(result)

        assert parsed["success"] is False
        assert parsed["exit_code"] == 1
        assert "NameError" in parsed["stderr"]

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    @patch("llm_sandbox.SandboxSession")
    def test_captures_plots(self, mock_session_class: MagicMock, mock_check: MagicMock) -> None:
        """Should capture matplotlib plots with metadata in response and data in _full_result."""
        mock_plot = MagicMock()
        mock_plot.format = MagicMock()
        mock_plot.format.value = "png"
        mock_plot.content_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"

        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock_result.plots = [mock_plot]

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = mock_result
        mock_session_class.return_value = mock_session

        result = execute_code.invoke(
            {"code": "import matplotlib.pyplot as plt; plt.plot([1,2,3]); plt.show()"}
        )
        parsed = json.loads(result)

        assert parsed["success"] is True
        # LLM sees only metadata (no base64 data)
        assert "plots" in parsed
        assert len(parsed["plots"]) == 1
        assert parsed["plots"][0]["format"] == "png"
        assert parsed["plots"][0]["name"] == "plot_1.png"
        assert "data" not in parsed["plots"][0]  # Data is in _full_result

        # Full data is in _full_result for server-side extraction
        assert "_full_result" in parsed
        assert "files" in parsed["_full_result"]
        assert len(parsed["_full_result"]["files"]) == 1
        assert parsed["_full_result"]["files"][0]["name"] == "plot_1.png"
        assert parsed["_full_result"]["files"][0]["data"] == mock_plot.content_base64

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    @patch("llm_sandbox.SandboxSession")
    def test_output_files_uses_full_result_pattern(
        self, mock_session_class: MagicMock, mock_check: MagicMock
    ) -> None:
        """Should put file data in _full_result and only metadata in response."""
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.stdout = '__OUTPUT_FILES__:["report.pdf"]\n'
        mock_result.stderr = ""
        mock_result.plots = []

        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.return_value = mock_result

        # Mock file extraction from sandbox
        def copy_from_runtime(src: str, dest: str) -> None:
            with open(dest, "wb") as f:
                f.write(b"PDF content here")

        mock_session.copy_from_runtime = copy_from_runtime
        mock_session_class.return_value = mock_session

        result = execute_code.invoke({"code": "generate_pdf()"})
        parsed = json.loads(result)

        assert parsed["success"] is True

        # LLM sees only metadata (filename, type, size - no data)
        assert "files" in parsed
        assert len(parsed["files"]) == 1
        assert parsed["files"][0]["name"] == "report.pdf"
        assert parsed["files"][0]["mime_type"] == "application/pdf"
        assert parsed["files"][0]["size"] == 16  # len(b"PDF content here")
        assert "data" not in parsed["files"][0]  # Data is NOT in the files list

        # Message for LLM to inform user
        assert "message" in parsed
        assert "report.pdf" in parsed["message"]

        # Full data is in _full_result for server-side extraction
        assert "_full_result" in parsed
        assert "files" in parsed["_full_result"]
        assert len(parsed["_full_result"]["files"]) == 1
        assert parsed["_full_result"]["files"][0]["name"] == "report.pdf"
        assert "data" in parsed["_full_result"]["files"][0]  # Data IS here

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    @patch("llm_sandbox.SandboxSession")
    def test_handles_timeout(self, mock_session_class: MagicMock, mock_check: MagicMock) -> None:
        """Should handle execution timeout."""
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.run.side_effect = TimeoutError("Execution timed out")
        mock_session_class.return_value = mock_session

        result = execute_code.invoke({"code": "while True: pass"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "timed out" in parsed["error"].lower()

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    @patch("llm_sandbox.SandboxSession")
    def test_handles_docker_error(
        self, mock_session_class: MagicMock, mock_check: MagicMock
    ) -> None:
        """Should handle Docker connection errors gracefully."""
        mock_session_class.side_effect = Exception("Cannot connect to Docker daemon")

        result = execute_code.invoke({"code": "print('test')"})
        parsed = json.loads(result)

        assert "error" in parsed
        assert "Docker" in parsed["error"] or "failed" in parsed["error"].lower()


class TestIsCodeSandboxAvailable:
    """Tests for is_code_sandbox_available function."""

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", False)
    def test_returns_false_when_disabled(self) -> None:
        """Should return False when sandbox is disabled in config."""
        assert is_code_sandbox_available() is False

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=False)
    def test_returns_false_when_docker_unavailable(self, mock_check: MagicMock) -> None:
        """Should return False when Docker is not available."""
        assert is_code_sandbox_available() is False

    @patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True)
    @patch("src.agent.tools.code_execution._check_docker_available", return_value=True)
    def test_returns_true_when_available(self, mock_check: MagicMock) -> None:
        """Should return True when sandbox is enabled and Docker is available."""
        assert is_code_sandbox_available() is True


class TestSandboxLibraryListsMatchImage:
    """The prompt and tool docstring promise exactly what the image installs.

    The model is told "the environment is fixed - do not probe it", so a
    library missing from the list goes unused and a listed-but-absent one
    fails at run time.
    """

    @staticmethod
    def _image_packages() -> set[str]:
        from pathlib import Path

        dockerfile = Path(__file__).parents[2] / "docker/code-sandbox/Dockerfile"
        text = dockerfile.read_text()
        pip_block = text.split("pip install --no-cache-dir", 1)[1].split("\n\n", 1)[0]
        return {tok for tok in pip_block.replace("\\", " ").split() if tok and tok != "&&"}

    @staticmethod
    def _listed(line: str) -> set[str]:
        return {name.strip() for name in line.split(":", 1)[1].split(",") if name.strip()}

    def test_prompt_lists_every_installed_package(self) -> None:
        from src.agent.prompt_texts.core import TOOLS_SYSTEM_PROMPT_BASE

        line = next(ln for ln in TOOLS_SYSTEM_PROMPT_BASE.splitlines() if "Pre-installed:" in ln)
        assert self._listed(line) == self._image_packages()

    def test_docstring_lists_every_installed_package(self) -> None:
        doc = execute_code.description
        section = doc.split("## Pre-installed Libraries", 1)[1].strip().splitlines()[0]
        assert self._listed(f"x:{section}") == self._image_packages()

    def test_image_has_office_document_libraries(self) -> None:
        assert {"python-docx", "python-pptx", "openpyxl"} <= self._image_packages()


class TestCancelKillsUserCode:
    def test_cancel_during_run_kills_the_user_process(self) -> None:
        from src.agent import cancellation
        from src.agent.tool_results import set_current_request_id

        set_current_request_id("req-code")
        token = cancellation.register_token("req-code")
        session = MagicMock()

        def run(_code: str) -> MagicMock:
            token.cancel()  # Stop pressed while the code runs
            return MagicMock(exit_code=137, stdout="", stderr="")

        session.run.side_effect = run
        pool = MagicMock()
        pool.session.return_value.__enter__.return_value = session
        try:
            with (
                patch("src.agent.tools.code_execution._check_docker_available", return_value=True),
                patch("src.agent.tools.code_execution.get_sandbox_pool", return_value=pool),
                patch("src.agent.tools.code_execution.Config.CODE_SANDBOX_ENABLED", True),
            ):
                execute_code.invoke({"code": "import time; time.sleep(30)"})
        finally:
            cancellation.unregister_token("req-code")
            set_current_request_id(None)

        kill_call = session.container.exec_run.call_args
        assert kill_call.kwargs["user"] == "root"
