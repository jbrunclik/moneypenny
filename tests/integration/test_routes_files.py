"""Integration tests for file/thumbnail serving routes (T2 leftovers)."""

import base64

from flask.testing import FlaskClient

from src.api.schemas import MessageRole
from src.db.models import Database, User

# 1x1 transparent PNG
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
_PNG_B64 = base64.b64encode(_PNG_BYTES).decode()


def _message_with_image(
    test_database: Database, user: User, thumbnail_status: str = "ready"
) -> str:
    """Create a conversation + user message carrying one PNG attachment."""
    conv = test_database.create_conversation(user.id, "Files test", "gemini-3.5-flash")
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
        conv = test_database.create_conversation(test_user.id, "Docs", "gemini-3.5-flash")
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


def _backdate_message(test_database: Database, message_id: str, days_old: int) -> None:
    from datetime import datetime, timedelta

    backdated = (datetime.now() - timedelta(days=days_old)).isoformat()
    with test_database._pool.get_connection() as conn:
        conn.execute("UPDATE messages SET created_at = ? WHERE id = ?", (backdated, message_id))
        conn.commit()


def _message_with_video(test_database: Database, user: User, days_old: int = 0) -> str:
    """Create a conversation + user message carrying one mp4 attachment."""
    from pathlib import Path

    mp4_b64 = base64.b64encode(
        (Path(__file__).parent.parent / "fixtures" / "tiny.mp4").read_bytes()
    ).decode()
    conv = test_database.create_conversation(user.id, "Video test", "gemini-3.5-flash")
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
        conv = test_database.create_conversation(test_user.id, "Docs", "gemini-3.5-flash")
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
        conv = test_database.create_conversation(test_user.id, "Docs2", "gemini-3.5-flash")
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
