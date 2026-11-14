# Artifact Checklist Ticks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `.mp-checklist` ticks persist on their own, and `read_artifact` tells the agent which items are done and open.

**Architecture:** The artifact's stored state becomes an envelope `{app, checklist}`. The frame's bridge owns `checklist` (saves on change, restores after render) and hands artifact code only `app`. The backend parses checklist labels from the HTML and joins them with the saved ticks.

**Tech Stack:** TypeScript (frame bridge, Vitest, Playwright), Python (LangChain tool, stdlib `html.parser`, pytest).

**Spec:** docs/superpowers/specs/2026-11-14-artifact-checklist-ticks-design.md

## Global Constraints

- Envelope keys exactly `app` and `checklist`; `checklist` maps label key -> `true` (unticked keys are removed).
- Label key: the `<label>` textContent, whitespace runs collapsed to one space, trimmed; the n-th repeat of a label gets ` #n` (n >= 2). Same rule on both sides.
- A stored value that is not an object with an `app` or `checklist` key is treated as `app` (no ticks).
- No migration, no API or OpenAPI change.

## Review Focus

- An artifact calling `mp.state.set({...})` after the user ticked items keeps the ticks (anti-goal) -> bridge test.
- Two items with the same label tick independently -> bridge test and backend test.
- A checklist item whose label has nested markup (`<label><input> <b>Milk</b> 2 l</label>`) keys as "Milk 2 l" on both sides -> backend test mirrors the bridge test.
- An item reworded by `update_artifact` drops only its own tick -> backend test (ticks keyed by old label simply do not match).
- A page with no checklist: `read_artifact` has no `checklist` field -> backend test.

---

### Task 1: Bridge envelope and auto-saved ticks

**Files:**
- Modify: `web/src/artifact/bridge-client.ts`, `web/src/artifact/frame.ts`
- Test: `web/tests/component/artifact-bridge-client.test.ts`

**Interfaces:**
- Produces: `checklistKeys(root: ParentNode): Array<{ input: HTMLInputElement; key: string }>` (exported, bridge-client.ts); `BridgeClient.restoreChecklist(): void`, called by frame.ts after `loadArtifact` resolves.

- [ ] **Step 1: Failing tests** in artifact-bridge-client.test.ts:
  - `hands artifact code only its own state`: applyInit `{app: {n: 1}, checklist: {Milk: true}}` -> `await mp.state.get()` equals `{n: 1}`.
  - `treats a legacy value as the artifact's own state`: applyInit `{n: 1}` -> get equals `{n: 1}`.
  - `saves a tick as the whole envelope`: checklist `<ul class="mp-checklist"><li><label><input type=checkbox> Milk</label></li></ul>`, change event on the box checked -> last posted `mp:state` is `{app: null, checklist: {Milk: true}}`; unchecking posts `{app: null, checklist: {}}`.
  - `keeps ticks when artifact code sets its state`: tick Milk, then `mp.state.set({score: 3})` -> posted `{app: {score: 3}, checklist: {Milk: true}}`.
  - `restores ticks after render`: applyInit with `{checklist: {'Eggs #2': true}}`, body has three items Milk, Eggs, Eggs -> after `restoreChecklist()` only the third box is checked.
  - `keys nested label markup by its text`: `<label><input type=checkbox> <b>Milk</b>  2 l</label>` -> key `Milk 2 l`.
- [ ] **Step 2:** `cd web && npx vitest run tests/component/artifact-bridge-client.test.ts` -> the new tests FAIL.
- [ ] **Step 3:** Implement in bridge-client.ts: envelope parsing in `applyInit`, `get/set` on `app`, a capture-phase `change` listener on the document for `.mp-checklist input[type=checkbox]` that rebuilds `checklist` from the boxes and posts the envelope, `restoreChecklist()`; frame.ts calls it in the `loadArtifact` `.then` before posting `mp:rendered`.
- [ ] **Step 4:** Same vitest command -> PASS; `cd web && npx tsc --noEmit` clean.

### Task 2: read_artifact reports done and open items

**Files:**
- Create: `src/agent/tools/artifact_checklist.py`
- Modify: `src/agent/tools/artifacts.py` (read_artifact)
- Test: `tests/unit/test_artifact_checklist.py`, `tests/unit/test_artifact_tools.py`

**Interfaces:**
- Produces: `checklist_items(html: str) -> list[str]` (label keys in page order, Global Constraints rule); `checklist_status(html: str, state: Any) -> dict[str, list[str]] | None` -> `{"done": [...], "open": [...]}` in page order, `None` when the page has no checklist.

- [ ] **Step 1: Failing tests**: `checklist_items` for repeats (`["Eggs", "Eggs #2"]`) and nested markup (`"Milk 2 l"`); `checklist_status` with envelope `{"checklist": {"Milk": True}}` over Milk/Bread -> `{"done": ["Milk"], "open": ["Bread"]}`; a legacy/None state -> all open; no `.mp-checklist` -> None; in test_artifact_tools.py `read_artifact` of a checklist artifact with saved ticks returns `checklist`, and of a plain page has no `checklist` key.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/unit/test_artifact_checklist.py tests/unit/test_artifact_tools.py -q -n0` -> FAIL.
- [ ] **Step 3:** Implement with `html.parser.HTMLParser` (track depth inside an element whose class list has `mp-checklist`, collect `<label>` text); read_artifact adds `checklist` when not None, logs `Artifact read` with `checklist_items`/`checklist_done`; its docstring: "Read an artifact's current HTML and, for a checklist, which items are done and which are still open - use it for "what's left on my list?" (before editing one from an earlier turn, too)."
- [ ] **Step 4:** Same pytest -> PASS; `make prompt-snapshots` (description changed).

### Task 3: End to end, eval, docs, announcement

**Files:**
- Test: `web/tests/e2e/` artifact spec (tick -> reload -> still ticked), a new eval case `evals/cases/artifact_checklist_left.yaml`
- Modify: `docs/features/artifacts.md`, `docs/regular-review.md`, `TODO.md` (remove the item), skill `src/agent/skills/artifact-design/SKILL.md` (ticks save themselves; mp.state is for other state)
- Create: `announcements/2026-11-14-checklist-ticks.md` (Czech + English)

- [ ] **Step 1:** E2E: seed a conversation with a checklist artifact, tick an item in the frame, reload, the item is still ticked. `make build`, then `E2E_PORT=8064 make test-fe-e2e` filtered to the spec -> PASS.
- [ ] **Step 2:** Eval case: seeded checklist artifact with saved ticks, user "co mi ještě zbývá na seznamu?" -> required `read_artifact`, rubric names the open items. Run `--only artifact_checklist_left` twice -> PASS.
- [ ] **Step 3:** Docs, review check (artifacts with saved ticks), TODO, announcement; `make lint`, `make test-all` green; commit; deploy.
