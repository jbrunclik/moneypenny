# Todoist add_tasks and list_completed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans.

**Goal:** two new `todoist` actions. **Spec:** `docs/superpowers/specs/2026-11-19-todoist-bulk-add-and-completed-design.md`

## Global Constraints
- `TODOIST_MAX_BULK_ADD = 25` (constant beside the handlers); `list_completed` range at most 92 days.
- Dates are APP_TIMEZONE local; `until` inclusive (sent as the next local midnight, exclusive).

## Review Focus
1. More than 25 entries → error, nothing created (`test_add_tasks_over_the_cap`).
2. One entry fails → the others still land, the failure is named (`test_add_tasks_partial_failure`).
3. `since` after `until`, or a range over 92 days → a clear error (`test_list_completed_bad_range`).
4. The `tasks` parameter stays Gemini-convertible (`test_every_param_has_a_concrete_type` for todoist).
5. Completed pages under `items` are followed (`test_completed_pages_follow_items_cursor`).

### Task 1: handlers + client paging (TDD) - `todoist_tasks.py`, `todoist_client.py`, tests in `test_todoist_tasks.py` / `test_todoist_tool.py`
### Task 2: tool wiring - `todoist.py` (`tasks`, `since`, `until` params, dispatch, docstring), `make prompt-snapshots`
### Task 3: eval fake + cases - `FakeTodoist` serves `/tasks/completed/by_completion_date`; cases `todoist_add_several_one_call`, `todoist_done_this_week`; run `--only` x3, report cost
### Task 4: docs (todoist.md), TODO re-measure, announcement; lint + test (backend only; no UI change) → commit, push, deploy
