"""manage_documents and open_document in a project chat: the project's documents."""

from __future__ import annotations

import base64
from collections.abc import Generator
from typing import TYPE_CHECKING, Any

import pytest

from src.agent.tools.context import set_conversation_context
from src.agent.tools.documents import manage_documents, open_document

if TYPE_CHECKING:
    from flask import Flask

    from src.db.blob_store import BlobStore
    from src.db.models import Database, Project, User

PDF = b"%PDF-1.4 wallbox quote"


@pytest.fixture
def project(test_database: Database, test_user: User) -> Project:
    return test_database.create_project(test_user.id, "Home")


def _chat_with_file(db: Database, user: User, project_id: str | None) -> tuple[str, str]:
    conv = db.create_conversation(user.id, "Wallbox", project_id=project_id)
    msg = db.add_message(
        conv.id,
        "user",
        "the quote",
        files=[
            {"name": "quote.pdf", "type": "application/pdf", "data": base64.b64encode(PDF).decode()}
        ],
    )
    set_conversation_context(conv.id, user.id)
    return conv.id, f"{msg.id}:0"


@pytest.fixture
def project_file(
    app: Flask,
    test_database: Database,
    test_blob_store: BlobStore,
    test_user: User,
    project: Project,
) -> Generator[str]:
    _conv_id, file_id = _chat_with_file(test_database, test_user, project.id)
    yield file_id
    set_conversation_context(None, None)


def _save(file_id: str, **kw: Any) -> str:
    op: dict[str, Any] = {
        "action": "save",
        "file_id": file_id,
        "title": "Wallbox quote",
        "summary": "11 kW install, 32 A breaker, 38,000 CZK",
        "use_for": "Wallbox questions",
    }
    op.update(kw)
    return str(manage_documents.invoke({"operations": [op]}))


def test_save_project_scope(
    test_database: Database, test_user: User, project: Project, project_file: str
) -> None:
    assert "SAVED" in _save(project_file, scope="project")
    assert [d.title for d in test_database.list_project_documents(project.id)] == ["Wallbox quote"]
    assert test_database.list_documents(test_user.id) == []


def test_default_save_is_personal(
    test_database: Database, test_user: User, project: Project, project_file: str
) -> None:
    _save(project_file)
    assert [d.title for d in test_database.list_documents(test_user.id)] == ["Wallbox quote"]


def test_project_scope_outside_project_rejected(
    app: Flask, test_database: Database, test_blob_store: BlobStore, test_user: User
) -> None:
    _conv, file_id = _chat_with_file(test_database, test_user, None)
    try:
        result = _save(file_id, scope="project")
    finally:
        set_conversation_context(None, None)
    assert "REJECTED (save)" in result
    assert "not in a project" in result


def test_open_project_document_from_its_chat(
    test_database: Database, project: Project, project_file: str
) -> None:
    _save(project_file, scope="project")
    [doc] = test_database.list_project_documents(project.id)
    result = open_document.invoke({"id": doc.id[:8]})
    assert isinstance(result, list)


def test_open_other_project_document_not_found(
    test_database: Database, test_user: User, project: Project, project_file: str
) -> None:
    other = test_database.create_project(test_user.id, "Bikes")
    doc = test_database.add_document(
        test_user.id,
        title="Bike invoice",
        summary="s",
        use_for="u",
        filename="i.pdf",
        mime_type="application/pdf",
        data=b"x",
        valid_until=None,
        source_conversation_id=None,
        source_message_id=None,
        project_id=other.id,
    )
    result = open_document.invoke({"id": doc.id[:8]})
    assert isinstance(result, str)
    assert "No saved document" in result


def test_member_replaces_members_document_bytes_to_replacer(
    test_database: Database, test_user: User, project: Project, project_file: str
) -> None:
    jana = test_database.get_or_create_user(email="jana@example.com", name="Jana")
    test_database.add_project_member(project.id, test_user.id, jana.id)
    old = test_database.add_document(
        jana.id,
        title="Old quote",
        summary="s",
        use_for="u",
        filename="old.pdf",
        mime_type="application/pdf",
        data=b"x" * 10,
        valid_until=None,
        source_conversation_id=None,
        source_message_id=None,
        project_id=project.id,
    )

    assert "SAVED" in _save(project_file, scope="project", replaces=old.id[:8])

    [doc] = test_database.list_project_documents(project.id)
    assert doc.user_id == test_user.id
    assert doc.title == "Wallbox quote"
