"""A program's setup: quick actions and standing instructions the coach may
propose changes to (docs/superpowers/specs/2026-11-11-program-self-tuning-design.md)."""

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import date, timedelta

import pytest

from src.db.models import Database, User, use_database
from src.services import program_setup as ps
from src.services.program_setup import ProgramRef, SetupChangeError

REF = ProgramRef("sports", "cycling")


@pytest.fixture
def db(test_database: Database) -> Generator[Database]:
    with use_database(test_database):
        yield test_database


def _save_program(db: Database, user: User, **extra: object) -> None:
    program = {
        "id": "cycling",
        "name": "Cycling",
        "emoji": "🚴",
        "created_at": "2026-11-01",
        **extra,
    }
    db.kv_set(user.id, "sports", "programs", json.dumps([program]))


def _stored_actions(db: Database, user: User) -> list[dict[str, object]]:
    programs = json.loads(db.kv_get(user.id, "sports", "programs") or "[]")
    return programs[0]["quick_actions"]


_NEXT = {
    "id": "next",
    "emoji": "⏭️",
    "label": "Next workout",
    "body": "What is my next workout?",
    "fields": [],
}


def _add(**action: object) -> ps.SetupChange:
    return {"target": "quick_action", "op": "add", "action": {**_NEXT, "id": "new", **action}}


class TestQuickActions:
    def test_add_starts_from_the_defaults(self, db: Database, test_user: User) -> None:
        _save_program(db, test_user)  # no quick_actions key: the defaults apply

        ps.apply_change(test_user.id, REF, _add(label="Plan week"))

        ids = [a["id"] for a in _stored_actions(db, test_user)]
        assert ids == [*(a["id"] for a in ps.QUICK_ACTION_DEFAULTS["sports"]), "new"]

    def test_edit_replaces_only_the_named_action(self, db: Database, test_user: User) -> None:
        other = {**_NEXT, "id": "other", "label": "Other"}
        _save_program(db, test_user, quick_actions=[_NEXT, other])
        edited = {**_NEXT, "body": "What is my next workout? Use my Garmin readiness."}

        ps.apply_change(
            test_user.id,
            REF,
            {"target": "quick_action", "op": "edit", "action_id": "next", "action": edited},
        )

        assert _stored_actions(db, test_user) == [edited, other]

    def test_remove_drops_it(self, db: Database, test_user: User) -> None:
        _save_program(db, test_user, quick_actions=[_NEXT])

        ps.apply_change(
            test_user.id, REF, {"target": "quick_action", "op": "remove", "action_id": "next"}
        )

        assert _stored_actions(db, test_user) == []

    def test_edit_of_a_vanished_action_is_refused(self, db: Database, test_user: User) -> None:
        _save_program(db, test_user, quick_actions=[_NEXT])
        change: ps.SetupChange = {
            "target": "quick_action",
            "op": "edit",
            "action_id": "gone",
            "action": _NEXT,
        }

        with pytest.raises(SetupChangeError, match="no longer"):
            ps.apply_change(test_user.id, REF, change)
        assert _stored_actions(db, test_user) == [_NEXT]

    def test_quick_action_limits_hold(self) -> None:
        assert isinstance(ps.validate_change("sports", _add(label="x" * 41)), str)
        assert isinstance(ps.validate_change("sports", _add(fields=["a"] * 7)), str)
        assert isinstance(ps.validate_change("sports", _add(body="")), str)
        assert isinstance(ps.validate_change("sports", _add(id="bad id!")), str)
        assert not isinstance(ps.validate_change("sports", _add()), str)

    def test_the_list_cannot_grow_past_its_limit(self, db: Database, test_user: User) -> None:
        full = [{**_NEXT, "id": f"a{i}"} for i in range(ps.QUICK_ACTIONS_MAX_PER_PROGRAM)]
        _save_program(db, test_user, quick_actions=full)

        with pytest.raises(SetupChangeError, match="at most"):
            ps.apply_change(test_user.id, REF, _add())


