# One approval mechanism, step 4 - destructive chat changes on a card

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In a chat turn, a delete or archive (the run gate's `DESTRUCTIVE_OPERATIONS`) does not run: it lands on the turn's `chat_change` card, and the server performs exactly those calls when the user approves.

**Architecture:** `check_autonomous_permission` returns a held result in chat for a destructive call: `src/agent/chat_changes.py` files (or extends) the turn's one `chat_change` proposal - each call with its tool, full arguments (`call_arguments`) and the item's name looked up from the integration - and the tool returns the card text instead of acting. Approving runs each stored call through its tool with a bypass flag set, under the card's conversation context; the result line says what happened.

**Tech Stack:** Flask, LangGraph tools, SQLite; TypeScript.

**Spec:** docs/superpowers/specs/2026-11-09-one-approval-mechanism-design.md (D, Applying, The card)

## Global Constraints

- Gated in chat: exactly `DESTRUCTIVE_OPERATIONS` (Todoist delete_task / delete_project / delete_section / archive_project, Calendar delete_event, Rouvy delete). Not gated in chat: completes, reschedules, attendee changes (the prompt rule keeps asking about ambiguous ones).
- One card per turn: all of a turn's destructive calls collect into it, one detail row per item, applied together on one approval.
- The card shows the item by name ("Task: Buy milk"), never only an id; a failed lookup falls back to the id.
- Unattended runs are unchanged (their gate files `agent_action` cards).
- The model never re-issues the change after a yes; the prompt's "confirm destructive actions in text first" rule becomes "the tool shows the card".
- A7 What's new post; A8: "Proposal resolved" covers it, plus an "Chat change applied" line (calls, failed); review check; TODO re-measure.

## Review Focus

1. Two destructive calls in one round run in parallel threads - one card, not two.
2. Approving after the item was already deleted elsewhere - the result says so, no crash.
3. A partial failure (2 of 3 deleted) - the card records both, the agent hears it.
4. The apply path re-entering the gate - must not file a new card.
5. A typed yes answers the card like any one-option card.

---

### Task 1: the gate, the card, applying

**Files:** create `src/agent/chat_changes.py`; modify `src/agent/tools/permission_check.py` (returns `str | None`), the four integration tools (return the held result), `todoist_tasks.py` / `todoist_projects.py` / `google_calendar.py` / `rouvy.py` (name lookups), `src/db/models/proposals.py` (`turn_proposal(request_id, kind)`, `extend_proposal(id, summary, details, options)`), `src/agent/prompt_texts/productivity.py`; tests `tests/unit/test_chat_changes.py`, prompt snapshots.

**Interfaces:** `KIND = "chat_change"`; payload `{"calls": [{"tool", "args", "item"}]}`; `hold_destructive_call(tool: str, args: Mapping[str, object]) -> str | None`; `apply_chat_change(proposal, option) -> str`; `item_label(tool, args) -> str`.

- [ ] Tests: a chat delete files a card and does not call the API; two deletes in one turn -> one card, two rows, summary "Delete 2 items"; two parallel calls -> one card; approve runs both calls (API called with the stored ids) and the result names them; one failing -> result "Deleted 1 of 2 - ..."; all failing -> failed; the apply path does not re-gate; a run is unaffected; non-destructive calls pass; a failed lookup shows the id.
- [ ] Implement; prompt rule updated; `make prompt-snapshots`.
- [ ] Commit `feat(agent): deletes asked for in chat wait on a card`.

### Task 2: card icon, docs, What's new

- [ ] `kindIcon('chat_change')` -> a trash icon; docs (proposals.md table, agent-tools.md gate note); regular-review check; TODO re-measure; announcement. Commit.
