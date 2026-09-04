# Program Quick Actions — Design

- **Date:** 2026-09-04
- **Status:** Approved (design); implementation pending
- **Author:** Jiri Brunclik + Claude

## Context & motivation

Program conversations (sports, language) are ritualized. In the sports program the
user opens the chat after a workout and types the same routine every time: "look at
the data, assess progression, update the Garmin workouts, prepare the table for the
next session", followed by a few subjective notes (hang time, how a set felt). The
trainer prompt already describes this routine as its "Returning Sessions" flow; what
is missing is a one-tap way to trigger it with the day's notes attached.

The app already has a precedent: opening a program auto-sends a hidden
`[System: session-start]` message. Quick actions generalize that idea into
user-defined, per-program, one-tap prompts.

## Goals

- Per-program **quick actions**: a saved prompt with an emoji, a short label, a
  plain-prose body, and an optional list of **fields** the action asks for before
  sending.
- **Send immediately** on tap when the action has no fields. When it has fields,
  show a small form (one input per field) whose primary button sends.
- Field answers are **appended as structured key–value lines** under the body; empty
  fields are omitted. The body itself contains no template syntax.
- Fully **customizable per program**: create, edit, reorder, delete. Two creation
  paths: an editor behind the program header, and "Save as quick action" on a user
  message already in the conversation.
- Built once in the shared program layer so **sports and language** both get it,
  each with its own seeded defaults.
- Works on desktop and mobile (768 px breakpoint) without regressing the iOS
  keyboard/auto-scroll behavior.

## Non-goals (YAGNI for v1)

- Quick actions in ordinary (non-program) conversations or for autonomous agents.
- Typed fields (number, select, date). All fields are free text.
- Inline `{placeholder}` templating in the body (rejected in design review as too
  fiddly; the appended key–value block replaces it).
- Agent-suggested / LLM-generated chips. Could be layered on later.
- Fully autonomous post-workout runs triggered by new Garmin activities.
- Sharing actions between programs or users.

## Data model

Quick actions live **inside the program object** in the existing `programs` list
that each program namespace keeps in `kv_store` (key `programs`, namespace `sports`
or `language`). They are deliberately **not** stored under the `{program_id}:`
prefix: `program_context.py` injects every key under that prefix into the system
prompt on every turn, and the actions are UI configuration, not training data.

```jsonc
{
  "id": "strength",
  "name": "Strength",
  "emoji": "🏋️",
  "created_at": "...",
  "quick_actions": [
    {
      "id": "a1b2c3",                 // short random id, stable across edits
      "emoji": "📊",
      "label": "Log & review",        // chip text
      "body": "Business as usual: assess progression against the plan, update the Garmin workouts, and prepare the table for the next session.",
      "fields": ["Hang time (s)", "Comments"]   // ordered labels; may be empty
    }
  ]
}
```

Limits (validated server-side): ≤ 12 actions per program, label ≤ 40 chars, body ≤
2000 chars, ≤ 6 fields, field label ≤ 40 chars. Programs created before this
feature have no `quick_actions` key; readers treat a missing key as the seeded
defaults (see below), so existing programs get the defaults without a migration.

## Message composition

On send, the client builds one ordinary user message:

```
<body>

<Field 1 label>: <value>
<Field 2 label>: <value>
```

Rules:
- The key–value block is separated from the body by a blank line.
- A field with an empty (whitespace-only) value is omitted entirely.
- If all fields are empty, only the body is sent.
- Multi-line values are kept as typed; continuation lines are indented by two
  spaces so the block stays readable and unambiguous to the model.
- The message goes through the normal `sendMessage()` path and renders as a
  normal user bubble. No new message type, no special handling in history, sync,
  stream resume, or compaction. The trainer sees exactly what the user would have
  typed.

## Seeded defaults

Programs without a `quick_actions` key resolve to these defaults. They are ordinary
rows once the user edits anything (the first save writes the full list).

Sports:

| Emoji | Label | Body | Fields |
|-------|-------|------|--------|
| 📋 | Plan today | Plan today's session. Check my Garmin readiness first and tell me which numbers drove the intensity call. | Comments |
| 📊 | Log & review | Assess today's session against the plan and stored progress, note any PRs, update the Garmin workouts for the next session, and prepare the overview table. | Results, Comments |

Language:

| Emoji | Label | Body | Fields |
|-------|-------|------|--------|
| 📖 | New lesson | Start a new lesson. | — |
| 🧠 | Quiz me | Quiz me on the vocabulary from the last two lessons. | — |

Defaults are defined once in the frontend (per namespace) and mirrored in the
backend seed used when a program is created, so the API returns them explicitly for
new programs and the "missing key" fallback only matters for pre-existing programs.

## API

