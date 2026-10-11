"""Artifact tools (src/agent/tools/artifacts.py)."""

import json
from collections.abc import Iterator
from typing import Any

import pytest

from src.agent.tools.artifacts import (
    EditError,
    apply_edits,
    create_artifact,
    read_artifact,
    update_artifact,
)
from src.agent.tools.context import set_conversation_context
from src.config import Config


@pytest.fixture
def ctx(test_database: Any, test_conversation: Any) -> Iterator[Any]:
    set_conversation_context(test_conversation.id, test_conversation.user_id)
    yield test_conversation
    set_conversation_context(None, None)


def _call(tool: Any, **args: Any) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(tool.invoke(args))
    return result


def test_create_returns_the_ref(ctx: Any) -> None:
    out = _call(create_artifact, title="Tips", html="<p>hi</p>")
    assert out["success"] is True
    assert out["artifact"]["version"] == 1 and out["artifact"]["title"] == "Tips"


def test_create_rejects_oversized_html(ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "ARTIFACT_MAX_BYTES", 10)
    out = _call(create_artifact, title="T", html="<p>far too long</p>")
    assert out["success"] is False and "limit" in out["error"]


def test_create_rejects_past_the_per_conversation_cap(
    ctx: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Config, "ARTIFACT_MAX_PER_CONVERSATION", 1)
    _call(create_artifact, title="A", html="a")
    assert _call(create_artifact, title="B", html="b")["success"] is False


def test_create_without_a_conversation_fails() -> None:
    set_conversation_context(None, None)
    assert _call(create_artifact, title="T", html="x")["success"] is False


def test_apply_edits_exactly_once() -> None:
    edited = apply_edits("<b>1</b><i>2</i>", [{"find": "1", "replace": "one"}])
    assert edited == "<b>one</b><i>2</i>"
    with pytest.raises(EditError, match="not found"):
        apply_edits("<b>1</b>", [{"find": "9", "replace": "x"}])
    with pytest.raises(EditError, match="2 times"):
        apply_edits("<b>1</b><b>1</b>", [{"find": "<b>1</b>", "replace": "x"}])


def test_update_with_edits_makes_version_two(ctx: Any) -> None:
    art = _call(create_artifact, title="T", html="<p>old</p>")["artifact"]
    out = _call(update_artifact, artifact_id=art["id"], edits=[{"find": "old", "replace": "new"}])
    assert out["artifact"]["version"] == 2
    assert _call(read_artifact, artifact_id=art["id"])["html"] == "<p>new</p>"


def test_update_with_html_replaces_the_document(ctx: Any) -> None:
    art = _call(create_artifact, title="T", html="<p>old</p>")["artifact"]
    out = _call(update_artifact, artifact_id=art["id"], html="<p>fresh</p>", title="T2")
    assert out["artifact"] == {"id": art["id"], "version": 2, "title": "T2"}
    assert _call(read_artifact, artifact_id=art["id"])["html"] == "<p>fresh</p>"


def test_failed_edit_shows_an_excerpt_and_writes_nothing(ctx: Any) -> None:
    art = _call(create_artifact, title="T", html="<p>alpha beta</p>")["artifact"]
    out = _call(update_artifact, artifact_id=art["id"], edits=[{"find": "gamma", "replace": "x"}])
    assert out["success"] is False and "alpha beta" in out["error"]
    assert _call(read_artifact, artifact_id=art["id"])["artifact"]["version"] == 1


def test_update_needs_edits_or_html(ctx: Any) -> None:
    art = _call(create_artifact, title="T", html="x")["artifact"]
    assert _call(update_artifact, artifact_id=art["id"])["success"] is False


def test_other_conversations_artifacts_are_invisible(
    ctx: Any, test_database: Any, test_user: Any
) -> None:
    other = test_database.create_conversation(user_id=test_user.id, title="other")
    foreign, _ = test_database.create_artifact(other.id, test_user.id, "F", "x")
    assert _call(read_artifact, artifact_id=foreign.id)["success"] is False
    out = _call(update_artifact, artifact_id=foreign.id, html="y")
    assert out["success"] is False


@pytest.mark.parametrize("tool", [create_artifact, update_artifact, read_artifact])
def test_every_param_has_a_concrete_type(tool: Any) -> None:
    # An Any-typed param breaks Gemini schema conversion for every chat
    for name, schema in tool.args.items():
        assert "type" in schema or "anyOf" in schema, f"{tool.name}.{name}: {schema}"


def test_converts_to_genai_declarations() -> None:
    try:
        from langchain_google_genai._function_utils import (
            convert_to_genai_function_declarations,
        )
    except Exception:
        return
    convert_to_genai_function_declarations([create_artifact, update_artifact, read_artifact])


_NAMES = {"create_artifact", "update_artifact", "read_artifact"}


def test_bound_in_chats_but_not_programs_or_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.agent.tools import get_tools_for_request

    monkeypatch.setattr(Config, "ARTIFACTS_ENABLED", True)
    names = lambda tools: {t.name for t in tools}  # noqa: E731
    assert _NAMES <= names(get_tools_for_request())
    assert _NAMES <= names(get_tools_for_request(anonymous_mode=True))
    assert not _NAMES & names(get_tools_for_request(is_sports=True))
    assert not _NAMES & names(get_tools_for_request(is_language=True))
    assert not _NAMES & names(get_tools_for_request(agent_tool_permissions=sorted(_NAMES)))
    monkeypatch.setattr(Config, "ARTIFACTS_ENABLED", False)
    assert not _NAMES & names(get_tools_for_request())
