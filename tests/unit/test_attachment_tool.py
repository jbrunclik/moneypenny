"""Unit tests for the create_file tool (src/agent/tools/attachment.py)."""

import base64
import json


class TestCreateFile:
    """Tests for the create_file attachment tool."""

    def test_creates_zwo_attachment(self) -> None:
        """Should base64-encode text content into a _full_result file entry."""
        from src.agent.tools import create_file

        xml = "<workout_file><name>Test</name></workout_file>"
        result = json.loads(create_file.invoke({"filename": "ride.zwo", "content": xml}))

        assert result["success"] is True
        # Metadata visible to the LLM must NOT carry the base64 payload.
        assert result["file"] == {
            "name": "ride.zwo",
            "mime_type": "application/xml",
            "size": len(xml.encode("utf-8")),
        }
        files = result["_full_result"]["files"]
        assert len(files) == 1
        assert files[0]["name"] == "ride.zwo"
        assert files[0]["mime_type"] == "application/xml"
        assert base64.b64decode(files[0]["data"]).decode("utf-8") == xml

    def test_explicit_mime_type_overrides_guess(self) -> None:
        from src.agent.tools import create_file

        result = json.loads(
            create_file.invoke({"filename": "data.bin", "content": "hi", "mime_type": "text/plain"})
        )
        assert result["file"]["mime_type"] == "text/plain"

    def test_guesses_csv_mime_type(self) -> None:
        from src.agent.tools import create_file

        result = json.loads(create_file.invoke({"filename": "plan.csv", "content": "a,b\n1,2"}))
        assert result["file"]["mime_type"] == "text/csv"

    def test_strips_path_from_filename(self) -> None:
        """A path in the filename must be reduced to its base name."""
        from src.agent.tools import create_file

        result = json.loads(create_file.invoke({"filename": "../../etc/passwd", "content": "x"}))
        assert result["file"]["name"] == "passwd"

    def test_rejects_empty_filename(self) -> None:
        from src.agent.tools import create_file

        result = json.loads(create_file.invoke({"filename": "  ", "content": "x"}))
        assert result["success"] is False

    def test_rejects_empty_content(self) -> None:
        from src.agent.tools import create_file

        result = json.loads(create_file.invoke({"filename": "a.txt", "content": ""}))
        assert result["success"] is False

    def test_rejects_oversized_content(self) -> None:
        from src.agent.tools import create_file
        from src.agent.tools.attachment import MAX_ATTACHMENT_BYTES

        result = json.loads(
            create_file.invoke({"filename": "big.txt", "content": "x" * (MAX_ATTACHMENT_BYTES + 1)})
        )
        assert result["success"] is False
        assert "_full_result" not in result

    def test_result_flows_to_attachment_extraction(self) -> None:
        """create_file output must surface through the shared attachment pipeline."""
        from src.agent.tools import create_file
        from src.utils.images import extract_code_output_files_from_tool_results

        content = create_file.invoke({"filename": "ride.zwo", "content": "<x/>"})
        files = extract_code_output_files_from_tool_results([{"type": "tool", "content": content}])
        assert len(files) == 1
        assert files[0]["name"] == "ride.zwo"
