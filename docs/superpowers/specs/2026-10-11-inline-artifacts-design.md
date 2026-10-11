# Inline Artifacts - Design

Status: approved design, Oct 11 2026. Replaces the TODO.md "Artifacts" item (side
panel version); the side panel is a follow-up.

## Problem

The agent can answer with markdown, KaTeX, mermaid, `quiz` blocks, matplotlib plots
and generated images, but it cannot show "a working thing": a tip calculator, a
recipe card with an ingredient checklist, an interactive chart, a small game. Typed
fenced blocks (the `quiz` pattern) need one hand-built component per use case; the
goal here is flexibility - arbitrary HTML/JS - while keeping the result looking like
part of Moneypenny in both themes, on desktop and mobile.

## Goal and success criteria

The agent creates and revises sandboxed HTML/JS artifacts that render inline in the
reply, styled by a design system it is given, and able to talk back to the chat.

- An artifact built from bare HTML plus design-system classes looks native in the
  light and dark themes, with no hex colours or fixed sizes in the agent's output.
- The same artifact works on desktop and mobile (below the 768px breakpoint) and on
  every device of the user, with layout driven by the frame's own width.
- The frame cannot reach the network, the app's origin, cookies or storage, cannot
  navigate the top page, and cannot send a message without a user gesture.
- Revisions are new versions of the same artifact, made by find/replace edits, not
  full rewrites.
- Ticked items and other artifact state survive a reload and show on other devices.
- Streaming and batch modes render artifacts identically.
- Evals: the agent makes an artifact for "tip calculator" / "recipe for X", does not
  for a factual question, edits with `update_artifact` instead of recreating, and
  uses design-system classes and tokens instead of hex colours and fixed widths.

## Non-goals (v1)

- Side panel (TODO).
- The agent reading artifact state (TODO).
- Web components with behaviour (`<mp-chart>` etc.) - TODO, driven by observed use.
- Bundled JS libraries (charts etc.) - inline SVG covers v1.
- Images other than inline SVG and `data:` URIs (TODO: conversation images via
  parent-resolved `blob:` URLs, then safe remote images).
- Outbound network or CDN scripts from artifacts.
- Artifacts from autonomous agents.
- Conversation search over artifact titles (the reply text names what was built).
- Live state sync between two devices showing the same artifact at the same time.

## Decisions

| Question | Decision |
|----------|----------|
| Reach beyond the frame | Self-contained + a `postMessage` bridge to the chat; no network |
| Revisions | Versions of one artifact (stable id); old messages keep their version with a "newer below" badge |
| State | Per-artifact JSON via the bridge, stored server-side, synced across devices |
| Design system | Tokens + styled base elements + ~15 utility/component classes |
| Production mechanism | Tool calls + an `artifacts` table; the message lists `{id, version}` |
| Placement | Inline, below the message text, in tool-call order |
| Sizing | Measured per device, never stored on the artifact; fluid layouts only |

## Architecture

### Frame

One static route, `GET /artifact-frame`, serves a shell page identical for every
artifact: the design-system CSS, the bridge script and a loader. Its response carries
its own CSP header (the app CSP is not applied to it):

```
sandbox allow-scripts; default-src 'none'; script-src 'self' 'unsafe-inline';
style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:;
connect-src 'none'; form-action 'none'; base-uri 'none'
```

