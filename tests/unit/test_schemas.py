"""Unit tests for Pydantic request schemas."""

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.api.schemas import (
    ChatRequest,
    CreateConversationRequest,
    FileAttachment,
    GoogleAuthRequest,
    UpdateConversationRequest,
)


class TestGoogleAuthRequest:
    """Tests for GoogleAuthRequest schema."""

    def test_valid_credential(self) -> None:
        """Should accept valid credential."""
        data = GoogleAuthRequest(credential="valid-token-xyz")
        assert data.credential == "valid-token-xyz"

    def test_missing_credential(self) -> None:
        """Should reject missing credential."""
        with pytest.raises(ValidationError) as exc_info:
            GoogleAuthRequest()  # type: ignore[call-arg]
        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("credential",)
        assert errors[0]["type"] == "missing"

    def test_empty_credential(self) -> None:
        """Should reject empty credential."""
        with pytest.raises(ValidationError) as exc_info:
            GoogleAuthRequest(credential="")
        errors = exc_info.value.errors()
        assert errors[0]["loc"] == ("credential",)
        assert "at least 1 character" in errors[0]["msg"]


class TestFileAttachment:
    """Tests for FileAttachment schema."""

    def test_valid_file(self) -> None:
        """Should accept valid file."""
        data = FileAttachment(name="test.png", type="image/png", data="base64data")
        assert data.name == "test.png"
        assert data.type == "image/png"
        assert data.data == "base64data"

    def test_missing_name(self) -> None:
        """Should reject missing name."""
        with pytest.raises(ValidationError) as exc_info:
            FileAttachment(type="image/png", data="base64data")  # type: ignore[call-arg]
        errors = exc_info.value.errors()
        assert errors[0]["loc"] == ("name",)

    def test_empty_name(self) -> None:
        """Should reject empty name."""
        with pytest.raises(ValidationError) as exc_info:
            FileAttachment(name="", type="image/png", data="base64data")
        errors = exc_info.value.errors()
        assert errors[0]["loc"] == ("name",)

    def test_name_too_long(self) -> None:
        """Should reject name exceeding 255 characters."""
        with pytest.raises(ValidationError) as exc_info:
            FileAttachment(name="x" * 256, type="image/png", data="base64data")
        errors = exc_info.value.errors()
        assert errors[0]["loc"] == ("name",)
        assert "at most 255 characters" in errors[0]["msg"]

    def test_invalid_mime_type(self) -> None:
        """Should reject invalid MIME type."""
        with pytest.raises(ValidationError) as exc_info:
            FileAttachment(name="test.exe", type="application/x-executable", data="base64data")
        errors = exc_info.value.errors()
        assert errors[0]["loc"] == ("type",)
        assert "not allowed" in errors[0]["msg"]

    def test_empty_data(self) -> None:
        """Should reject empty data."""
        with pytest.raises(ValidationError) as exc_info:
            FileAttachment(name="test.png", type="image/png", data="")
        errors = exc_info.value.errors()
        assert errors[0]["loc"] == ("data",)


class TestCreateConversationRequest:
    """Tests for CreateConversationRequest schema."""

    def test_empty_request(self) -> None:
        """Should accept empty request (model is optional)."""
        data = CreateConversationRequest()
        assert data.model is None

    def test_valid_model(self) -> None:
        """Should accept valid model."""
        data = CreateConversationRequest(model="gemini-3-flash-preview")
        assert data.model == "gemini-3-flash-preview"

    def test_invalid_model(self) -> None:
        """Should reject invalid model."""
        with pytest.raises(ValidationError) as exc_info:
            CreateConversationRequest(model="nonexistent-model")
        errors = exc_info.value.errors()
        assert errors[0]["loc"] == ("model",)
        assert "Invalid model" in errors[0]["msg"]
        assert "Choose from" in errors[0]["msg"]

    def test_null_model(self) -> None:
        """Should accept null model."""
        data = CreateConversationRequest(model=None)
        assert data.model is None


