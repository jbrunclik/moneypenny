# Artifact checklist ticks (Nov 14 2026)

**Intent.** "What's left on my list?" should work for a checklist artifact. Today
it cannot: 7 of the 12 production artifacts are checklists, only one calls
`mp.state.set`, and no artifact has ever saved state - ticks live only in the
frame until a reload. So the runtime saves ticks itself, and the agent can read
them.

**Goals.** Every `.mp-checklist` checkbox keeps its tick across reloads and
devices with no artifact-authored code; `read_artifact` reports which items are
done and which are open.
**Non-goals.** Live sync between two open devices (TODO "Live artifact state
sync"); reading other artifact state for the agent.
**Anti-goals.** Ticks and an artifact's own `mp.state` must never overwrite
each other.

## Approaches

1. **Envelope in the existing state (picked).** The stored value becomes
   `{"app": <the artifact's own state>, "checklist": {"<label key>": true}}`.
   The bridge hands the artifact's code only `app` and keeps `checklist` itself.
   Same column and endpoint, no migration - no stored state exists to convert.
2. Separate `checklist` column, message type and endpoint: cleanest split, but
   a migration plus schema/OpenAPI/TS changes for the same behaviour.
3. Save ticks only when the artifact does not use `mp.state`: no format change,
   but a checklist with a score counter would lose its ticks.

## Design

- **Bridge** (`web/src/artifact/bridge-client.ts`): `mp.state.get/set` read and
  write `app`; a capture-phase `change` listener on `.mp-checklist
  input[type=checkbox]` updates `checklist` and posts the whole envelope as
  `mp:state`; `applyInit` restores ticks after the HTML renders. A stored value
  that is not an envelope (none exist) is treated as `app`.
- **Label key**: the item's `<label>` text, whitespace collapsed and trimmed; a
  repeated label gets `#2`, `#3`. Rewording one item in `update_artifact`
  keeps the others' ticks.
- **Agent** (`read_artifact`): parse `.mp-checklist` labels from the current
  HTML with the same key rule (stdlib `html.parser`), return
  `"checklist": {"done": [...], "open": [...]}` beside the HTML when the page
  has a checklist; the description names "what's left on my list?".
- **Instrumentation**: `read_artifact` logs `checklist_items` and
  `checklist_done`; the artifact usage check in docs/regular-review.md counts
  artifacts with saved ticks.

**Left to the builder.** Where the key helper lives on each side; test layout.