class TestInstructions:
    def test_instruction_patch_merges(self, db: Database, test_user: User) -> None:
        db.kv_set(
            test_user.id, "sports", "cycling:routine", json.dumps({"days": 3, "z2_watts": 120})
        )
        change: ps.SetupChange = {
            "target": "instruction",
            "key": "routine",
            "patch": {"z2_watts": 125, "days": None},
        }

        ps.apply_change(test_user.id, REF, change)

        assert json.loads(db.kv_get(test_user.id, "sports", "cycling:routine") or "") == {
            "z2_watts": 125
        }

    def test_a_prose_instruction_is_replaced_whole(self, db: Database, test_user: User) -> None:
        db.kv_set(test_user.id, "sports", "cycling:goals", "Ride 200 km")

        ps.apply_change(
            test_user.id,
            REF,
            {"target": "instruction", "key": "goals", "text": "Ride 300 km by June"},
        )
        assert db.kv_get(test_user.id, "sports", "cycling:goals") == "Ride 300 km by June"

        with pytest.raises(SetupChangeError, match="text"):
            ps.apply_change(
                test_user.id, REF, {"target": "instruction", "key": "goals", "patch": {"km": 1}}
            )

    def test_only_instruction_keys_may_change(self) -> None:
        for key in ("progress", "vocabulary", "programs", "last_session"):
            reason = ps.validate_change(
                "sports", {"target": "instruction", "key": key, "patch": {"a": 1}}
            )
            assert isinstance(reason, str) and "goals" in reason
        assert not isinstance(
            ps.validate_change(
                "language", {"target": "instruction", "key": "grammar", "patch": {"a": 1}}
            ),
            str,
        )
        assert isinstance(
            ps.validate_change(
                "language", {"target": "instruction", "key": "routine", "patch": {"a": 1}}
            ),
            str,
        )


class TestDescribe:
    def test_describe_shows_before_and_after(self, db: Database, test_user: User) -> None:
        _save_program(db, test_user, quick_actions=[_NEXT])
        setup = ps.load_setup(test_user.id, REF)
        edited = {**_NEXT, "body": "What is my next workout? Date: today."}

        before, after = ps.describe_change(
            setup, {"target": "quick_action", "op": "edit", "action_id": "next", "action": edited}
        )

        # Only what changes - here the message
        assert before == "Message: What is my next workout?"
        assert before != after
        assert "Date: today" in after

    def test_a_new_action_has_no_before(self, db: Database, test_user: User) -> None:
        _save_program(db, test_user, quick_actions=[])
        before, after = ps.describe_change(
            ps.load_setup(test_user.id, REF), _add(label="Plan week")
        )
        assert before == "(none)" and "Plan week" in after


class TestDeclines:
    def test_decline_is_remembered_and_blocks_until_newer_evidence(
        self, db: Database, test_user: User
    ) -> None:
        change = _add(label="Plan week")
        ps.record_decline(test_user.id, REF, change, "Add Plan week")
        today = date.today()
        entries = ps.declined(test_user.id, REF)

        assert entries[0]["fingerprint"] == ps.fingerprint(change)
        assert ps.blocked_by_decline(
            entries, change, [f"{today - timedelta(days=1)}: asked for a plan"]
        )
        assert not ps.blocked_by_decline(
            entries, change, [f"{today + timedelta(days=1)}: asked again"]
        )
        assert not ps.blocked_by_decline(entries, _add(label="Other"), [f"{today}: x"])

    def test_the_declined_list_is_capped(self, db: Database, test_user: User) -> None:
        for i in range(ps.Config.SETUP_DECLINED_MAX + 5):
            ps.record_decline(test_user.id, REF, _add(label=f"A{i}"), f"Add A{i}")
        entries = ps.declined(test_user.id, REF)
        assert len(entries) == ps.Config.SETUP_DECLINED_MAX
        assert entries[-1]["summary"] == f"Add A{ps.Config.SETUP_DECLINED_MAX + 4}"

    def test_fingerprint_ignores_case_and_spacing_of_the_body(self) -> None:
        a = _add(body="What is my  next workout?")
        b = _add(body="what is my next workout? ")
        assert ps.fingerprint(a) == ps.fingerprint(b)
        assert ps.fingerprint(a) != ps.fingerprint(_add(body="Something else"))


class TestProgramForConversation:
    def test_a_program_chat_resolves_to_its_program(self, db: Database, test_user: User) -> None:
        conv = db.get_or_create_program_conversation("sports", test_user.id, "cycling")
        assert ps.program_for_conversation(conv.id, test_user.id) == REF

    def test_an_ordinary_chat_has_none(self, db: Database, test_user: User) -> None:
        conv = db.create_conversation(test_user.id, "Hello")
        assert ps.program_for_conversation(conv.id, test_user.id) is None


