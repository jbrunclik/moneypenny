"""Integration tests for the saved-documents routes (list, download, delete, restore)."""

from unittest.mock import patch

import pytest
from flask.testing import FlaskClient

from src.config import Config
from src.db.models import Database, User


def _add(db: Database, user_id: str, data: bytes = b"%PDF-1.4 x", title: str = "Lease") -> str:
    return db.add_document(
        user_id,
        title=title,
        summary="Flat lease",
        use_for="Rent questions",
        filename="lease.pdf",
        mime_type="application/pdf",
        data=data,
        valid_until=None,
        source_conversation_id=None,
        source_message_id=None,
    ).id


class TestDocumentRoutes:
    def test_list_separates_deleted(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        live = _add(test_database, test_user.id, title="Live")
        gone = _add(test_database, test_user.id, title="Gone")
        test_database.delete_document(gone, test_user.id)

        response = client.get("/api/documents", headers=auth_headers)

        assert response.status_code == 200
        body = response.get_json()
        assert [d["id"] for d in body["documents"]] == [live]
        assert [d["id"] for d in body["deleted"]] == [gone]
        assert body["documents"][0]["title"] == "Live"
        assert body["documents"][0]["use_for"] == "Rent questions"
        assert body["limit"] == Config.DOCUMENTS_MAX_ENTRIES
        assert body["bytes_used"] == 10
        assert body["bytes_limit"] == Config.DOCUMENTS_MAX_TOTAL_BYTES

    def test_download_sets_attachment_header(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        doc_id = _add(test_database, test_user.id, data=b"%PDF-bytes")

        response = client.get(f"/api/documents/{doc_id}/file", headers=auth_headers)

        assert response.status_code == 200
        assert response.data == b"%PDF-bytes"
        assert response.mimetype == "application/pdf"
        assert "attachment" in response.headers["Content-Disposition"]
        assert "lease.pdf" in response.headers["Content-Disposition"]

    def test_download_czech_name_header_is_latin1(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        """Gunicorn writes headers as latin-1: a Czech file name must ride in
        filename*= (UTF-8, percent-encoded) with an ASCII fallback."""
        doc_id = test_database.add_document(
            test_user.id,
            title="Lease",
            summary="s",
            use_for="u",
            filename="Nájemní smlouva - Černý.pdf",
            mime_type="application/pdf",
            data=b"%PDF",
            valid_until=None,
            source_conversation_id=None,
            source_message_id=None,
        ).id

        response = client.get(f"/api/documents/{doc_id}/file", headers=auth_headers)

        header = response.headers["Content-Disposition"]
        header.encode("latin-1")
        assert 'filename="Najemni smlouva - Cerny.pdf"' in header
        assert "filename*=UTF-8''N%C3%A1jemn%C3%AD%20smlouva%20-%20%C4%8Cern%C3%BD.pdf" in header

    def test_delete_then_restore(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        doc_id = _add(test_database, test_user.id)

        assert client.delete(f"/api/documents/{doc_id}", headers=auth_headers).status_code == 200
        assert test_database.list_documents(test_user.id) == []
        restore = client.post(f"/api/documents/{doc_id}/restore", headers=auth_headers)
        assert restore.status_code == 200
        assert [d.id for d in test_database.list_documents(test_user.id)] == [doc_id]

    def test_restore_over_cap_conflicts(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        gone = _add(test_database, test_user.id)
        test_database.delete_document(gone, test_user.id)
        _add(test_database, test_user.id)

        with patch.object(Config, "DOCUMENTS_MAX_ENTRIES", 1):
            response = client.post(f"/api/documents/{gone}/restore", headers=auth_headers)

        assert response.status_code == 409
        assert test_database.list_documents(test_user.id)[0].id != gone

    def test_restore_over_byte_cap_conflicts(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_user: User,
        test_database: Database,
    ) -> None:
        gone = _add(test_database, test_user.id, data=b"x" * 60)
        test_database.delete_document(gone, test_user.id)
        _add(test_database, test_user.id, data=b"y" * 60)

        with patch.object(Config, "DOCUMENTS_MAX_TOTAL_BYTES", 100):
            response = client.post(f"/api/documents/{gone}/restore", headers=auth_headers)

        assert response.status_code == 409

    @pytest.mark.parametrize(
        ("method", "suffix"),
        [("get", "/file"), ("delete", ""), ("post", "/restore")],
    )
    def test_other_users_document_is_not_found(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        method: str,
        suffix: str,
    ) -> None:
        other = test_database.get_or_create_user("other@example.com", "Other")
        doc_id = _add(test_database, other.id)
        if method == "post":
            test_database.delete_document(doc_id, other.id)

        response = getattr(client, method)(f"/api/documents/{doc_id}{suffix}", headers=auth_headers)

        assert response.status_code == 404

    def test_requires_auth(self, client: FlaskClient) -> None:
        assert client.get("/api/documents").status_code == 401
