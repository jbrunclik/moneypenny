"""Sandbox scripts that call tools (spec: docs/superpowers/specs/2026-11-17-sandbox-tool-calls-design.md).

The agent makes one tool call per round, and every round re-sends the whole
context. An ``execute_code`` script can instead loop over lookups
(``from moneypenny import tools``) and print only what the answer needs.

The script and the host talk over the script's own stdout and stdin: the
stub writes one request line marked with a per-run random token, the host
answers with one JSON line on stdin. A printed line without the token is
plain output, so a fetched page that gets printed cannot pose as a request.
The container keeps its network off; only read-only tools are reachable.
"""

import contextvars
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Protocol

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from src.agent.source_pages import SourcePage, turn_pages
from src.agent.tools.turn_usage import record_tool_call
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Read-only tools a script may call: their results are data, not actions.
# Writes stay one visible tool call each, so cards and approvals keep working.
ALLOWED_TOOLS = ("web_search", "fetch_url", "research", "search_memory")
WEB_TOOLS = frozenset({"web_search", "fetch_url", "research"})

_MARKER = "<<rpc:{token}>> "
_ENV = "MP_RPC_TOKEN"

# Runs in the sandbox ahead of the user's code (wrap_user_code). Reads the
# token from the environment and removes it, so the script's own os.environ
# no longer shows it; the stub keeps it in a closure.
STUB = '''
def _moneypenny_tools():
    import json, os, sys, types
    token = os.environ.pop("MP_RPC_TOKEN", "")

    class ToolError(Exception):
        """A tool call failed; the message says why."""

    ToolError.__module__, ToolError.__qualname__ = "moneypenny.tools", "ToolError"

    def call(tool, **args):
        if not token:
            raise ToolError("tool calls are not available in this run")
        sys.stdout.flush()
        out = sys.__stdout__
        out.write("<<rpc:" + token + ">> " + json.dumps({"tool": tool, "args": args}) + "\\n")
        out.flush()
        line = sys.__stdin__.readline()
        if not line:
            raise ToolError("no reply from the host")
        reply = json.loads(line)
        if "error" in reply:
            raise ToolError(reply["error"])
        return reply["result"]

    tools = types.ModuleType("moneypenny.tools")
    tools.ToolError = ToolError
    tools.web_search = lambda query, num_results=None: call(
        "web_search", **({"query": query} | ({"num_results": num_results} if num_results else {}))
    )
    tools.fetch_url = lambda url: call("fetch_url", url=url)
    tools.research = lambda queries: call(
        "research", queries=[queries] if isinstance(queries, str) else list(queries)
    )
    tools.search_memory = lambda query: call("search_memory", query=query)
    package = types.ModuleType("moneypenny")
    package.tools = tools
    sys.modules["moneypenny"] = package
    sys.modules["moneypenny.tools"] = tools


_moneypenny_tools()
del _moneypenny_tools
'''


class _Tool(Protocol):
    def invoke(self, _input: dict[str, object], /) -> object: ...


def _default_tools() -> dict[str, _Tool]:
    from src.agent.tools import fetch_url, research, web_search  # noqa: PLC0415 - cycle: tools -> code_execution -> here
    from src.agent.tools.memory import search_memory  # noqa: PLC0415 - same cycle

    return {
        "web_search": web_search,
        "fetch_url": fetch_url,
        "research": research,
        "search_memory": search_memory,
    }


@dataclass
class ToolBridge:
    """Answers one run's tool calls, within its budget and allow-list."""

    context: contextvars.Context = field(default_factory=contextvars.copy_context)
    tools: dict[str, _Tool] = field(default_factory=_default_tools)
    token: str = field(default_factory=lambda: secrets.token_hex(16))
    calls: int = 0
    failed: int = 0
    web_calls: int = 0
    ms: int = 0
    _messages: list[BaseMessage] = field(default_factory=list)

    @property
    def marker(self) -> str:
        return _MARKER.format(token=self.token)

    @property
    def environment(self) -> dict[str, str]:
        return {_ENV: self.token}

    def request_in(self, line: str) -> str | None:
        """The JSON request a stdout line carries, or None for plain output."""
        return line[len(self.marker) :] if line.startswith(self.marker) else None

    def answer(self, request: str) -> str:
        """One JSON reply line (without the newline) for one request."""
        started = time.monotonic()
        name = ""
        try:
            data = json.loads(request)
            name = str(data.get("tool", ""))
            args = data.get("args") or {}
            reply = (
                self._call(name, args)
                if isinstance(args, dict)
                else _error("args must be an object")
            )
        except ValueError, AttributeError:
            reply = _error("the request was not valid JSON")
        elapsed = round((time.monotonic() - started) * 1000)
        self.ms += elapsed
        ok = "error" not in reply
        self.failed += 0 if ok else 1
        logger.info("Sandbox tool call", extra={"tool": name, "ms": elapsed, "ok": ok})
        return json.dumps(reply, ensure_ascii=False)

    def _call(self, name: str, args: dict[str, object]) -> dict[str, object]:
        if name not in self.tools:
            return _error(f"unknown tool '{name}'; available: {', '.join(ALLOWED_TOOLS)}")
        if self.calls >= Config.CODE_SANDBOX_TOOL_CALLS_MAX:
            return _error(f"budget spent: at most {Config.CODE_SANDBOX_TOOL_CALLS_MAX} calls a run")
        self.calls += 1
        self.web_calls += name in WEB_TOOLS
        call_id = f"sandbox-{self.calls}"
        try:
            # The tools read the turn's request and conversation context
            content = self.context.run(self._invoke, name, args)
        except Exception as e:  # noqa: BLE001 - a failed tool is the script's error, not the run's
            return _error(f"{name} failed: {e}")
        self._messages += [
            AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}]),
            ToolMessage(content=content, tool_call_id=call_id, name=name),
        ]
        try:
            result: object = json.loads(content)
        except ValueError:
            return {"result": content}
        if isinstance(result, dict) and result.get("error"):
            # The tools report failure as an {"error"} envelope: a ToolError
            return _error(f"{name}: {result['error']}")
        return {"result": result}

    def _invoke(self, name: str, args: dict[str, object]) -> str:
        record_tool_call(name)
        return str(self.tools[name].invoke(args))

    def pages(self) -> list[SourcePage]:
        """The pages the run's calls read (or searched), as a turn's sources."""
        return turn_pages(self._messages)


def _error(message: str) -> dict[str, object]:
    return {"error": message}