The chat embeds it as `<iframe sandbox="allow-scripts" src="/artifact-frame">`
(opaque origin: no app cookies, storage or DOM). After the shell posts `ready`, the
parent sends `init {html, theme, state}`. The shell's own document stays in
place (no `document.open`, so the bridge's listeners survive): the loader parses the
agent's HTML with `DOMParser` (a fragment or a full document), moves its `<style>` /
`<link>` head nodes and body nodes into the live document, then re-creates each
`<script>` in document order - an external one is awaited (`load`/`error`) before the
next runs, so an inline script that uses an earlier external one works - and
finally dispatches synthetic `DOMContentLoaded` and `load` events for agent code that
waits for them. The shell is a Vite entry (`web/src/artifact/frame.ts`), rendered
by a Flask template from the manifest like `index.html`. The frame never fetches user data and
needs no authentication (the app authenticates with a JWT header, which an iframe
navigation could not carry anyway); the shell is cacheable. The app CSP gains
`frame-src 'self'`; the frame route overrides the app-wide `X-Frame-Options: DENY`
and `frame-ancestors 'none'` with `SAMEORIGIN` / `frame-ancestors 'self'`. In dev
mode its CSP also allows the Vite dev server (`http://localhost:5173`, `ws:`) so the
frame entry loads with HMR.

No bundled libraries in v1: graphics and charts are inline SVG (the agent writes
them well, and they theme through `currentColor` and the tokens). Opt-in libraries
served from our origin (`script-src 'self'`) can be added later without changing the
frame.

### Data model

Migration adds:

- `artifacts` - `id` (short random id), `conversation_id`, `user_id`, `title`,
  `latest_version`, `state` (JSON text, nullable), `created_at`, `updated_at`.
- `artifact_versions` - `artifact_id`, `version`, `html`, `created_by_message_id`
  (nullable until the turn is saved), `created_at`; primary key
  `(artifact_id, version)`.
- `messages.artifacts` - JSON array `[{id, version, title}]`, nullable.

Foreign keys are not enforced in this database and messages are deleted from
several places (truncate, single delete, conversation delete/purge, programs,
planner, agents), so cleanup is done by SQLite triggers in the migration:
`AFTER DELETE ON messages` deletes the versions that message created;
`AFTER DELETE ON artifact_versions` recomputes `latest_version` and deletes an
artifact left with no versions; `AFTER DELETE ON conversations` deletes its
artifacts and their versions.

SQL lives in `src/db/models/artifacts.py`.

### Agent tools

`src/agent/tools/artifacts.py`:

- `create_artifact(title, html)` - validates size (`ARTIFACT_MAX_BYTES`) and the
  per-conversation count (`ARTIFACT_MAX_PER_CONVERSATION`), writes the artifact and
  version 1 immediately (so later calls in the same turn can reference the id), and
  returns `{id, version, title}`. The `_full_result` carries the same for the save
  path.
- `update_artifact(id, edits | html)` - `edits` is a list of `{find, replace}`
  applied in order, each `find` required to match exactly once; a miss or an
  ambiguous match fails with a short excerpt around the nearest match so the model
  can retry. `html` replaces the whole document. Writes version n+1.
- `read_artifact(id)` - returns the latest HTML and version. Tool calls are not
  replayed across turns (history is text + MSG_CONTEXT), so editing an artifact from
  an earlier turn reads it first; the tool description says so.

All three check that the artifact belongs to the current conversation. They pass the
three availability layers (binding, `check_tool_permission`, contextvar forwarding -
docs/features/agent-tools.md) and are not in `ALWAYS_SAFE_TOOLS`; they are not bound
for autonomous agents.

### Saving a turn

The tools' LLM-visible result carries `"artifact": {id, version, title}` (nothing
needs `_full_result`). `save_message_to_db()` (stream and batch) reads those from the
turn's `ToolMessage`s in `result_messages`, stores them in `messages.artifacts`, and
sets `created_by_message_id` on those versions. MSG_CONTEXT for that message gains
`artifacts: [{id, v, title}]`.

The tools are bound in regular chats (including anonymous ones - artifacts are
conversation data, not user memory) and not in sports/language programs, which trim
tool declarations for tokens.

### Streaming and batch

- While a tool runs, the existing tool-status line shows "Building an artifact".
- On completion `stream_events` turns the tool's result into a new SSE event
  `artifact {id, version, title}` that places the frame. It
  joins `_JOURNALED_EVENT_TYPES`, so a resumed stream shows it; the streaming data
  flow's components are updated together (see docs/features/chat-and-streaming.md).
- Batch responses and message payloads carry `artifacts: [{id, version, title}]`.

### API

`src/api/routes/artifacts.py`, schemas in `src/api/schemas/artifacts.py`, all
ownership-checked through the conversation:

