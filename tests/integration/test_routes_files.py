"""Integration tests for file/thumbnail serving routes (T2 leftovers)."""

import base64

from flask.testing import FlaskClient

from src.db.models import Database, User
from src.enums import MessageRole

# 1x1 transparent PNG
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
_PNG_B64 = base64.b64encode(_PNG_BYTES).decode()


def _message_with_image(
    test_database: Database, user: User, thumbnail_status: str = "ready"
) -> str:
    """Create a conversation + user message carrying one PNG attachment."""
    conv = test_database.create_conversation(user.id, "Files test", "gemini-3.8-flash")
    message = test_database.add_message(
        conv.id,
        MessageRole.USER,
        "here is a picture",
        files=[
            {
                "name": "dot.png",
                "type": "image/png",
                "data": _PNG_B64,
                "thumbnail_status": thumbnail_status,
            }
        ],
    )
    return message.id


class TestGetMessageFile:
    def test_file_roundtrip(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        message_id = _message_with_image(test_database, test_user)

        response = client.get(f"/api/messages/{message_id}/files/0", headers=auth_headers)

        assert response.status_code == 200
        assert response.mimetype == "image/png"
        assert response.data == _PNG_BYTES

    def test_missing_message_is_404(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/api/messages/msg-nope/files/0", headers=auth_headers)
        assert response.status_code == 404

    def test_missing_file_index_is_404(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        message_id = _message_with_image(test_database, test_user)
        response = client.get(f"/api/messages/{message_id}/files/5", headers=auth_headers)
        assert response.status_code == 404

    def test_other_users_file_is_forbidden(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
    ) -> None:
        other = test_database.get_or_create_user(email="other@example.com", name="Other")
        message_id = _message_with_image(test_database, other)

        response = client.get(f"/api/messages/{message_id}/files/0", headers=auth_headers)
        assert response.status_code == 403

    def test_requires_auth(self, client: FlaskClient) -> None:
        assert client.get("/api/messages/msg-1/files/0").status_code == 401


class TestFullFileSources:
    """Which bytes a full-file request serves: the blob store, then legacy base64."""

    def _get(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        file: dict,
        blobs: dict[str, tuple[bytes, str]],
    ):
        from datetime import UTC, datetime
        from unittest.mock import MagicMock, patch

        message = MagicMock(id="m1", conversation_id="c1", files=[file])
        message.created_at = datetime.now(UTC)
        store = MagicMock()
        store.get.side_effect = blobs.get
        with (
            patch("src.api.routes.files.db") as mock_db,
            patch("src.api.routes.files.get_blob_store", return_value=store),
        ):
            mock_db.get_message_by_id.return_value = message
            return client.get("/api/messages/m1/files/0", headers=auth_headers)

    def test_blob_store_comes_first(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        file = {"type": "image/png", "data": base64.b64encode(b"legacy").decode()}

        response = self._get(client, auth_headers, file, {"m1/0": (b"blob", "image/webp")})

        assert (response.status_code, response.data, response.mimetype) == (
            200,
            b"blob",
            "image/webp",
        )
        assert response.headers["Cache-Control"] == "private, max-age=31536000"

    def test_legacy_data_is_the_fallback(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        file = {"type": "application/pdf", "data": base64.b64encode(b"%PDF-1.4").decode()}

        response = self._get(client, auth_headers, file, {})

        assert (response.status_code, response.data, response.mimetype) == (
            200,
            b"%PDF-1.4",
            "application/pdf",
        )
        assert response.headers["Cache-Control"] == "private, max-age=31536000"

    def test_no_file_data_anywhere_is_404(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        for file in ({"type": "image/png"}, {"type": "image/png", "data": "not base64!"}):
            assert self._get(client, auth_headers, file, {}).status_code == 404


class TestGetMessageThumbnail:
    def test_ready_image_returns_binary(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        """Ready status serves a thumbnail (or falls back to the full image)."""
        message_id = _message_with_image(test_database, test_user)

        response = client.get(f"/api/messages/{message_id}/files/0/thumbnail", headers=auth_headers)

        assert response.status_code == 200
        assert response.mimetype.startswith("image/")
        assert len(response.data) > 0

    def test_missing_message_is_404(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/api/messages/msg-nope/files/0/thumbnail", headers=auth_headers)
        assert response.status_code == 404

    def test_other_users_thumbnail_is_forbidden(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
    ) -> None:
        other = test_database.get_or_create_user(email="other@example.com", name="Other")
        message_id = _message_with_image(test_database, other)

        response = client.get(f"/api/messages/{message_id}/files/0/thumbnail", headers=auth_headers)
        assert response.status_code == 403

    def test_non_image_file_is_rejected(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Docs", "gemini-3.8-flash")
        message = test_database.add_message(
            conv.id,
            MessageRole.USER,
            "a document",
            files=[
                {
                    "name": "doc.pdf",
                    "type": "application/pdf",
                    "data": base64.b64encode(b"%PDF-1.4 fake").decode(),
                }
            ],
        )

        response = client.get(f"/api/messages/{message.id}/files/0/thumbnail", headers=auth_headers)
        assert response.status_code == 400


class TestThumbnailSources:
    """Which bytes a thumbnail request serves, in order of preference.

    The database and blob store are faked so legacy (unmigrated) metadata -
    base64 thumbnails and image data inside the file entry - can be served.
    """

    def _get(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        file: dict,
        blobs: dict[str, tuple[bytes, str]],
        age_seconds: float = 0,
    ):
        from datetime import UTC, datetime, timedelta
        from unittest.mock import MagicMock, patch

        message = MagicMock(id="m1", conversation_id="c1", files=[file])
        message.created_at = datetime.now(UTC) - timedelta(seconds=age_seconds)
        store = MagicMock()
        store.get.side_effect = blobs.get
        with (
            patch("src.api.routes.files.db") as mock_db,
            patch("src.api.routes.files.get_blob_store", return_value=store),
        ):
            mock_db.get_message_by_id.return_value = message
            return client.get("/api/messages/m1/files/0/thumbnail", headers=auth_headers)

    def test_stored_thumbnail_comes_first(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        file = {"type": "image/png", "has_thumbnail": True}
        blobs = {"m1/0.thumb": (b"thumb", "image/jpeg"), "m1/0": (b"full", "image/png")}

        response = self._get(client, auth_headers, file, blobs)

        assert (response.status_code, response.data, response.mimetype) == (
            200,
            b"thumb",
            "image/jpeg",
        )
        assert response.headers["Cache-Control"] == "private, max-age=31536000"

    def test_legacy_thumbnail_is_served_as_jpeg(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        file = {"type": "image/png", "thumbnail": base64.b64encode(b"old-thumb").decode()}

        response = self._get(client, auth_headers, file, {"m1/0": (b"full", "image/png")})

        assert (response.data, response.mimetype) == (b"old-thumb", "image/jpeg")

    def test_undecodable_legacy_thumbnail_falls_back_to_the_image(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        file = {"type": "image/png", "thumbnail": "not base64!"}

        response = self._get(client, auth_headers, file, {"m1/0": (b"full", "image/webp")})

        assert (response.data, response.mimetype) == (b"full", "image/webp")

    def test_legacy_image_data_is_the_last_resort(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        file = {"type": "image/gif", "data": base64.b64encode(b"gif-bytes").decode()}

        response = self._get(client, auth_headers, file, {})

        assert (response.data, response.mimetype) == (b"gif-bytes", "image/gif")

    def test_no_image_data_anywhere_is_404(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        for file in ({"type": "image/png"}, {"type": "image/png", "data": "not base64!"}):
            assert self._get(client, auth_headers, file, {}).status_code == 404

    def test_stale_pending_thumbnail_without_a_stored_image_falls_back(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        file = {
            "type": "image/png",
            "thumbnail_status": "pending",
            "data": base64.b64encode(b"inline").decode(),
        }

        response = self._get(client, auth_headers, file, {}, age_seconds=10**6)

        assert (response.status_code, response.data) == (200, b"inline")

    def test_failed_stale_regeneration_serves_the_full_image(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        from unittest.mock import patch

        file = {"type": "image/png", "thumbnail_status": "pending"}
        with patch(
            "src.api.routes.files.generate_and_save_thumbnail", return_value=None
        ) as regenerate:
            response = self._get(
                client, auth_headers, file, {"m1/0": (b"full", "image/png")}, age_seconds=10**6
            )

        regenerate.assert_called_once_with("m1", 0, base64.b64encode(b"full").decode(), "image/png")
        assert (response.status_code, response.data) == (200, b"full")


def _backdate_message(test_database: Database, message_id: str, days_old: int) -> None:
    from datetime import UTC, datetime, timedelta

    backdated = (datetime.now(UTC) - timedelta(days=days_old)).isoformat()
    with test_database._pool.get_connection() as conn:
        conn.execute("UPDATE messages SET created_at = ? WHERE id = ?", (backdated, message_id))
        conn.commit()


def _message_with_video(test_database: Database, user: User, days_old: int = 0) -> str:
    """Create a conversation + user message carrying one mp4 attachment."""
    from pathlib import Path

    mp4_b64 = base64.b64encode(
        (Path(__file__).parent.parent / "fixtures" / "tiny.mp4").read_bytes()
    ).decode()
    conv = test_database.create_conversation(user.id, "Video test", "gemini-3.8-flash")
    message = test_database.add_message(
        conv.id,
        MessageRole.USER,
        "here is a video",
        files=[{"name": "clip.mp4", "type": "video/mp4", "data": mp4_b64}],
    )
    if days_old:
        _backdate_message(test_database, message.id, days_old)
    return message.id


class TestExpiredMediaGone:
    def test_expired_video_returns_410(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        msg_id = _message_with_video(test_database, test_user, days_old=8)
        resp = client.get(f"/api/messages/{msg_id}/files/0", headers=auth_headers)
        assert resp.status_code == 410

    def test_fresh_video_returns_200(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        msg_id = _message_with_video(test_database, test_user)
        resp = client.get(f"/api/messages/{msg_id}/files/0", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.mimetype == "video/mp4"

    def test_expired_image_returns_410(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        msg_id = _message_with_image(test_database, test_user)
        _backdate_message(test_database, msg_id, days_old=31)
        resp = client.get(f"/api/messages/{msg_id}/files/0", headers=auth_headers)
        assert resp.status_code == 410

    def test_old_pdf_returns_410(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Docs", "gemini-3.8-flash")
        message = test_database.add_message(
            conv.id,
            MessageRole.USER,
            "a document",
            files=[
                {
                    "name": "doc.pdf",
                    "type": "application/pdf",
                    "data": base64.b64encode(b"%PDF-1.4 fake").decode(),
                }
            ],
        )
        _backdate_message(test_database, message.id, days_old=999)
        resp = client.get(f"/api/messages/{message.id}/files/0", headers=auth_headers)
        assert resp.status_code == 410

    def test_fresh_pdf_still_served(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Docs2", "gemini-3.8-flash")
        message = test_database.add_message(
            conv.id,
            MessageRole.USER,
            "a document",
            files=[
                {
                    "name": "doc.pdf",
                    "type": "application/pdf",
                    "data": base64.b64encode(b"%PDF-1.4 fake").decode(),
                }
            ],
        )
        resp = client.get(f"/api/messages/{message.id}/files/0", headers=auth_headers)
        assert resp.status_code == 200
