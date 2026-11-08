"""Unit tests for ChatAgent construction options and tool wiring (src/agent/agent.py)."""


class TestChatAgentOverrides:
    """enable_context_cache=False and system_prompt_override (delegate subagent)."""

    @staticmethod
    def _construct(monkeypatch, **kwargs):
        import src.agent.agent as agent_mod

        def fail_cache_lookup(*args, **kw):
            raise AssertionError("cache lookup must not run")

        monkeypatch.setattr(agent_mod, "get_cached_content_name", fail_cache_lookup)
        # ChatAgent now builds via the memoized get_compiled_graph; stub it so
        # construction skips real (slow) graph compilation.
        monkeypatch.setattr(agent_mod, "get_compiled_graph", lambda *a, **kw: object())
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


class TestStandingChatToolWiring:
    """A standing chat binds the ordinary chat tools plus kv_store, and keeps
    the freshness check and the standard cache profile."""

    @staticmethod
    def _agent(monkeypatch):
        import src.agent.agent as agent_mod
        from src.agent.standing import StandingContext

        captured: dict[str, list] = {}

        def fake_get_compiled_graph(model_name, **kwargs):
            captured["tools"] = kwargs.get("tools") or []
            return object()

        monkeypatch.setattr(agent_mod, "get_compiled_graph", fake_get_compiled_graph)
        agent = agent_mod.ChatAgent(
            model_name="gemini-test",
            standing=StandingContext("agent", "Watcher", "Watch", None, "agent:a1"),
        )
        return agent, {t.name for t in captured["tools"]}

    def test_gets_kv_store_and_the_chat_tools(self, monkeypatch) -> None:
        _, names = self._agent(monkeypatch)
        assert {"kv_store", "schedule", "manage_memory"} <= names

    def test_freshness_gate_and_standing_cache(self, monkeypatch) -> None:
        from src.agent.context_cache import CacheProfile

        agent, names = self._agent(monkeypatch)
        assert agent.freshness_gate is ("research" in names)
        assert agent._get_cache_profile() == CacheProfile.STANDING

    def test_standing_chats_always_think_fully(self, monkeypatch) -> None:
        """Review: an easy-looking session start or quiz grading must not drop
        to light thinking - the freshness lookups stay, the light graph goes."""
        agent, _ = self._agent(monkeypatch)
        assert agent.light_graph is None