- `GET /api/artifacts/<id>/versions/<v>` - `{html, title, version, state}`.
- `PUT /api/artifacts/<id>/state` - JSON body up to `ARTIFACT_STATE_MAX_BYTES`. The
  version GET returns the current state too, so every render (any device, any
  reload) starts from the latest saved state. Live updates while two devices show
  the same artifact at once are out of scope.

### Client

`web/src/components/messages/artifact-frame.ts` (rendering) and
`web/src/core/artifact-bridge.ts` (message handling), `web/src/api/artifacts.ts`.

- Each `{id, version}` on a message renders a frame below the text, in order, with a
  title row. When a later message in the store holds the same artifact at a higher
  version, a badge "v{n} · newer below" jumps to it (computed client-side, so a
  version from a failed or deleted turn never produces a dead link).
- Re-decorating a message (stream `artifact` event, then `done`, then re-renders)
  keeps a live frame keyed by `id@version` instead of reloading it.
- The parent fetches the version's HTML and state and sends `init`.
- Theme changes are pushed to every live frame (a `MutationObserver` on the root's
  `data-theme`, so no coupling to the settings code).

## Bridge

Global `mp` inside the frame, `postMessage` only:

- `mp.send(text)` - sends `text` as the user's next message through `sendUiMessage`
  (outbox, steering and sync rules apply). The shell only forwards it while
  `navigator.userActivation.isActive`, so scripts cannot post messages unprompted.
- `mp.state.get()` / `mp.state.set(obj)` - per-artifact JSON (shared across
  versions, so an edit keeps ticked items). The parent debounces writes
  (`ARTIFACT_STATE_SAVE_DEBOUNCE_MS`) and PUTs them.
- `mp.theme` and an `mp:theme` event; the shell sets `data-theme` on its `<html>`.
- Automatic, no agent involvement:
  - height reports from a `ResizeObserver` on the document;
  - `console.error` and uncaught errors forwarded to the parent (badge + log);
  - link clicks intercepted and forwarded; the parent opens only `https:` URLs in a
    new tab, after a user gesture.

Origin checks: the parent accepts only messages whose `event.source` is a frame it
created (frames are opaque-origin, so `event.origin` is `"null"` and is not used);
the shell accepts only the first `init` from `window.parent` and later messages from
the same source.

## Design system

