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


def test_program_identity_defaults_and_overrides() -> None:
    from evals.run import program_identity

    cycling = EvalCase(id="c", description="", user="u", mode="sports")
    strength = EvalCase(
        id="s",
        description="",
        user="u",
        mode="sports",
        program={"id": "strength", "name": "Posilovna"},
    )
    assert program_identity(cycling) == ("Cyklistika", "cycling")
    assert program_identity(strength) == ("Posilovna", "strength")


def test_chat_program_is_inherited() -> None:
    chat = {"mode": "sports", "program": {"id": "strength", "name": "Posilovna"}, "messages": []}
    assert merge_chat({"id": "c"}, chat)["program"] == {"id": "strength", "name": "Posilovna"}


def test_freeze_summary_writes_the_summary_into_the_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evals.freeze_summary import freeze_summary
    from src.config import Config

    keep = Config.CONVERSATION_COMPACTION_KEEP_RECENT
    messages = _long_history(keep + 6)
    _write(tmp_path, "ride.yaml", {"mode": "sports", "messages": messages})
    path = tmp_path / "ride.yaml"
    path.write_text("# Synthetic chat - keep this header\n" + path.read_text())
    seen: list[int] = []

    def fake_summarize(chunk: list[dict[str, Any]], *_: Any) -> str:
        seen.append(len(chunk))
        return "Uživatel jezdí třikrát týdně."

    summary = freeze_summary(tmp_path / "ride.yaml", summarize=fake_summarize)
    assert "třikrát týdně" in summary
    assert sum(seen) == 6  # only the older messages are summarized
    chat = load_chat("ride", tmp_path)
    assert chat["summary"] == summary
    assert chat["messages"] == messages and chat["mode"] == "sports"
    assert path.read_text().startswith("# Synthetic chat - keep this header\n")


# Rendered size targets (characters, messages + tool digests): production
# medians Nov 18 2026 - program chats ~20-35k, ordinary chats 15-25k
_SIZE = {"sports": (18_000, 36_000), "chat": (15_000, 26_000)}
_SHARED = ("cycling_program", "strength_program", "family_logistics", "project_research")


@pytest.mark.parametrize("name", _SHARED)
def test_shared_chats_are_realistic(name: str) -> None:
    from langdetect import DetectorFactory, detect

    DetectorFactory.seed = 0
    chat = load_chat(name)
    messages = chat["messages"]
    assert len(messages) >= 20
    # Program data is context too (the stored-data section of the prompt)
    size = sum(len(m["content"]) + len(json.dumps(m.get("metadata") or {})) for m in messages)
    size += sum(len(v) for v in (chat.get("program_kv") or {}).values())
    low, high = _SIZE[chat.get("mode", "chat")]
    assert low <= size <= high, f"{name}: {size} characters"
    users = [m["content"] for m in messages if m["role"] == "user" and len(m["content"]) >= 20]
    # Czech typed without diacritics (as the family types) often detects as
    # a neighbouring language; the check is "not an English fixture"
    czech = [u for u in users if detect(u) in ("cs", "sk", "sl", "hr", "pl")]
    assert len(czech) >= 0.6 * len(users)
    assert any((m.get("metadata") or {}).get("tool_outputs") for m in messages)
    assert chat.get("summary", "").strip()
    if chat.get("mode") == "sports":
        assert chat.get("program_kv")


def test_chat_artifacts_are_inherited() -> None:
    chat = {"artifacts": [{"title": "Srovnání", "html": "<table></table>"}], "messages": []}
    assert merge_chat({"id": "c"}, chat)["artifacts"] == chat["artifacts"]


