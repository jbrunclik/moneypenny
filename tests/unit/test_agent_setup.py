"""Unit tests for ChatAgent construction options and tool wiring (src/agent/agent.py)."""


class TestChatAgentOverrides:
    """system_prompt_override (delegate subagent)."""

    @staticmethod
    def _construct(monkeypatch, **kwargs):
        import src.agent.agent as agent_mod

        # ChatAgent now builds via the memoized get_compiled_graph; stub it so
        # construction skips real (slow) graph compilation.
        monkeypatch.setattr(agent_mod, "get_compiled_graph", lambda *a, **kw: object())
        return agent_mod.ChatAgent(model_name="gemini-test", **kwargs)

    def test_system_prompt_override_has_no_static_prefix(self, monkeypatch) -> None:
        agent = self._construct(monkeypatch, system_prompt_override="You are a test.")
        assert agent._static_prefix_profile is None

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
        from src.agent.prompts import CacheProfile

        agent, names = self._agent(monkeypatch)
        assert agent.freshness_gate is ("research" in names)
        assert agent._get_cache_profile() == CacheProfile.STANDING

    def test_standing_chats_always_think_fully(self, monkeypatch) -> None:
        """Review: an easy-looking session start or quiz grading must not drop
        to light thinking - the freshness lookups stay, the light graph goes."""
        agent, _ = self._agent(monkeypatch)
        assert agent.light_graph is None

    def test_standing_chats_can_still_think_deep(self, monkeypatch) -> None:
        """With a deep level set, a hard turn in a standing chat (a training
        block plan) gets it; only the light level is kept from them."""
        from src.config import Config

        monkeypatch.setattr(Config, "FRESHNESS_GATE_DEEP_THINKING_LEVEL", "high")
        agent, _ = self._agent(monkeypatch)
        assert agent.deep_graph is not None


class TestHardTurnThinking:
    """Nov 26 2026: `high` turns were 12% of chat turns and a third of the
    spend (median 56 s); hard turns now run at the model's own level -
    medium on Hydrogen, the API default on Carbon."""

    def test_hard_turns_run_at_the_models_own_level_by_default(self, monkeypatch) -> None:
        """The shipped default, read from a fresh copy of src/config.py with
        no .env and no environment value."""
        import importlib.util

        import dotenv

        import src.config

        monkeypatch.delenv("FRESHNESS_GATE_DEEP_THINKING_LEVEL", raising=False)
        monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: False)
        spec = importlib.util.spec_from_file_location("_fresh_config", src.config.__file__)
        assert spec is not None and spec.loader is not None
        fresh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fresh)

        assert fresh.Config.FRESHNESS_GATE_DEEP_THINKING_LEVEL == ""
