# Inline Artifacts

The agent can answer with "a working thing": a small HTML/CSS/JS page (tip
calculator, recipe card with an ingredient checklist, tracker, inline-SVG chart,
small game) rendered in a sandboxed frame under its reply. A design system makes
bare HTML look like Moneypenny in both themes; a `postMessage` bridge lets the
artifact send a message, save state and follow the theme. Revisions are new
versions of the same artifact, made by find/replace edits.

Design: [inline artifacts spec](../superpowers/specs/2026-10-11-inline-artifacts-design.md).
Where the code and the spec differ, the code wins; the differences are noted below.

## The flow

1. **Tool.** `create_artifact(title, html)` or `update_artifact(artifact_id,
   edits | html, title)` ([tools/artifacts.py](../../src/agent/tools/artifacts.py))
   writes a version to the database at once, so later calls in the same turn can
   use the id. `read_artifact(artifact_id)` returns the latest HTML (tool calls
   are not replayed across turns, so editing an earlier turn's artifact reads it
   first; the `update_artifact` docstring says so).
2. **LLM-visible ref.** The tool result JSON carries
   `"artifact": {id, version, title}`. Nothing rides in `_full_result` (see
   [Pitfalls](#pitfalls)).
3. **`artifact` SSE event.** `StreamEventProcessor` in
   [stream_events.py](../../src/agent/stream_events.py) turns a successful
   create/update result into `{"type": "artifact", id, version, title}` via
   `artifact_ref_from_tool_content()` ([artifact_refs.py](../../src/agent/artifact_refs.py)).
   It is in `FORWARDED_EVENT_TYPES` and `_JOURNALED_EVENT_TYPES`, so a resumed
   stream shows it.
4. **`messages.artifacts`.** `save_message_to_db()` (stream and batch) calls
   `extract_artifact_refs()` on the turn's `ToolMessage`s (an artifact changed
   twice keeps its last version at its first position), stores the list on the
   reply and calls `db.link_artifact_versions()` to set `created_by_message_id`.
   `add_artifacts()` ([api/utils.py](../../src/api/utils.py)) puts `artifacts`
   on loaded messages, the batch response, the live `done` and the resume
   `done`. MSG_CONTEXT gains `artifacts: "<id> v<n> '<title>'; ..."`
   ([history.py](../../src/agent/history.py)), which is how the next turn finds
   the id.
5. **Client card.** The stream's `artifact` event calls `addLiveArtifact()`, and
   `done` / history renders call `decorateArtifacts()`
   ([components/messages/artifacts.ts](../../web/src/components/messages/artifacts.ts)).
   Decorating is idempotent by `id@version`, so the live frame survives the
   `done` and later re-renders.
6. **Sandboxed frame.** Each card holds
   `<iframe sandbox="allow-scripts" src="/artifact-frame?theme=...">`. The shell
   page is the same for every artifact and never fetches user data.
7. **`postMessage` init.** The frame posts `mp:ready`;
   [artifact-host.ts](../../web/src/core/artifact-host.ts) fetches
   `GET /api/artifacts/<id>/versions/<v>` (`{id, version, title, html, state}`)
   with the user's token and posts `mp:init {html, theme, state}`. The frame's
   loader ([loader.ts](../../web/src/artifact/loader.ts)) moves the HTML into the
   live document, re-creates each `<script>` in order (external ones awaited),
   then dispatches synthetic `DOMContentLoaded` and `load`, and posts
   `mp:rendered`.

While a tool runs, the tool-status line shows "Building an artifact" /
"Updating the artifact" (`TOOL_METADATA` in
[tool_display.py](../../src/agent/tool_display.py)); the pill's detail is the
title.

## Frame security model

`GET /artifact-frame` (`artifact_frame()` in [app.py](../../src/app.py), template
[artifact-frame.html](../../src/templates/artifact-frame.html), Vite entry
[frame.ts](../../web/src/artifact/frame.ts)) sends its own headers; the app-wide
ones use `setdefault`, so these win:

- `X-Frame-Options: SAMEORIGIN`, `Cache-Control: no-cache`.
- `Content-Security-Policy` from `build_frame_csp(dev_mode, origin)`:

```
sandbox allow-scripts; default-src 'none'; script-src 'self' {origin} 'unsafe-inline';
style-src 'self' {origin} 'unsafe-inline'; img-src 'self' {origin} data: blob:;
font-src 'self' {origin} data:; connect-src 'none'; form-action 'none';
base-uri 'none'; frame-ancestors 'self'
```

`{origin}` is the app's own origin, `request.scheme://request.host` (behind the
reverse proxy `ProxyFix` makes it the public one). It sits next to `'self'`
because WebKit matches nothing against `'self'` in an opaque-origin sandbox, so
Safari loaded a blank frame. Dev mode adds the Vite dev server to `script-src` /
`style-src` and its websocket to `connect-src` (`_FRAME_CSP_DEV_EXTRAS`).