class TestUpdateConversationRequest:
    """Tests for UpdateConversationRequest schema."""

    def test_empty_request(self) -> None:
        """Should accept empty request (all fields optional)."""
        data = UpdateConversationRequest()
        assert data.title is None
        assert data.model is None

    def test_valid_title(self) -> None:
        """Should accept valid title."""
        data = UpdateConversationRequest(title="My Conversation")
        assert data.title == "My Conversation"

    def test_empty_title(self) -> None:
        """Should reject empty title."""
        with pytest.raises(ValidationError) as exc_info:
            UpdateConversationRequest(title="")
        errors = exc_info.value.errors()
        assert errors[0]["loc"] == ("title",)

    def test_title_too_long(self) -> None:
        """Should reject title exceeding 200 characters."""
        with pytest.raises(ValidationError) as exc_info:
            UpdateConversationRequest(title="x" * 201)
        errors = exc_info.value.errors()
        assert errors[0]["loc"] == ("title",)
        assert "at most 200 characters" in errors[0]["msg"]

    def test_valid_model(self) -> None:
        """Should accept valid model."""
        data = UpdateConversationRequest(model="gemini-3.1-pro-preview")
        assert data.model == "gemini-3.1-pro-preview"

    def test_invalid_model(self) -> None:
        """Should reject invalid model."""
        with pytest.raises(ValidationError) as exc_info:
            UpdateConversationRequest(model="bad-model")
        errors = exc_info.value.errors()
        assert errors[0]["loc"] == ("model",)
        assert "Invalid model" in errors[0]["msg"]

    def test_both_fields(self) -> None:
        """Should accept both title and model."""
        data = UpdateConversationRequest(title="New Title", model="gemini-3-flash-preview")
        assert data.title == "New Title"
        assert data.model == "gemini-3-flash-preview"


class TestChatRequest:
    """Tests for ChatRequest schema."""

    def test_message_only(self) -> None:
        """Should accept message without files."""
        data = ChatRequest(message="Hello")
        assert data.message == "Hello"
        assert data.files == []
        assert data.force_tools == []

    def test_files_only(self) -> None:
        """Should accept files without message."""
        data = ChatRequest(
            message="", files=[{"name": "test.png", "type": "image/png", "data": "base64"}]
        )
        assert data.message == ""
        assert len(data.files) == 1
        assert data.files[0].name == "test.png"

    def test_both_message_and_files(self) -> None:
        """Should accept both message and files."""
        data = ChatRequest(
            message="Check this",
            files=[{"name": "test.png", "type": "image/png", "data": "base64"}],
        )
        assert data.message == "Check this"
        assert len(data.files) == 1

    def test_neither_message_nor_files(self) -> None:
        """Should reject when neither message nor files."""
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(message="", files=[])
        errors = exc_info.value.errors()
        assert "Message or files required" in errors[0]["msg"]

    def test_whitespace_only_message(self) -> None:
        """Should treat whitespace-only message as empty."""
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(message="   ", files=[])
        errors = exc_info.value.errors()
        assert "Message or files required" in errors[0]["msg"]

    def test_empty_request(self) -> None:
        """Should reject completely empty request."""
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest()
        errors = exc_info.value.errors()
        assert "Message or files required" in errors[0]["msg"]

    @patch("src.api.schemas.Config.MAX_FILES_PER_MESSAGE", 10)
    def test_too_many_files(self) -> None:
        """Should reject too many files."""
        files = [{"name": f"test{i}.png", "type": "image/png", "data": "base64"} for i in range(15)]
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(message="", files=files)
        errors = exc_info.value.errors()
        assert "Too many files" in errors[0]["msg"]

    def test_force_tools(self) -> None:
        """Should accept force_tools list."""
        data = ChatRequest(message="Search for X", force_tools=["web_search"])
        assert data.force_tools == ["web_search"]

    def test_multiple_force_tools(self) -> None:
        """Should accept multiple force_tools."""
        data = ChatRequest(message="Do things", force_tools=["web_search", "fetch_url"])
        assert data.force_tools == ["web_search", "fetch_url"]

    def test_invalid_file_in_list(self) -> None:
        """Should reject invalid file in files list."""
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(
                message="",
                files=[{"name": "test.exe", "type": "application/x-executable", "data": "base64"}],
            )
        errors = exc_info.value.errors()
        assert "files" in str(errors[0]["loc"])
        assert "not allowed" in errors[0]["msg"]

    def test_model_dump_for_files(self) -> None:
        """Should be able to convert files to dicts for validate_files()."""
        data = ChatRequest(
            message="Test", files=[{"name": "test.png", "type": "image/png", "data": "base64data"}]
        )
        # Convert to dicts for validate_files()
        files_as_dicts = [f.model_dump() for f in data.files]
        assert files_as_dicts == [{"name": "test.png", "type": "image/png", "data": "base64data"}]
