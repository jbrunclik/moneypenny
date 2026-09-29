"""Unit tests for ChatAgent construction options and tool wiring (src/agent/agent.py)."""


class TestChatAgentOverrides:
    """enable_context_cache=False and system_prompt_override (delegate subagent)."""

    @staticmethod
    def _construct(monkeypatch, **kwargs):
        import src.agent.agent as agent_mod
        import src.agent.context_cache as cache_mod
        import src.agent.graph as graph_mod

        def fail_cache_lookup(*args, **kw):
            raise AssertionError("cache lookup must not run")

        monkeypatch.setattr(cache_mod, "get_cached_content_name", fail_cache_lookup)
        # ChatAgent now builds via the memoized get_compiled_graph; stub it so
        # construction skips real (slow) graph compilation.
        monkeypatch.setattr(graph_mod, "get_compiled_graph", lambda *a, **kw: object())
        return agent_mod.ChatAgent(model_name="gemini-test", **kwargs)

    def test_cache_opt_out_skips_cache_lookup(self, monkeypatch) -> None:
        agent = self._construct(monkeypatch, enable_context_cache=False)
        assert agent._cached_content_name is None

    def test_system_prompt_override_implies_no_cache(self, monkeypatch) -> None:
        agent = self._construct(monkeypatch, system_prompt_override="You are a test.")
        assert agent._cached_content_name is None

    def test_system_prompt_override_used_verbatim(self, monkeypatch) -> None:
        from langchain_core.messages import SystemMessage

        agent = self._construct(monkeypatch, system_prompt_override="You are a test.")
        messages = agent._build_messages("hi")
        assert isinstance(messages[0], SystemMessage)
        assert messages[0].content == "You are a test."


class TestInteractiveAgentToolWiring:
    """Interactive turns in an agent conversation must bind kv_store (parity with auto runs)."""

    @staticmethod
    def _captured_tool_names(monkeypatch, agent_tools) -> set[str]:
        import src.agent.agent as agent_mod
        import src.agent.graph as graph_mod

        captured: dict[str, list] = {}

        def fake_get_compiled_graph(model_name, **kwargs):
            captured["tools"] = kwargs.get("tools") or []
            return object()

        monkeypatch.setattr(graph_mod, "get_compiled_graph", fake_get_compiled_graph)

        agent_mod.ChatAgent(
            model_name="gemini-test",
            is_autonomous=True,
            agent_context={"name": "watcher", "tools": agent_tools},
        )
        return {t.name for t in captured["tools"]}

    def test_agent_with_explicit_permissions_gets_kv_store(self, monkeypatch) -> None:
        names = self._captured_tool_names(monkeypatch, agent_tools=["web_search"])
        assert "kv_store" in names

    def test_agent_with_unrestricted_permissions_gets_kv_store(self, monkeypatch) -> None:
        names = self._captured_tool_names(monkeypatch, agent_tools=None)
        assert "kv_store" in names
