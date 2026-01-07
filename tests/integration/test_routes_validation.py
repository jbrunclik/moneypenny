"""Integration tests for request validation.

Tests that Pydantic validation is properly integrated with API routes
and returns correct error responses.
"""

import json
from typing import TYPE_CHECKING

from flask import Flask
from flask.testing import FlaskClient

if TYPE_CHECKING:
    from src.db.models import Conversation


class TestGoogleAuthValidation:
    """Tests for /auth/google validation."""

    def test_missing_credential(self, client: FlaskClient) -> None:
        """Should return 400 with field in error details."""
        response = client.post("/auth/google", json={})

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert data["error"]["details"]["field"] == "credential"

    def test_empty_credential(self, client: FlaskClient) -> None:
        """Should return 400 for empty credential."""
        response = client.post("/auth/google", json={"credential": ""})

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert data["error"]["details"]["field"] == "credential"

    def test_invalid_json(self, client: FlaskClient) -> None:
        """Should return 400 for malformed JSON.

        Note: Flask's get_json(silent=True) returns None for malformed JSON,
        which get_request_json() converts to {}. Pydantic then validates the
        empty dict and returns VALIDATION_ERROR for missing required fields.
        """
        response = client.post(
            "/auth/google", data="not valid json", content_type="application/json"
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        # Malformed JSON becomes empty dict, which fails schema validation
        assert data["error"]["code"] == "VALIDATION_ERROR"


class TestCreateConversationValidation:
    """Tests for POST /api/conversations validation."""

    def test_invalid_model(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should return 400 for invalid model with helpful message."""
        response = client.post(
            "/api/conversations",
            headers=auth_headers,
            json={"model": "nonexistent-model"},
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert data["error"]["details"]["field"] == "model"
        assert "Choose from" in data["error"]["message"]

    def test_accepts_empty_body(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should accept empty body (model is optional, defaults to default model)."""
        response = client.post(
            "/api/conversations",
            headers=auth_headers,
            json={},
        )

        assert response.status_code == 201


class TestUpdateConversationValidation:
    """Tests for PATCH /api/conversations/<conv_id> validation."""

    def test_invalid_model(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return 400 for invalid model."""
        response = client.patch(
            f"/api/conversations/{test_conversation.id}",
            headers=auth_headers,
            json={"model": "bad-model"},
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert data["error"]["details"]["field"] == "model"

    def test_empty_title(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return 400 for empty title."""
        response = client.patch(
            f"/api/conversations/{test_conversation.id}",
            headers=auth_headers,
            json={"title": ""},
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert data["error"]["details"]["field"] == "title"

    def test_title_too_long(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return 400 for title exceeding 200 characters."""
        response = client.patch(
            f"/api/conversations/{test_conversation.id}",
            headers=auth_headers,
            json={"title": "x" * 201},
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert data["error"]["details"]["field"] == "title"

    def test_accepts_valid_update(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should accept valid title update."""
        response = client.patch(
            f"/api/conversations/{test_conversation.id}",
            headers=auth_headers,
            json={"title": "New Title"},
        )

        assert response.status_code == 200


class TestChatBatchValidation:
    """Tests for POST /api/conversations/<conv_id>/chat/batch validation."""

    def test_neither_message_nor_files(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return 400 when neither message nor files provided."""
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/batch",
            headers=auth_headers,
            json={},
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "Message or files required" in data["error"]["message"]

    def test_whitespace_only_message(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should treat whitespace-only message as empty."""
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/batch",
            headers=auth_headers,
            json={"message": "   "},
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "Message or files required" in data["error"]["message"]

    def test_invalid_file_type(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return 400 for invalid file MIME type."""
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/batch",
            headers=auth_headers,
            json={
                "message": "",
                "files": [
                    {"name": "test.exe", "type": "application/x-executable", "data": "base64"}
                ],
            },
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "not allowed" in data["error"]["message"]
        # Field path should include files array index
        assert "files" in data["error"]["details"]["field"]

    def test_too_many_files(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return 400 when too many files attached."""
        # Create 15 files (exceeds default MAX_FILES_PER_MESSAGE of 10)
        files = [{"name": f"test{i}.png", "type": "image/png", "data": "base64"} for i in range(15)]
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/batch",
            headers=auth_headers,
            json={"message": "", "files": files},
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "Too many files" in data["error"]["message"]

    def test_missing_file_fields(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return 400 for file missing required fields."""
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/batch",
            headers=auth_headers,
            json={
                "message": "",
                "files": [{"name": "test.png"}],  # Missing type and data
            },
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"]["code"] == "VALIDATION_ERROR"

    def test_invalid_json(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return 400 for malformed JSON.

        Note: Malformed JSON becomes empty dict via get_request_json(),
        which then fails Pydantic validation for "Message or files required".
        """
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/batch",
            headers=auth_headers,
            data="not valid json",
            content_type="application/json",
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        # Malformed JSON becomes empty dict, which fails schema validation
        assert data["error"]["code"] == "VALIDATION_ERROR"


class TestChatStreamValidation:
    """Tests for POST /api/conversations/<conv_id>/chat/stream validation."""

    def test_neither_message_nor_files(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return 400 when neither message nor files provided."""
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stream",
            headers=auth_headers,
            json={},
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "Message or files required" in data["error"]["message"]

    def test_invalid_file_type(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_conversation: Conversation,
    ) -> None:
        """Should return 400 for invalid file MIME type."""
        response = client.post(
            f"/api/conversations/{test_conversation.id}/chat/stream",
            headers=auth_headers,
            json={
                "message": "",
                "files": [{"name": "bad.zip", "type": "application/zip", "data": "base64"}],
            },
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert "not allowed" in data["error"]["message"]


class TestValidationErrorFormat:
    """Tests for validation error response format."""

    def test_error_structure(self, client: FlaskClient, auth_headers: dict[str, str]) -> None:
        """Should return standardized error structure."""
        response = client.post(
            "/api/conversations",
            headers=auth_headers,
            json={"model": "invalid-model"},
        )

        assert response.status_code == 400
        data = json.loads(response.data)

        # Check error structure
        assert "error" in data
        error = data["error"]
        assert "code" in error
        assert "message" in error
        assert "retryable" in error
        assert error["retryable"] is False  # Validation errors are not retryable
        assert "details" in error
        assert "field" in error["details"]

    def test_custom_validator_message_cleaned(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should not include 'Value error, ' prefix in messages."""
        response = client.post(
            "/api/conversations",
            headers=auth_headers,
            json={"model": "invalid-model"},
        )

        data = json.loads(response.data)
        message = data["error"]["message"]

        # Message should not contain the "Value error, " prefix that Pydantic adds
        assert not message.startswith("Value error")
        # But should contain the actual validation message
        assert "Invalid model" in message or "Choose from" in message


class TestRequestSizeLimit:
    """Tests for request body size limits (DoS protection)."""

    def test_payload_too_large_returns_413(self, app: Flask, auth_headers: dict[str, str]) -> None:
        """Should return 413 when request body exceeds MAX_CONTENT_LENGTH."""
        # Temporarily set a very low limit on the app
        original_limit = app.config.get("MAX_CONTENT_LENGTH")
        app.config["MAX_CONTENT_LENGTH"] = 100  # 100 bytes

        try:
            client = app.test_client()
            large_data = "x" * 200  # 200 bytes > 100 byte limit
            response = client.post(
                "/api/conversations",
                headers=auth_headers,
                data=large_data,
                content_type="application/json",
            )

            # Flask raises RequestEntityTooLarge which becomes 413
            assert response.status_code == 413
            data = json.loads(response.data)
            assert data["error"]["code"] == "PAYLOAD_TOO_LARGE"
            assert data["error"]["retryable"] is False
        finally:
            app.config["MAX_CONTENT_LENGTH"] = original_limit

    def test_normal_request_succeeds(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        """Should accept normal-sized requests."""
        response = client.post(
            "/api/conversations",
            headers=auth_headers,
            json={"model": "gemini-3-flash-preview"},
        )

        # Should succeed (201 for create)
        assert response.status_code == 201