Extend the shared `register_program_routes` in `src/api/routes/programs.py`:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/{ns}/programs` | GET | Unchanged shape plus `quick_actions` on each item |
| `/api/{ns}/programs/<program_id>/quick-actions` | PUT | Replace the full ordered list (create/edit/reorder/delete are all one PUT) |

A single PUT-the-whole-list endpoint keeps the client and server trivially
consistent and matches how the program list itself is stored. Request and response
schemas are Pydantic models in `src/api/schemas.py` (`QuickActionItem`,
`UpdateQuickActionsRequest`, response reuses the programs response). Validation
enforces the limits above; unknown program id → 404. Run `make openapi && make types`
to regenerate `generated-api.ts`.

## Frontend

### Components

- **`components/QuickActionsBar.ts`** — renders the chip row from a program's
  actions. Handles tap → either `sendQuickAction(action, {})` or opens the field
  form. Emits nothing else; pure presentation plus the two callbacks.
- **`components/QuickActionForm.ts`** — the field form. Bottom sheet on mobile
  (reuse `ActionSheet.ts` styling/behavior), popover anchored to the chip on desktop.
  One auto-growing textarea per field, first field focused, `Send` primary,
  `Cancel` secondary, Escape closes. Cmd/Ctrl+Enter sends.
- **`components/QuickActionsEditor.ts`** — modal listing the program's actions
  (drag reorder, edit, delete, add). Editing shows emoji picker (reuse the sports
  emoji grid), label, body textarea, and a field list (add/remove/reorder chips).
  Saves via PUT. Opened from a "Quick actions" gear button in the program header
  (added to `actions` in `renderSportsProgramHeader` / language equivalent).
- **`core/quick-actions.ts`** — glue: current program's actions (from the store),
  `composeQuickActionMessage(action, values)`, `sendQuickAction()`, mount/unmount of
  the bar when entering/leaving a program view, and the "Save as quick action"
  handler.
- **"Save as quick action"** — new item in the user-message action menu
  (`components/messages/actions.ts`), shown only inside program conversations. Opens
  `QuickActionsEditor` in add mode prefilled with the message text as the body.

### Placement & behavior

- The bar mounts directly above the composer, inside the composer container so it
  moves with the keyboard on iOS. Chips scroll horizontally; no wrapping.
- Desktop: always visible in program conversations.
- Mobile: visible when the textarea is empty and no reply is streaming; hidden
  while typing or streaming. Transition is opacity + transform only (never height
  animation) per the auto-scroll rules; the container reserves its height when
  visible and collapses via a class toggle, and the composer-height observer
  (`core/composer-height.ts`) must account for it.
- While streaming, chips are disabled (not hidden) on desktop.
- Entering a program calls the bar mount; `leaveSportsView()` / language equivalent
  unmounts it. Ordinary conversations never render it.

### State

`quick_actions` rides along on the `SportsProgram` / `LanguageProgram` objects the
store already caches. The PUT response replaces the cached program. No new store
slice.

## Backend touch points

- `src/api/routes/programs.py`: PUT endpoint, seeds on create, include
  `quick_actions` in list output.
- `src/api/schemas.py`: schemas + limits.
- `src/agent/prompts.py`: one sentence in the shared program preamble telling the
  model that a user message may end with a `Label: value` block from a quick action
  and to treat it as the user's data for this turn. No other prompt change.

## Error handling

- PUT failures → toast, editor stays open with the user's edits intact.
- Send failures use the existing outbox/retry path unchanged.
- Corrupt or over-limit stored actions are dropped server-side on read with a
  warning log, never returned as a 500.

## Testing

- **Backend**: unit tests for validation limits, seeding on create, missing-key
  fallback, PUT replace semantics, 404 on unknown program.
- **Frontend unit**: `composeQuickActionMessage` (empty fields omitted, blank line
  separator, multi-line indentation, all-empty → body only); bar show/hide state
  transitions; editor save payload.
- **E2E**: tap a no-field chip sends the body; tap a field chip → form → send
  produces the composed message in the transcript; "Save as quick action" prefills
  the editor; both desktop and mobile projects.
- **Visual**: baselines for the bar (desktop + mobile), form, and editor via
  `/regen-baselines` after the UI settles.
- **Scroll regression**: run the scroll/auto-scroll suites and verify on a real
  iPhone with the keyboard open, since the bar changes composer height.

## Open decisions resolved during design

- Tap sends immediately (vs. inserting editable text): **send immediately**.
- Parameters as inline `{placeholders}` vs. separate field list appended as
  structured data: **field list, appended as `Label: value` lines**.
- Storage in `{program_id}:quick_actions` vs. inside the program object: **inside
  the program object**, to stay out of per-turn prompt injection.
