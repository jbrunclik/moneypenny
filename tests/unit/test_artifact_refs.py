"""Artifact refs from a turn's tool messages (src/agent/artifact_refs.py)."""

import json

from langchain_core.messages import AIMessage, ToolMessage

from src.agent.artifact_refs import artifact_ref_from_tool_content, extract_artifact_refs


def _result(name: str, art_id: str, version: int, ok: bool = True) -> ToolMessage:
    body = {"success": ok, "artifact": {"id": art_id, "version": version, "title": "T"}}
    return ToolMessage(name=name, content=json.dumps(body), tool_call_id=f"{art_id}{version}")


def test_refs_in_order_with_the_last_version_of_each() -> None:
    msgs = [
        AIMessage(content=""),
        _result("create_artifact", "a", 1),
        _result("create_artifact", "b", 1),
        _result("update_artifact", "a", 2),
    ]
    refs = extract_artifact_refs(msgs)
    assert [(r["id"], r["version"]) for r in refs] == [("a", 2), ("b", 1)]
    assert refs[0] == {"id": "a", "version": 2, "title": "T"}


def test_reads_failures_and_other_tools_are_ignored() -> None:
    msgs = [
        _result("read_artifact", "a", 1),
        _result("create_artifact", "b", 1, ok=False),
        ToolMessage(name="web_search", content="not json", tool_call_id="x"),
    ]
    assert extract_artifact_refs(msgs) == []


def test_malformed_content_is_no_ref() -> None:
    assert artifact_ref_from_tool_content("create_artifact", "{bad") is None
    assert artifact_ref_from_tool_content("create_artifact", '{"success": true}') is None
    assert artifact_ref_from_tool_content(None, '{"success": true}') is None