`web/src/artifact/design-system.css` imports `web/src/styles/variables.css` and
defines the `--mp-*` tokens as aliases of the app's tokens (`--mp-accent:
var(--color-brand-500)` …), so the brand cannot drift and both themes come for free
(the frame's `<html>` gets the same `data-theme` as the app):

- **Tokens** for both themes: `--mp-bg`, `--mp-surface`, `--mp-surface-2`,
  `--mp-text`, `--mp-muted`, `--mp-accent`, `--mp-accent-text`, `--mp-border`,
  `--mp-success`, `--mp-warning`, `--mp-error`, `--mp-radius`, spacing scale
  `--mp-space-1..6`, type scale `--mp-text-xs..2xl`. The frame background is
  transparent so it sits on the assistant bubble.
- **Base elements** look native bare: `body`, `h1`-`h3`, `p`, `a`, `button`
  (primary; `.secondary`), `input`, `select`, `input[type=range]`, `table`, lists,
  `code`/`pre`, SVG defaulting to `currentColor`.
- **Classes**: `.mp-card`, `.mp-hero`, `.mp-grid`, `.mp-stack`, `.mp-row`,
  `.mp-stat`, `.mp-chip`, `.mp-checklist`, `.mp-steps`, `.mp-tabs` (CSS-only, radio
  based), `.mp-divider`, `.mp-muted`, `.mp-accent`.

### Prompt guide

`src/agent/prompt_texts/artifacts.py` (~400 tokens), used as the `create_artifact`
tool description (the deep-research pattern), so it costs nothing where the tool is
not bound: when to use an artifact (interactive or visual and worth more than
markdown; never for plain text, lists or tables), the class list with a short
example, colours via tokens or `currentColor` only, inline SVG for graphics, the `mp`
API, and the sizing rules below.

## Sizing across devices

- Nothing about size is stored on the artifact; each device measures its own render.
- The frame is always 100% of the message column width; no fixed widths anywhere.
- The design system uses container queries on the frame width: `.mp-grid` and
  `.mp-row` stack below a 480px container width (a CSS value in the design-system
  file, not a TS constant), type scale and padding step
  down slightly - so an artifact reflows the same on a phone, a narrow desktop
  window or a future side panel.
- The prompt guide's hard rule: fluid layouts only (`%`, `fr`, `minmax`), SVG with a
  `viewBox` and `width="100%"`, no fixed widths or heights.
- Height comes from the bridge, capped at `ARTIFACT_MAX_HEIGHT_VH` with scrolling
  inside the frame beyond it. Rotation and window resizes re-measure through the
  same `ResizeObserver`.
- Scroll stability: a per-device cache in `localStorage` (try/catch; a miss means a
  short placeholder height) keyed by `artifact@version` and a frame-width bucket
  reserves the height before the first report. Growth after the first report is
  applied only when the user is not actively scrolling (docs/ui scroll rules; check
  on an iOS device with the kbdebug overlay).

## Lifecycle

- Artifacts follow their conversation through trash and restore (trash is a flag
  on the conversation) and are deleted with it on purge (trigger).
- Regenerate / edit-and-resend delete a message: versions it created are deleted;
  an artifact left with no versions is deleted; `latest_version` is recomputed
  (triggers).
- Copy on a message appends `[Artifact: {title}]` per artifact.
- A stopped turn keeps artifacts already created (same as files).

## Error handling

- Tool errors (size, count, failed edit, unknown id) return error results through
  the existing `check_tool_results` retry path.
- Frame not `ready` within `ARTIFACT_READY_TIMEOUT_MS`, or the HTML fetch fails: a
  card with the title, "Couldn't display", Retry and "View source".
- Forwarded runtime errors show a small badge; the frame keeps running.
- State PUT failures retry on the next change; the last state is kept in memory.

## Configuration

`src/config.py` (with `.env.example` and the feature doc): `ARTIFACTS_ENABLED`,
`ARTIFACT_MAX_BYTES`, `ARTIFACT_STATE_MAX_BYTES`, `ARTIFACT_MAX_PER_CONVERSATION`.
`web/src/config.ts`: `ARTIFACT_MAX_HEIGHT_VH`, `ARTIFACT_READY_TIMEOUT_MS`,
`ARTIFACT_STATE_SAVE_DEBOUNCE_MS`.

## Testing

- **Backend unit**: create/update/read (find/replace exact-once semantics, miss and
  ambiguous excerpts, whole-html replace), size and count limits, ownership, frame
  route CSP header, state GET/PUT limits, lifecycle cascades and version cleanup.
- **Migration triggers**: deleting a message, a version or a conversation leaves no
  orphans and the right `latest_version`.
- **Integration**: save path fills `messages.artifacts` and `created_by_message_id`,
  SSE `artifact` event and journal resume, batch parity, MSG_CONTEXT contents.
- **Web unit**: bridge source checks, `mp.send` gesture gate, height cap and cache,
  theme push, link forwarding (`https:` only), loader script ordering, every
  `--mp-*` token resolves to an app token.
- **E2E** (desktop and mobile): renders, theme toggle reaches the frame, an
  `mp.send` button posts a message, state survives reload, version badge jumps,
  `fetch()` from the frame fails.
- **Visual**: a fixture artifact using the full class set, both themes, desktop and
  mobile (`/regen-baselines`).
- **Evals**: artifact for "tip calculator" and "recipe for X"; none for a factual
  question; `update_artifact` for a revision; no hex colours or fixed widths.

## TODO entries (added in the implementing commit)

- The agent reads artifact state ("what's left on my list?").
- Web components with behaviour, based on observed artifact use.
- Conversation images in artifacts, then safe remote images (e.g. server-inlined
  images from pages the agent read).
- Side panel for artifacts.
