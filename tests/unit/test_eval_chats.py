"""Shared synthetic chats for eval cases (evals/chats.py, `history_from:`).

Cases borrow a long, realistic conversation instead of each inlining one; its
older turns arrive as a frozen compaction summary seeded the way production
stores it.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from evals.chats import load_chat, merge_chat, seed_frozen_summary
from evals.run import EvalCase, load_cases

_CHAT = {
    "mode": "sports",
    "program_kv": {"plan": "A", "log": "x"},
    "integrations": {"garmin": {"state": "connected"}},
    "summary": "Earlier: the user rides three times a week.",
    "messages": [
        {"role": "user", "content": "ahoj"},
        {"role": "assistant", "content": "čau"},
    ],
}


def _write(directory: Path, name: str, data: dict[str, Any]) -> None:
    import yaml

    (directory / name).write_text(yaml.safe_dump(data, allow_unicode=True))


def test_case_inherits_chat_fields_and_wins() -> None:
    merged = merge_chat(
        {
            "id": "c",
            "user": "u",
            "program_kv": {"plan": "B"},
            "history": [{"role": "user", "content": "own"}],
        },
        _CHAT,
    )
    assert merged["mode"] == "sports"
    assert merged["program_kv"] == {"plan": "B", "log": "x"}
    assert merged["integrations"] == {"garmin": {"state": "connected"}}
    assert [h["content"] for h in merged["history"]] == ["ahoj", "čau", "own"]
    assert merged["frozen_summary"] == "Earlier: the user rides three times a week."


def test_case_mode_overrides_chat_mode() -> None:
    assert merge_chat({"mode": "chat"}, _CHAT)["mode"] == "chat"


def test_load_chat_resolves_dates(tmp_path: Path) -> None:
    _write(tmp_path, "c.yaml", {"messages": [{"role": "user", "content": "on {today}"}]})
    chat = load_chat("c", tmp_path)
    assert "{today}" not in chat["messages"][0]["content"]


def test_unknown_chat_fails_at_load(tmp_path: Path) -> None:
    (tmp_path / "c.yaml").write_text("id: c\nuser: u\nhistory_from: nope\nexpect: {rubric: r}\n")
    with pytest.raises(ValueError, match=r"c\.yaml.*nope"):
        load_cases(tmp_path)


def test_case_loads_a_shared_chat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chats = tmp_path / "chats"
    chats.mkdir()
    _write(chats, "ride.yaml", _CHAT)
    monkeypatch.setattr("evals.chats.CHATS_DIR", chats)
    (tmp_path / "c.yaml").write_text("id: c\nuser: u\nhistory_from: ride\nexpect: {rubric: r}\n")
    [case] = load_cases(tmp_path)
    assert case.history_from == "ride"
    assert case.mode == "sports"
    assert case.program_kv == {"plan": "A", "log": "x"}
    assert len(case.history) == 2
    assert case.frozen_summary == _CHAT["summary"]


def _long_history(n: int) -> list[dict[str, Any]]:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"} for i in range(n)
    ]


def test_frozen_summary_seeds_kv_and_history(test_database: Any, test_user: Any) -> None:
    from src.agent.conversation_compaction import KV_NAMESPACE
    from src.config import Config

    keep = Config.CONVERSATION_COMPACTION_KEEP_RECENT
    history = _long_history(keep + 8)
    case = EvalCase(
        id="c",
        description="",
        user="u",
        history=history,
        frozen_summary="SUMMARY TEXT",
    )
    conv = test_database.create_conversation(test_user.id, "eval-c")
    sent = seed_frozen_summary(case, test_user, test_database, conv.id)

    assert "SUMMARY TEXT" in sent[0]["content"]
    assert [m["content"] for m in sent[1:]] == [h["content"] for h in history[-keep:]]
    state = json.loads(test_database.kv_get(test_user.id, KV_NAMESPACE, conv.id))
    assert state["covered_count"] == 8
    assert state["segments"][0]["text"] == "SUMMARY TEXT"
    assert len(test_database.get_messages(conv.id)) == len(history)


def test_frozen_summary_in_program_chat_does_not_restore_messages(
    test_database: Any, test_user: Any
) -> None:
    from src.config import Config

    keep = Config.CONVERSATION_COMPACTION_KEEP_RECENT
    case = EvalCase(
        id="c",
        description="",
        user="u",
        mode="sports",
        history=_long_history(keep + 4),
        frozen_summary="S",
    )
    conv = test_database.create_conversation(test_user.id, "eval-c")
    sent = seed_frozen_summary(case, test_user, test_database, conv.id, store_messages=False)
    assert "S" in sent[0]["content"]
    assert test_database.get_messages(conv.id) == []