What this gives: an opaque origin (no app cookies, storage or DOM), no network
(`connect-src 'none'`, images only `data:` / `blob:` / app assets), no forms, no
top navigation, and only the app can embed the frame. The app CSP gained
`frame-src ... 'self'`. Inline scripts are allowed because they are the
artifact's own code. Built assets under `/static/assets/` send
`Access-Control-Allow-Origin: *` (public hashed bundles); the API still sends no
CORS headers.

The host trusts a message only by `event.source` (a frame it created); the
frame's origin is `"null"` and says nothing. The frame listens only to
`window.parent` and applies only the first `mp:init` (`mp:theme` any time). It posts with target
`'*'` (the only target an opaque frame can use; `frame-ancestors 'self'` limits
who receives it).

## Bridge

The global `mp` inside the frame ([bridge-client.ts](../../web/src/artifact/bridge-client.ts)):

- `mp.send(text)` posts `mp:send`; the host sends it through `sendUiMessage()`
  (outbox and sync rules apply), trimmed to `ARTIFACT_SEND_MAX_CHARS`, but only
  when the user just acted IN THIS FRAME: the iframe is the parent's
  `document.activeElement` (a click into a frame focuses it) and the parent's
  `navigator.userActivation.isActive` (a click inside a frame activates its
  ancestors; focus alone where the API is missing). At most one send per
  `ARTIFACT_SEND_MIN_INTERVAL_MS`. `mp:link` passes the same gate. The frame's
  own check in `mp.send` is only a convenience: artifact code shares the
  frame's realm and can post `mp:send` itself, so the host decides.
- `mp.state.get()` (a promise, resolved after init) / `mp.state.set(obj)`: JSON
  per artifact, shared by all its versions (an edit keeps ticked items). The host
  debounces writes (`ARTIFACT_STATE_SAVE_DEBOUNCE_MS`) and PUTs
  `/api/artifacts/<id>/state` (limit `ARTIFACT_STATE_MAX_BYTES`, 413 above it).
  A failed save is logged; the next change retries.
- `mp.theme` (`'light' | 'dark'`) and a window `mp:theme` event; the frame sets
  `data-theme` on its `<html>`. The host's `observeTheme()` watches the app
  root's `data-theme` with a `MutationObserver` and pushes `mp:theme`.
- Automatic, no agent code needed: height reports from a `ResizeObserver` on the
  document; uncaught errors, rejections and `console.error` forwarded as
  `mp:error` (the card shows an "Artifact error" badge, the frame keeps
  running); link clicks held back and forwarded as `mp:link`, which the host
  opens in a new tab only for `https:` URLs.

Message types ([protocol.ts](../../web/src/artifact/protocol.ts), shared by both
sides; `isFromFrame()` / `isToFrame()` drop anything else):

| Direction | Types |
|---|---|
| chat -> frame (`ToFrame`) | `mp:init {html, theme, state}`, `mp:theme {theme}` |
| frame -> chat (`FromFrame`) | `mp:ready`, `mp:rendered`, `mp:height {height}`, `mp:send {text}`, `mp:state {state}`, `mp:link {href}`, `mp:error {message}` |