class TestReviewFixes:
    def test_a_card_for_a_hand_edited_action_is_refused(
        self, db: Database, test_user: User
    ) -> None:
        """Final review #1: the snapshot taken when suggested must still match."""
        _save_program(db, test_user, quick_actions=[_NEXT])
        coach: ps.SetupChange = {
            "target": "quick_action",
            "op": "edit",
            "action_id": "next",
            "action": {**_NEXT, "body": "Coach's version"},
        }
        coach = ps.with_snapshot(ps.load_setup(test_user.id, REF), coach)
        mine: ps.SetupChange = {
            "target": "quick_action",
            "op": "edit",
            "action_id": "next",
            "action": {**_NEXT, "body": "My own words"},
        }
        ps.apply_change(test_user.id, REF, mine)

        with pytest.raises(SetupChangeError, match="changed since"):
            ps.apply_change(test_user.id, REF, coach)
        assert _stored_actions(db, test_user)[0]["body"] == "My own words"

    def test_an_unchanged_target_still_applies(self, db: Database, test_user: User) -> None:
        _save_program(db, test_user, quick_actions=[_NEXT])
        change: ps.SetupChange = {"target": "quick_action", "op": "remove", "action_id": "next"}
        ps.apply_change(
            test_user.id, REF, ps.with_snapshot(ps.load_setup(test_user.id, REF), change)
        )
        assert _stored_actions(db, test_user) == []

    def test_an_instruction_changed_since_is_refused(self, db: Database, test_user: User) -> None:
        db.kv_set(test_user.id, "sports", "cycling:goals", "Ride 200 km")
        _save_program(db, test_user)
        change = ps.with_snapshot(
            ps.load_setup(test_user.id, REF),
            {"target": "instruction", "key": "goals", "text": "Ride 300 km"},
        )
        db.kv_set(test_user.id, "sports", "cycling:goals", "Ride 250 km")

        with pytest.raises(SetupChangeError, match="changed since"):
            ps.apply_change(test_user.id, REF, change)

    def test_the_snapshot_does_not_change_the_fingerprint(
        self, db: Database, test_user: User
    ) -> None:
        _save_program(db, test_user, quick_actions=[_NEXT])
        change: ps.SetupChange = {"target": "quick_action", "op": "remove", "action_id": "next"}
        snapped = ps.with_snapshot(ps.load_setup(test_user.id, REF), change)
        assert ps.fingerprint(snapped) == ps.fingerprint(change)

    def test_the_declined_list_is_not_under_the_program_prefix(
        self, db: Database, test_user: User
    ) -> None:
        """Final review #6: program_context injects every {program_id}: key into the prompt."""
        ps.record_decline(test_user.id, REF, _add(label="X"), "Add X")
        assert db.kv_list(test_user.id, "sports", prefix="cycling:") == []
        assert len(ps.declined(test_user.id, REF)) == 1

    def test_a_malformed_declined_entry_is_skipped(self, db: Database, test_user: User) -> None:
        entries = [
            {"fingerprint": "a"},
            {"fingerprint": "b", "declined_at": "not a date"},
            "junk",
            {"fingerprint": "c", "summary": "ok", "declined_at": "2026-11-01"},
        ]
        db.kv_set(test_user.id, "sports", "setup_declined:cycling", json.dumps(entries))
        assert [e["fingerprint"] for e in ps.declined(test_user.id, REF)] == ["c"]

    def test_evidence_must_cite_days_the_user_wrote(self, db: Database, test_user: User) -> None:
        """Final review #4: dates are checked against the chat, not taken on the model's word."""
        conv = db.get_or_create_program_conversation("sports", test_user.id, "cycling")
        db.add_message(conv.id, "user", "plan my week")
        today = date.today()
        days = ps.chat_dates(conv.id)

        assert today in days
        assert ps.evidence_problem([f"{today}: 'plan my week'"], days) is None
        assert "wrote" in (
            ps.evidence_problem([f"{today - timedelta(days=3)}: made up"], days) or ""
        )
        assert ps.evidence_problem([], days) is not None
        assert ps.evidence_problem(["you often ask"], days) is not None


