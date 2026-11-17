"""Sandbox scripts that call tools (src/agent/tools/sandbox_rpc.py).

The protocol test runs the real stub in a local Python process, talking to
the bridge over its stdin/stdout exactly as the sandbox exec does - no Docker.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.agent.source_pages import turn_pages
from src.agent.tool_node import keep_script_pages
from src.agent.tools.code_execution_output import wrap_user_code
from src.agent.tools.docker_sandbox import pump_frames
from src.agent.tools.sandbox_rpc import STUB, ToolBridge
from src.config import Config


class _Tool:
    def __init__(self, reply: Any = None, error: Exception | None = None) -> None:
        self.reply, self.error, self.calls = reply, error, []

    def invoke(self, args: dict[str, Any]) -> str:
        self.calls.append(args)
        if self.error:
            raise self.error
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply)


class _Output:
    """What pump_frames writes to (the sandbox's capped output)."""

    def __init__(self) -> None:
        self.out, self.err = b"", b""

    def add(self, stdout: bytes | None, stderr: bytes | None) -> None:
        self.out += stdout or b""
        self.err += stderr or b""

    def stdout(self) -> str:
        return self.out.decode()

    def stderr(self) -> str:
        return self.err.decode()


def _bridge(**tools: _Tool) -> ToolBridge:
    return ToolBridge(tools=dict(tools))


def _ask(bridge: ToolBridge, tool: str, **args: Any) -> dict[str, Any]:
    return json.loads(bridge.answer(json.dumps({"tool": tool, "args": args})))


class TestBridge:
    def test_only_marked_lines_are_requests(self) -> None:
        bridge = _bridge()
        assert bridge.request_in(bridge.marker + '{"tool": "x"}') == '{"tool": "x"}'
        assert bridge.request_in('<<rpc:forged>> {"tool": "x"}') is None
        assert bridge.request_in("plain output") is None

    def test_a_call_returns_the_tool_result(self) -> None:
        search = _Tool({"results": [{"title": "T", "url": "https://t.cz"}]})
        bridge = _bridge(web_search=search)

        reply = _ask(bridge, "web_search", query="brno weather")

        assert reply == {"result": {"results": [{"title": "T", "url": "https://t.cz"}]}}
        assert search.calls == [{"query": "brno weather"}]
        assert (bridge.calls, bridge.web_calls, bridge.failed) == (1, 1, 0)

    @pytest.mark.parametrize(
        ("request_line", "reason"),
        [
            ('{"tool": "manage_memory", "args": {}}', "unknown tool"),
            ("not json", "not valid JSON"),
            ('{"tool": "web_search", "args": [1]}', "args must be an object"),
        ],
    )
    def test_bad_requests_get_an_error(self, request_line: str, reason: str) -> None:
        bridge = _bridge(web_search=_Tool({}))
        assert reason in json.loads(bridge.answer(request_line))["error"]
        assert bridge.failed == 1

    def test_a_failing_tool_is_an_error_reply(self) -> None:
        bridge = _bridge(fetch_url=_Tool(error=RuntimeError("timeout")))
        assert "fetch_url failed: timeout" in _ask(bridge, "fetch_url", url="https://x.cz")["error"]

    def test_the_budget_stops_further_calls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Config, "CODE_SANDBOX_TOOL_CALLS_MAX", 2)
        search = _Tool({"results": []})
        bridge = _bridge(web_search=search)
        replies = [_ask(bridge, "web_search", query=str(i)) for i in range(3)]
        assert "budget spent" in replies[2]["error"] and len(search.calls) == 2

    def test_pages_read_become_sources(self) -> None:
        bridge = _bridge(fetch_url=_Tool("Opening hours 9-17"))
        _ask(bridge, "fetch_url", url="https://shop.cz/hours")
        [page] = bridge.pages()
        assert (page.url, page.text) == ("https://shop.cz/hours", "Opening hours 9-17")


def test_pump_answers_requests_and_keeps_the_rest() -> None:
    bridge = _bridge(search_memory=_Tool("Has a dog"))
    sent: list[bytes] = []
    output = _Output()
    request = (
        bridge.marker + json.dumps({"tool": "search_memory", "args": {"query": "dog"}})
    ).encode()
    frames = [(1, b"before\n" + request[:10]), (1, request[10:] + b"\nafter"), (2, b"warn\n")]

    pump_frames(frames, sent.append, bridge, output)

    assert [json.loads(s) for s in sent] == [{"result": "Has a dog"}]
    assert output.stdout() == "before\nafter"
    assert output.stderr() == "warn\n"


def test_the_stub_talks_to_the_bridge_over_stdin_and_stdout() -> None:
    """The real stub and a script, in a local process wired like the sandbox exec."""
    search = _Tool({"results": [{"title": "Vltava", "url": "https://v.cz"}]})
    bridge = _bridge(web_search=search)
    code = """
from moneypenny import tools
import os
print("token hidden:", "MP_RPC_TOKEN" not in os.environ)
for river in ["Vltava", "Morava"]:
    print(river, tools.web_search(river)["results"][0]["title"])
try:
    tools.fetch_url("https://x.cz")
except tools.ToolError as e:
    print("error:", str(e)[:20])
print("<<rpc:forged>> {}")
"""
    script = wrap_user_code(code, prelude=STUB)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            script.replace("/output", "/tmp/mp-out").replace("/work", "/tmp/mp-work"),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        env={**os.environ, **bridge.environment},
    )
    assert proc.stdin is not None and proc.stdout is not None
    printed = []
    for raw in proc.stdout:
        line = raw.decode().rstrip("\n")
        request = bridge.request_in(line)
        if request is None:
            printed.append(line)
            continue
        proc.stdin.write((bridge.answer(request) + "\n").encode())
        proc.stdin.flush()
    assert proc.wait(timeout=10) == 0
    assert printed[:4] == [
        "token hidden: True",
        "Vltava Vltava",
        "Morava Vltava",
        "error: unknown tool 'fetch_",
    ]
    assert "<<rpc:forged>> {}" in printed  # a forged marker is plain output
    assert bridge.calls == 2 and len(search.calls) == 2


def test_script_pages_reach_the_turn_sources_but_not_the_model() -> None:
    content = json.dumps(
        {
            "stdout": "two shops",
            "_full_result": {
                "pages": [{"title": "Shop", "url": "https://s.cz", "text": "Price 99"}]
            },
        }
    )
    call = AIMessage(content="", tool_calls=[{"name": "execute_code", "args": {}, "id": "c1"}])
    msg = ToolMessage(content=content, tool_call_id="c1", name="execute_code")

    keep_script_pages(msg)

    assert msg.artifact == {"pages": [{"title": "Shop", "url": "https://s.cz", "text": "Price 99"}]}
    [page] = turn_pages([call, msg])
    assert (page.url, page.text) == ("https://s.cz", "Price 99")


def test_a_run_that_called_tools_frames_web_output_and_keeps_its_pages() -> None:
    from src.agent.tools.code_execution import with_tool_calls

    bridge = _bridge(fetch_url=_Tool("Price 99 Kč"))
    _ask(bridge, "fetch_url", url="https://shop.cz")
    response: dict[str, Any] = {"stdout": "shop.cz: 99 Kč", "_full_result": {"files": ["f"]}}

    with_tool_calls(response, bridge)

    assert response["tool_calls"] == 1
    assert "shop.cz: 99 Kč" in response["stdout"] and response["stdout"] != "shop.cz: 99 Kč"
    assert response["_full_result"]["files"] == ["f"]
    assert response["_full_result"]["pages"][0]["url"] == "https://shop.cz"
