"""Saved-document routes (document memory): list, download, delete, restore.

The agent saves documents from chat (manage_documents); the Data page shows
them. Deletes are soft: a document stays restorable for
DOCUMENTS_SOFT_DELETE_RETENTION_DAYS before the nightly purge.
"""

import unicodedata
from urllib.parse import quote

from apiflask import APIBlueprint
from flask import Response

from src.api.errors import raise_conflict_error, raise_not_found_error
from src.api.schemas.common import StatusResponse
from src.api.schemas.documents import DocumentsResponse
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.blob_store import get_blob_store
from src.db.models import Document, User, db
from src.db.models.helpers import make_document_blob_key
from src.utils.clock import local_today, to_api
from src.utils.logging import get_logger

logger = get_logger(__name__)

api = APIBlueprint("documents", __name__, url_prefix="/api", tag="Documents")


def _serialize(doc: Document) -> dict[str, object]:
    return {
        "id": doc.id,
        "title": doc.title,
        "summary": doc.summary,
        "use_for": doc.use_for,
        "filename": doc.filename,
        "mime_type": doc.mime_type,
        "size_bytes": doc.size_bytes,
        "created_at": to_api(doc.created_at),
        "valid_until": doc.valid_until.isoformat() if doc.valid_until else None,
        "deleted_at": to_api(doc.deleted_at) if doc.deleted_at else None,
        "last_opened_at": to_api(doc.last_opened_at) if doc.last_opened_at else None,
        "source_conversation_id": doc.source_conversation_id,
    }


@api.route("/documents", methods=["GET"])
@api.output(DocumentsResponse)
@require_auth
def list_documents(user: User) -> dict[str, object]:
    """The user's saved documents and the recently deleted ones."""
    _count, bytes_used = db.document_usage(user.id, local_today())
    return {
        "documents": [_serialize(d) for d in db.list_documents(user.id)],
        "deleted": [_serialize(d) for d in db.list_deleted_documents(user.id)],
        "limit": Config.DOCUMENTS_MAX_ENTRIES,
        "bytes_used": bytes_used,
        "bytes_limit": Config.DOCUMENTS_MAX_TOTAL_BYTES,
    }


@api.route("/documents/<document_id>/file", methods=["GET"])
@api.doc(
    summary="Download a saved document",
    responses={200: "The file, as an attachment", 404: "Not found"},
)
@require_auth
def download_document(user: User, document_id: str) -> Response:
    """The saved document's file, as an attachment (live or recently deleted)."""
    doc = db.get_document(document_id, user.id)
    blob = get_blob_store().get(make_document_blob_key(document_id)) if doc else None
    if doc is None or blob is None:
        raise_not_found_error("Document")
    data, mime_type = blob
    response = Response(data, mimetype=mime_type or doc.mime_type)
    response.headers["Content-Disposition"] = _attachment_header(doc.filename)
    return response


def _attachment_header(filename: str) -> str:
    """An attachment header for any file name: the server writes headers as
    latin-1, so a Czech name rides in filename*= (UTF-8), with an ASCII
    fallback for clients that only read filename=."""
    cleaned = "".join(c for c in filename if c not in '"\r\n\\/') or "document"
    ascii_name = unicodedata.normalize("NFKD", cleaned).encode("ascii", "ignore").decode()
    return (
        f'attachment; filename="{ascii_name or "document"}"; '
        f"filename*=UTF-8''{quote(cleaned, safe='')}"
    )


@api.route("/documents/<document_id>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[404])
@require_auth
def delete_document(user: User, document_id: str) -> tuple[dict[str, str], int]:
    """Delete a saved document (soft delete, restorable for a while)."""
    if not db.delete_document(document_id, user.id):
        raise_not_found_error("Document")
    logger.info("Document deleted", extra={"user_id": user.id, "document_id": document_id})
    return {"status": "deleted"}, 200


@api.route("/documents/<document_id>/restore", methods=["POST"])
@api.output(StatusResponse)
@api.doc(responses=[404, 409])
@require_auth
def restore_document(user: User, document_id: str) -> tuple[dict[str, str], int]:
    """Restore a deleted document, unless the library is full."""
    doc = db.get_document(document_id, user.id)
    if doc is None or doc.deleted_at is None:
        raise_not_found_error("Document")
    count, used = db.document_usage(user.id, local_today())
    if count >= Config.DOCUMENTS_MAX_ENTRIES:
        raise_conflict_error(
            f"You already have {count} saved documents, the most there can be. Delete one first."
        )
    if used + doc.size_bytes > Config.DOCUMENTS_MAX_TOTAL_BYTES:
        raise_conflict_error("Your saved documents' storage is full. Delete one first.")
    db.restore_document(document_id, user.id, local_today())
    logger.info("Document restored", extra={"user_id": user.id, "document_id": document_id})
    return {"status": "restored"}, 200