class TestFieldChanges:
    """Show what changes, not the whole object (Nov 11 2026: a routine edit
    showed the full JSON twice)."""

    def test_an_instruction_patch_lists_only_the_changed_fields(
        self, db: Database, test_user: User
    ) -> None:
        routine = {
            "location": "Man Cave",
            "gtg_pullups": "1-2 strict",
            "ring_numbers": {"01": "Pull-ups"},
        }
        db.kv_set(test_user.id, "sports", "cycling:routine", json.dumps(routine))
        _save_program(db, test_user)
        change: ps.SetupChange = {
            "target": "instruction",
            "key": "routine",
            "patch": {
                "gtg_pullups": "3 strict, Wed + Thu",
                "ring_numbers": {"17": "Ring rows"},
                "old": None,
            },
        }

        rows = ps.field_changes(ps.load_setup(test_user.id, REF), change)

        assert rows == [
            {"field": "gtg pullups", "before": "1-2 strict", "after": "3 strict, Wed + Thu"},
            {"field": "ring numbers › 17", "before": "", "after": "Ring rows"},
        ]

    def test_a_removed_field_shows_what_goes(self, db: Database, test_user: User) -> None:
        db.kv_set(
            test_user.id,
            "sports",
            "cycling:routine",
            json.dumps({"days": ["Mon", "Wed"], "z2": 120}),
        )
        _save_program(db, test_user)
        rows = ps.field_changes(
            ps.load_setup(test_user.id, REF),
            {"target": "instruction", "key": "routine", "patch": {"days": None}},
        )
        assert rows == [{"field": "days", "before": "Mon, Wed", "after": ""}]

    def test_a_quick_action_edit_lists_only_what_differs(
        self, db: Database, test_user: User
    ) -> None:
        _save_program(db, test_user, quick_actions=[_NEXT])
        edited = {**_NEXT, "body": "What is my next workout? Use readiness.", "fields": ["Time"]}
        rows = ps.field_changes(
            ps.load_setup(test_user.id, REF),
            {"target": "quick_action", "op": "edit", "action_id": "next", "action": edited},
        )
        assert rows == [
            {
                "field": "Message",
                "before": "What is my next workout?",
                "after": "What is my next workout? Use readiness.",
            },
            {"field": "Questions", "before": "", "after": "Time"},
        ]

    def test_a_prose_instruction_is_one_row(self, db: Database, test_user: User) -> None:
        db.kv_set(test_user.id, "sports", "cycling:goals", "Ride 200 km")
        _save_program(db, test_user)
        rows = ps.field_changes(
            ps.load_setup(test_user.id, REF),
            {"target": "instruction", "key": "goals", "text": "Ride 300 km"},
        )
        assert rows == [{"field": "goals", "before": "Ride 200 km", "after": "Ride 300 km"}]

    def test_the_text_form_is_one_line_per_field(self, db: Database, test_user: User) -> None:
        _save_program(db, test_user, quick_actions=[_NEXT])
        edited = {**_NEXT, "label": "Next ride"}
        before, after = ps.describe_change(
            ps.load_setup(test_user.id, REF),
            {"target": "quick_action", "op": "edit", "action_id": "next", "action": edited},
        )
        assert (before, after) == ("Label: Next workout", "Label: Next ride")


class TestCollisions:
    """Nov 11 2026: accepting one suggestion made the next one on the same
    instruction look stale, though they touched different fields."""

    def _routine(self, db: Database, user: User) -> ps.ProgramSetup:
        db.kv_set(
            user.id,
            "sports",
            "cycling:routine",
            json.dumps({"gtg": "1-2 strict", "explain": None, "z2": 120}),
        )
        _save_program(db, user)
        return ps.load_setup(user.id, REF)

    def test_two_changes_to_different_fields_both_apply(
        self, db: Database, test_user: User
    ) -> None:
        current = self._routine(db, test_user)
        first = ps.with_snapshot(
            current, {"target": "instruction", "key": "routine", "patch": {"explain": "always"}}
        )
        second = ps.with_snapshot(
            current, {"target": "instruction", "key": "routine", "patch": {"gtg": "3 strict"}}
        )

        ps.apply_change(test_user.id, REF, first)
        ps.apply_change(test_user.id, REF, second)

        stored = json.loads(db.kv_get(test_user.id, "sports", "cycling:routine") or "")
        assert stored == {"gtg": "3 strict", "explain": "always", "z2": 120}

    def test_the_same_field_changed_meanwhile_is_a_conflict(
        self, db: Database, test_user: User
    ) -> None:
        current = self._routine(db, test_user)
        change = ps.with_snapshot(
            current, {"target": "instruction", "key": "routine", "patch": {"gtg": "3 strict"}}
        )
        ps.apply_change(
            test_user.id,
            REF,
            {"target": "instruction", "key": "routine", "patch": {"gtg": "2 strict"}},
        )

        with pytest.raises(ps.SetupConflictError):
            ps.apply_change(test_user.id, REF, change)