A frame that is not ready within `ARTIFACT_READY_TIMEOUT_MS`, or whose version
fetch fails, shows "Couldn't display" with Retry. "View source" opens the HTML as
`text/plain` in a new tab (the spec's modal could not show long HTML).

## Design system

[design-system.css](../../web/src/artifact/design-system.css) (loaded with the
app fonts, Inter and Bricolage Grotesque) imports
[variables.css](../../web/src/styles/variables.css) and defines the `--mp-*`
tokens as aliases of the app tokens (`--mp-accent: var(--accent)`, ...), so the
brand cannot drift and both themes come for free. It has no hex colours of its
own.

- **Tokens**: `--mp-bg`, `--mp-surface`, `--mp-surface-2`, `--mp-text`,
  `--mp-muted`, `--mp-accent`, `--mp-accent-text`, `--mp-accent-soft`,
  `--mp-border`, `--mp-border-strong`, `--mp-success`, `--mp-warning`,
  `--mp-error`, `--mp-radius(-sm)`, `--mp-space-1..6`, `--mp-text-xs..2xl`,
  fonts, shadow, motion. The frame background is transparent over the bubble.
- **Base elements** styled bare: `body`, `h1`-`h3`, `p`, `a`, `button`
  (primary; `.secondary`), `input`, `select`, `input[type=range]`, `table`,
  lists, `code` / `pre`.
- **Classes**: `.mp-stack`, `.mp-row`, `.mp-grid`, `.mp-divider`, `.mp-card`,
  `.mp-hero`, `.mp-stat`, `.mp-chip`, `.mp-checklist`, `.mp-steps`, `.mp-tabs`
  (CSS-only radio + label pairs, then one `.mp-tab-panel` per tab, up to 5),
  `.mp-muted`, `.mp-accent`.
- **Narrow frames**: `body` is an inline-size container; below a 480px
  container width `.mp-row` and `.mp-grid` stack and card padding and headings
  step down. Layout follows the frame's width, not the screen.

The agent learns all this from `CREATE_ARTIFACT_DESCRIPTION`
([prompt_texts/artifacts.py](../../src/agent/prompt_texts/artifacts.py)), the
tool's description (so it costs nothing where the tool is not bound): when to
build one (never for plain answers, lists or tables; a recipe is always a card),
the class list, colours only via tokens or `currentColor`, fluid sizing only,
SVG with `viewBox` and `width="100%"`, the `mp` API and an example. **The class
and token list in the guide must match the CSS**:
[artifact-design-system.test.ts](../../web/tests/unit/artifact-design-system.test.ts)
fails on a class or token the guide names that the CSS lacks, on an `--mp-*`
token that is not an app token, and on a hex colour.

## Sizing across devices

- Nothing about size is stored server-side; each device measures its own render.
  The frame is 100% of the message column wide.
- Height comes from the frame's `mp:height`, capped at `ARTIFACT_MAX_HEIGHT_VH`
  (80% of the viewport); taller artifacts scroll inside the frame. Rotation and
  resizes re-measure through the same `ResizeObserver`.
- A per-device cache in `localStorage` (`artifact-heights`,
  [artifact-height.ts](../../web/src/core/artifact-height.ts)) keyed by
  `id@version:<width bucket>` (`ARTIFACT_HEIGHT_WIDTH_BUCKET_PX`) reserves the
  height before the first report, so a reload does not jolt; a miss reserves
  `ARTIFACT_PLACEHOLDER_HEIGHT_PX`. The oldest entries beyond
  `ARTIFACT_HEIGHT_CACHE_MAX_ENTRIES` are dropped; storage errors are ignored.
- Scroll compensation: when a frame entirely above the viewport changes height,
  `applyHeight()` moves `#messages`' `scrollTop` by the difference. Growth of a
  visible or lower frame is applied as is (the spec's "defer while scrolling"
  was dropped; see [Scroll Behavior](../ui/scroll-behavior.md)).

## Lifecycle and versions

Migration [0065_add_artifacts.py](../../migrations/0065_add_artifacts.py) adds
`artifacts` (`id`, `conversation_id`, `user_id`, `title`, `latest_version`,
`state`, timestamps), `artifact_versions` (`artifact_id`, `version`, `html`,
`created_by_message_id`, `created_at`; PK `(artifact_id, version)`) and
`messages.artifacts`. SQL lives in
[db/models/artifacts.py](../../src/db/models/artifacts.py); ids are
`secrets.token_urlsafe`. Cleanup is by trigger, since foreign keys are not
enforced and messages are deleted from many places:

- `artifact_versions_message_delete`: a deleted message takes the versions it
  created (regenerate, edit-and-resend, truncate).
- `artifacts_version_delete`: an artifact left with no versions is deleted;
  otherwise `latest_version` is recomputed.
- `artifacts_conversation_delete`: a purged conversation takes its artifacts
  and versions. Trash is a flag, so artifacts follow it through restore.

A stopped turn keeps the artifacts already created. State belongs to the
artifact, so every version and every device starts from the latest saved state;
two devices showing the same artifact at once do not sync live. When a later
card in the DOM shows a higher version of the same artifact, the older card gets
a "v{n} · newer below" badge that flashes the newer card (computed at click
time, so a deleted turn never leaves a dead link). Copying a message appends
`[Artifact: <title>]` per card (`artifactCopyText()`).

Ownership: the tools accept only artifacts of the current conversation
(`_own_artifact()`); the routes ([routes/artifacts.py](../../src/api/routes/artifacts.py))
go through `db.get_artifact_for_user()` and answer 404 otherwise.

## Tool binding

- Bound in regular chats, including anonymous ones (artifacts are conversation
  data, not user memory), behind `ARTIFACTS_ENABLED` (`get_available_tools()` in
  [tools/\_\_init\_\_.py](../../src/agent/tools/__init__.py)).
- Not in sports or language programs (`_SPORTS_EXCLUDED_TOOLS`, inherited by
  `_LANGUAGE_EXCLUDED_TOOLS`): they answer in text and trim declarations for
  tokens.
- Never for autonomous agents: the three tools are in `_NON_PERMISSIONED_TOOLS`
  (agent output is push and digest text), so the agent editor does not offer
  them. See [Agent Tools](agent-tools.md#three-layers-decide-tool-availability).
- `update_artifact.edits` is typed `list[ArtifactEdit]` (Pydantic), not
  `list[dict]`: untyped nested parameters can break Gemini's schema conversion.
  Each `find` must match exactly once; a miss or an ambiguous match fails with
  an excerpt near the closest match so the model can retry through
  `check_tool_results`.

## Configuration

| Config (`src/config.py`) | Default | Purpose |
|---|---|---|
| `ARTIFACTS_ENABLED` | `true` | Binds the three tools (existing artifacts still render) |
| `ARTIFACT_MAX_BYTES` | `200000` | One version's HTML (it is output tokens per edit) |
| `ARTIFACT_STATE_MAX_BYTES` | `50000` | State saved through the bridge |
| `ARTIFACT_MAX_PER_CONVERSATION` | `30` | Past this, the agent must update an existing artifact |

Client constants in [config.ts](../../web/src/config.ts):

| Constant | Value | Purpose |
|---|---|---|
| `ARTIFACT_MAX_HEIGHT_VH` | `80` | Tallest frame; taller content scrolls inside |
| `ARTIFACT_READY_TIMEOUT_MS` | `5000` | No `mp:ready` by then: the failed card |
| `ARTIFACT_STATE_SAVE_DEBOUNCE_MS` | `400` | Quick `mp.state.set` calls save once |
| `ARTIFACT_PLACEHOLDER_HEIGHT_PX` | `160` | Reserved height without a cached one |
| `ARTIFACT_SEND_MAX_CHARS` | `2000` | Longest `mp.send` text |
| `ARTIFACT_SEND_MIN_INTERVAL_MS` | `1500` | One artifact send per click burst |
| `ARTIFACT_HEIGHT_WIDTH_BUCKET_PX` | `80` | Frame widths sharing a cached height |
| `ARTIFACT_HEIGHT_CACHE_MAX_ENTRIES` | `200` | Cached heights kept per device |

## Testing

- **Backend unit**: [test_artifact_tools.py](../../tests/unit/test_artifact_tools.py)
  (edits, limits, ownership, schema),
  [test_artifacts_storage.py](../../tests/unit/test_artifacts_storage.py)
  (storage and triggers),
  [test_message_artifacts_storage.py](../../tests/unit/test_message_artifacts_storage.py),
  [test_artifact_refs.py](../../tests/unit/test_artifact_refs.py),
  [test_artifact_stream_events.py](../../tests/unit/test_artifact_stream_events.py).
- **Integration**: [test_chat_artifacts.py](../../tests/integration/test_chat_artifacts.py)
  (forwarded + journaled, stream save, batch parity, MSG_CONTEXT),
  [test_routes_artifacts.py](../../tests/integration/test_routes_artifacts.py),
  [test_artifact_frame_route.py](../../tests/integration/test_artifact_frame_route.py)
  (exact CSP, headers, asset CORS, theme).
- **Web unit / component**: [artifact-host.test.ts](../../web/tests/unit/artifact-host.test.ts),
  [artifact-bridge-client.test.ts](../../web/tests/unit/artifact-bridge-client.test.ts),
  [artifact-loader.test.ts](../../web/tests/unit/artifact-loader.test.ts),
  [artifact-height.test.ts](../../web/tests/unit/artifact-height.test.ts),
  [artifact-design-system.test.ts](../../web/tests/unit/artifact-design-system.test.ts),
  [artifacts.test.ts](../../web/tests/component/artifacts.test.ts).
- **E2E**: [artifacts.spec.ts](../../web/tests/e2e/chat/artifacts.spec.ts). The
  E2E server's `POST /test/set-artifact` makes the next streamed turn run the
  real tool: `{title, html}` creates one, `{html, update: true}` adds a version
  to the last one (streamed mock only; batch parity is the integration test).
  Covers sizing, no network, theme, `mp.send`, state across reload, the
  "newer below" badge, error badge, stacking on narrow frames.
- **Visual**: [artifacts.visual.ts](../../web/tests/visual/artifacts.visual.ts)
  renders [artifact-kitchen-sink.html](../../web/tests/fixtures/artifact-kitchen-sink.html)
  (every class) in both themes, desktop and mobile.
- **Evals** ([Evals](../testing/evals.md)): `artifact_calculator` and
  `artifact_recipe` (`required_tools: [create_artifact]`, plus
  `forbidden_arg_patterns` on `create_artifact.html` for hex colours, fixed
  widths and URLs: the judge never sees tool args), `artifact_not_for_facts`
  (no artifact for a population question), `artifact_revision` (a seeded
  artifact; `update_artifact`, not `create_artifact`). Oct 11 2026: passing
  after the "a recipe is always a card" guide line; four artifact runs cost $0.58.

## Pitfalls

- **`srcdoc` frames inherit the parent's CSP**, so the frame needs its own route
  with its own policy; the app CSP (`frame-ancestors 'none'`, no inline scripts)
  would break it.
- **The app's JWT header cannot reach an iframe navigation**, so the frame never
  fetches user data: the chat fetches the version and posts the HTML in.
- **The opaque `"null"` origin makes the frame's own module script and fonts
  CORS fetches**, hence `Access-Control-Allow-Origin: *` on `/static/assets/*`.
  In E2E, Playwright's `X-Test-Execution-Id` header turns those into preflights,
  so the E2E server allows that header on asset responses (production sends no
  custom header and sees no preflight).
- **WebKit matches nothing against `'self'` in an opaque-origin sandbox**: the
  frame CSP names the app origin explicitly, or Safari shows blank frames.
- **History renders a message before appending it**, so a frame registered then
  has no `contentWindow`. The host keys frames by element and matches
  `event.source` per message; keying by `contentWindow` lost the init after a
  reload.
- **An iframe whose `color-scheme` differs from its page gets an opaque backdrop
  in Chrome** (black behind the transparent artifact). The starting theme rides
  on the frame URL (`?theme=`; the template sets `data-theme="light"` for it) and
  `applyFrameTheme()` sets an inline `color-scheme` on the iframe.
- **jsdom does not load external scripts**: `loadArtifact()` takes an injectable
  `ScriptRunner`; ordering is unit-tested with a fake runner and real execution
  in E2E.
- **Streamed `ToolMessage`s lack `_full_result`**, so the artifact ref lives in
  the tool's visible JSON; anything the save path needs must be there.
- **Foreign keys are not enforced**, hence the triggers; any new artifact-linked
  table needs its own cleanup trigger.
- **Never trust a gesture check inside the frame**, and `isActive` alone is not
  enough: a click on the chat's Send button keeps the page "active" for
  seconds, long enough for a fresh artifact to post `mp:send` on load. The host
  also requires the frame to be focused (E2E: "artifact code cannot send a
  message without a click").
- **`mp.send` during an active reply is refused**: `sendUiMessage()` shows
  "Please wait for the current response to finish." and returns false.
- **A new SSE event joins `_JOURNALED_EVENT_TYPES` and `FORWARDED_EVENT_TYPES`,
  and the resume `done` calls `add_artifacts()`**, or frames vanish on resume
  (see [Chat and Streaming](chat-and-streaming.md#resumable-streams)).

## See Also

- [Agent Tools](agent-tools.md) - binding, permissions, `_NON_PERMISSIONED_TOOLS`
- [Chat and Streaming](chat-and-streaming.md) - the `artifact` event, resume
- [UI Features](ui-features.md) - inline artifact cards
- [Design System](../ui/design-system.md) - the app tokens the `--mp-*` ones alias
- [Database](../architecture/database.md) - tables and triggers
- [Evals](../testing/evals.md) - `forbidden_arg_patterns`, `artifacts:` seeding