def test_frozen_summary_history_gets_artifact_ids(test_database: Any, test_user: Any) -> None:
    import evals.run as eval_run
    from src.config import Config

    keep = Config.CONVERSATION_COMPACTION_KEEP_RECENT
    history = _long_history(keep + 2)
    history[-1] = {"role": "assistant", "content": "Tabulka: {artifact_0}"}
    case = EvalCase(
        id="c",
        description="",
        user="u",
        history=history,
        frozen_summary="S",
        artifacts=[{"title": "Srovnání", "html": "<p>x</p>"}],
    )
    conv = test_database.create_conversation(test_user.id, "eval-c")
    _, sent, _ = eval_run._seed_case(case, test_user, test_database, conv.id)
    assert sent is not None
    assert "{artifact_0}" not in sent[-1]["content"]


def test_frozen_summary_gets_artifact_ids(test_database: Any, test_user: Any) -> None:
    """The chat's artifact may be mentioned only in its summarized part."""
    import evals.run as eval_run
    from src.agent.conversation_compaction import KV_NAMESPACE
    from src.config import Config

    keep = Config.CONVERSATION_COMPACTION_KEEP_RECENT
    case = EvalCase(
        id="c",
        description="",
        user="u",
        history=_long_history(keep + 2),
        frozen_summary="Srovnání je v tabulce {artifact_0}.",
        artifacts=[{"title": "Srovnání", "html": "<p>x</p>"}],
    )
    conv = test_database.create_conversation(test_user.id, "eval-c")
    _, sent, _ = eval_run._seed_case(case, test_user, test_database, conv.id)
    assert sent is not None
    assert "{artifact_" not in sent[0]["content"]
    assert "{artifact_" not in test_database.kv_get(test_user.id, KV_NAMESPACE, conv.id)


def test_program_chat_coverage_counts_stored_messages(test_database: Any, test_user: Any) -> None:
    """A program chat stores only the user turns; the summary covers the ones
    that precede the verbatim tail, so the tail's are not marked summarized."""
    from src.agent.conversation_compaction import KV_NAMESPACE
    from src.config import Config

    keep = Config.CONVERSATION_COMPACTION_KEEP_RECENT
    history = _long_history(keep + 8)  # alternating; 4 users among the first 8
    case = EvalCase(
        id="c", description="", user="u", mode="sports", history=history, frozen_summary="S"
    )
    conv = test_database.create_conversation(test_user.id, "eval-c")
    seed_frozen_summary(case, test_user, test_database, conv.id, store_messages=False)
    state = json.loads(test_database.kv_get(test_user.id, KV_NAMESPACE, conv.id))
    assert state["covered_count"] == 4


def test_summary_covers_survives_a_case_adding_turns(test_database: Any, test_user: Any) -> None:
    """The frozen summary covers a fixed number of the chat's messages; a case
    appending its own turns must not push chat messages out of both the
    summary and the verbatim tail."""
    from src.config import Config

    keep = Config.CONVERSATION_COMPACTION_KEEP_RECENT
    chat_messages = _long_history(keep + 6)
    own = [{"role": "user", "content": "own 1"}, {"role": "assistant", "content": "own 2"}]
    case = EvalCase(
        id="c",
        description="",
        user="u",
        history=chat_messages + own,
        frozen_summary="S",
        frozen_summary_covers=6,
    )
    conv = test_database.create_conversation(test_user.id, "eval-c")
    sent = seed_frozen_summary(case, test_user, test_database, conv.id)
    assert [m["content"] for m in sent[1:]] == [m["content"] for m in (chat_messages + own)[6:]]


def test_freeze_records_how_many_messages_the_summary_covers(tmp_path: Path) -> None:
    from evals.freeze_summary import freeze_summary
    from src.config import Config

    keep = Config.CONVERSATION_COMPACTION_KEEP_RECENT
    _write(tmp_path, "ride.yaml", {"messages": _long_history(keep + 5)})
    freeze_summary(tmp_path / "ride.yaml", summarize=lambda chunk, *_: "S")
    assert load_chat("ride", tmp_path)["summary_covers"] == 5
    merged = merge_chat({"id": "c"}, load_chat("ride", tmp_path))
    assert merged["frozen_summary_covers"] == 5
