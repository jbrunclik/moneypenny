"""Unit tests for quick-action defaults and sanitization."""

from src.api.routes.program_quick_actions import (
    QUICK_ACTION_DEFAULTS,
    resolve_quick_actions,
    sanitize_quick_actions,
)


def _valid(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "abc123",
        "emoji": "\U0001f4ca",
        "label": "Log & review",
        "body": "Assess today's session.",
        "fields": ["Results", "Comments"],
    }
    base.update(overrides)
    return base


class TestDefaults:
    def test_sports_and_language_have_defaults(self) -> None:
        assert len(QUICK_ACTION_DEFAULTS["sports"]) == 2
        assert len(QUICK_ACTION_DEFAULTS["language"]) == 2

    def test_defaults_pass_sanitization_unchanged(self) -> None:
        for ns, defaults in QUICK_ACTION_DEFAULTS.items():
            assert sanitize_quick_actions(defaults) == defaults, ns


class TestSanitize:
    def test_keeps_valid_entries(self) -> None:
        assert sanitize_quick_actions([_valid()]) == [_valid()]

    def test_drops_malformed_entries_but_keeps_the_rest(self) -> None:
        raw = [_valid(), {"id": "x"}, "garbage", _valid(id="def456", fields=[])]
        result = sanitize_quick_actions(raw)
        assert [a["id"] for a in result] == ["abc123", "def456"]

    def test_non_list_input_yields_empty(self) -> None:
        assert sanitize_quick_actions(None) == []
        assert sanitize_quick_actions({"id": "x"}) == []

    def test_caps_at_twelve_actions(self) -> None:
        raw = [_valid(id=f"id{i}") for i in range(15)]
        assert len(sanitize_quick_actions(raw)) == 12

    def test_drops_entries_over_limits(self) -> None:
        too_long_body = _valid(body="x" * 2001)
        too_many_fields = _valid(fields=[f"f{i}" for i in range(7)])
        assert sanitize_quick_actions([too_long_body, too_many_fields]) == []


class TestResolve:
    def test_missing_key_returns_namespace_defaults(self) -> None:
        program = {"id": "pushups", "name": "Push-ups", "emoji": "x", "created_at": "t"}
        assert resolve_quick_actions(program, "sports") == QUICK_ACTION_DEFAULTS["sports"]

    def test_explicit_empty_list_stays_empty(self) -> None:
        program = {"id": "p", "quick_actions": []}
        assert resolve_quick_actions(program, "sports") == []

    def test_stored_actions_are_sanitized(self) -> None:
        program = {"id": "p", "quick_actions": [_valid(), "junk"]}
        assert resolve_quick_actions(program, "language") == [_valid()]
