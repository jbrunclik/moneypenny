"""Unit tests for per-turn tool output digests (src/agent/tool_outputs.py)."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agent.tool_outputs import (
    TOOL_OUTPUTS_MAX_CHARS,
    build_tool_outputs,
    format_tool_outputs,
)


def _turn(*calls: tuple[str, dict, str]) -> list:
    """History-shaped message list: one AIMessage per call + its ToolMessage."""
    messages: list = [HumanMessage(content="question")]
    for i, (name, args, result) in enumerate(calls):
        messages.append(
            AIMessage(content="", tool_calls=[{"id": f"c{i}", "name": name, "args": args}])
        )
        messages.append(ToolMessage(content=result, tool_call_id=f"c{i}", name=name))
    messages.append(AIMessage(content="final answer"))
    return messages


class TestBuildToolOutputs:
    def test_digest_per_call_with_args_and_result(self) -> None:
        outputs = build_tool_outputs(
            _turn(("garmin_connect", {"action": "hrv"}, json.dumps({"hrv": 62, "status": "ok"})))
        )
        assert outputs == [
            {
                "tool": "garmin_connect",
                "args": '{"action":"hrv"}',
                "result": '{"hrv":62,"status":"ok"}',
            }
        ]

    def test_skips_web_metadata_and_recall_tools(self) -> None:
        outputs = build_tool_outputs(
            _turn(
                ("web_search", {"query": "x"}, "{}"),
                ("set_conversation_title", {"title": "x"}, "Noted"),
                ("search_conversations", {"query": "x"}, "Found"),
                ("generate_image", {"prompt": "cat"}, "{}"),
                ("todoist", {"action": "list"}, '{"tasks": ["buy milk"]}'),
            )
        )
        assert outputs is not None
        assert [o["tool"] for o in outputs] == ["todoist"]

    def test_skips_load_skill(self) -> None:
        """Skill bodies are repo text: re-sending them in every later turn's
        MSG_CONTEXT would crowd out the digests that matter."""
        outputs = build_tool_outputs(
            _turn(
                ("load_skill", {"name": "weekly-planning"}, "Skill: weekly-planning\n..."),
                ("todoist", {"action": "list"}, '{"tasks": ["buy milk"]}'),
            )
        )
        assert outputs is not None
        assert [o["tool"] for o in outputs] == ["todoist"]

    def test_none_without_tool_calls(self) -> None:
        assert build_tool_outputs([HumanMessage(content="hi"), AIMessage(content="hello")]) is None
        assert build_tool_outputs(_turn(("web_search", {}, "{}"))) is None

    def test_strips_internal_keys(self) -> None:
        result = json.dumps(
            {"stdout": "42", "_full_result": {"files": ["x" * 999]}, "_efficiency": "nudge"}
        )
        outputs = build_tool_outputs(_turn(("execute_code", {"code": "print(42)"}, result)))
        assert outputs is not None
        assert outputs[0]["result"] == '{"stdout":"42"}'

    def test_long_results_are_truncated(self) -> None:
        outputs = build_tool_outputs(_turn(("kv_store", {"action": "get"}, "v" * 5000)))
        assert outputs is not None
        assert len(outputs[0]["result"]) <= 401
        assert outputs[0]["result"].endswith("…")

    def test_total_budget_is_bounded(self) -> None:
        calls = [("kv_store", {"key": f"k{i}"}, "v" * 400) for i in range(20)]
        outputs = build_tool_outputs(_turn(*calls))
        assert outputs is not None
        assert len(format_tool_outputs(outputs) or "") <= TOOL_OUTPUTS_MAX_CHARS + 40
        assert outputs[-1]["tool"] == "…"  # "+N more" marker

    def test_multimodal_result_is_described(self) -> None:
        messages = _turn(("kv_store", {}, "x"))
        messages[2] = ToolMessage(
            content=[{"type": "image_url"}], tool_call_id="c0", name="kv_store"
        )
        outputs = build_tool_outputs(messages)
        assert outputs is not None
        assert outputs[0]["result"] == "[non-text result]"


class TestFormatToolOutputs:
    def test_renders_compact_line(self) -> None:
        text = format_tool_outputs(
            [{"tool": "todoist", "args": '{"action":"list"}', "result": '{"tasks":1}'}]
        )
        assert text == 'todoist({"action":"list"}) -> {"tasks":1}'

    def test_never_contains_comment_terminator(self) -> None:
        """The digest is embedded in an HTML-comment MSG_CONTEXT marker."""
        text = format_tool_outputs([{"tool": "kv_store", "args": "{}", "result": "a --> b"}])
        assert text is not None
        assert "-->" not in text

    def test_none_for_empty(self) -> None:
        assert format_tool_outputs(None) is None
        assert format_tool_outputs([]) is None


class TestCallShapes:
    def test_parallel_calls_in_one_round(self) -> None:
        messages = [
            AIMessage(
                content="",
                tool_calls=[
                    {"id": "a", "name": "todoist", "args": {"action": "list_tasks"}},
                    {"id": "b", "name": "garmin_connect", "args": {"action": "hrv"}},
                ],
            ),
            ToolMessage(content='{"tasks":[]}', tool_call_id="a", name="todoist"),
            ToolMessage(content='{"hrv":62}', tool_call_id="b", name="garmin_connect"),
        ]
        outputs = build_tool_outputs(messages)
        assert outputs is not None
        assert [o["tool"] for o in outputs] == ["todoist", "garmin_connect"]
        assert outputs[1]["args"] == '{"action":"hrv"}'

    def test_tool_name_falls_back_to_the_call(self) -> None:
        """Hand-built ToolMessages (e.g. permission-blocked calls) carry no name."""
        messages = [
            AIMessage(content="", tool_calls=[{"id": "a", "name": "kv_store", "args": {}}]),
            ToolMessage(content="blocked", tool_call_id="a"),
        ]
        outputs = build_tool_outputs(messages)
        assert outputs is not None
        assert outputs[0]["tool"] == "kv_store"
