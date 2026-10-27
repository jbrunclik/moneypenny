# E2E Reliability

How to tell load-induced E2E failures from real regressions, and the races found and fixed while taking CI from retry-dependent to first-run green. Read this before theorizing about a red E2E run.

## Known transient failure signature (starved runner)

There is one recurring E2E failure pattern that is NOT a code regression
(observed 4x on CI + locally through Aug 2026): a **batch of unrelated
tests failing together, most timing out at exactly the 30s test timeout or
a 20s `waitForSelector`**, including trivial tests (e.g. "rejects empty
name") — while the same commit passes locally and adjacent commits with a
superset of the changes pass on CI. Cause: the runner/mock-server being
starved under full-suite load; timing-sensitive scroll tests fail first.

How to tell it apart from a real regression (zero-tolerance still applies):
1. The failing set is broad and unrelated to the diff (a real regression
   fails a focused cluster).
2. Failures are timeouts waiting for mock-server responses, not assertion
   mismatches — check WHERE it died (`--log-failed`): before the feature
   assertion = infrastructure, at the assertion = investigate the code.
3. Re-run the failing test with `--repeat-each=3` in isolation; the
   transient passes deterministically.
4. A superset commit passing CI clears the suspect change.

If the pattern recurs frequently, the fix direction is runner resourcing
(e.g. sharding the E2E job), not test code.

## Visual flakes are state races, not pixel noise

When a visual test passes only on retry, diff the `expected`/`actual`
attachments in the Playwright report: the difference is almost always a
whole UI element in a different state, and the fix belongs in the app or
the test's setup, never in the baseline. Root-caused examples (Sep 2026):

- **Deep-research progress panel: identical pixels, different anti-aliasing**
  (Oct 2026, ~40-50% WebKit failures). A finding renders BELOW the captured
  items; the bottom-pinned list then shifts the whole panel up ~54px, so
  captures on either side of its arrival sat at different sub-pixel offsets.
  WebKit also held the `started` SSE chunk until the finding arrived. Fix: wait
  for the state BOTH engines reach (the first finding in) before capturing.
  Watch for content landing below a clip in a bottom-pinned list - it moves
  the clip even though nothing inside it changed.
- **Live thinking line never seen on WebKit** (Oct 2026, CI WebKit 4/4, local
  WebKit fine). The mock sent one `thinking` event, held it, then the tokens;
  WebKit holds an SSE chunk until the next one arrives, so the thinking landed
  with the first token and the line collapsed at once. The mock now re-sends
  the (unchanged) thinking halfway through `thinking_hold_ms`. A live state
  that lasts exactly one SSE chunk is invisible on WebKit - put a later chunk
  inside the window you assert on.
- **Scroll tests must send input** (Oct 2026): since only real input counts as
  the user (see [Scroll Behavior](../ui/scroll-behavior.md#outside-forces-oct-10-2026-ios)),
  a bare `scrollTo` reads as layout - the image chase re-pinned "the user" who
  had scrolled up, depending on timing. Dispatch a `wheel` on `#messages` first.
- **Agent editor: "the Name field holds the description"** (Oct 2026, WebKit).
  Not a fill race - the editor body was scrolled by about one field (filling
  the last field scrolls it into view, settling at varying offsets), so the
  Description input sat under the Name label. Fix: blur and reset the
  scroller before capturing. When a capture looks like values swapped, check
  the scroll offset first.

- **Storage page mobile: header hidden vs visible.** `navigateToStorage`
  hides the composer; the composer `ResizeObserver` saw a bottom-pinned
  (empty) list and re-pinned it in a `requestAnimationFrame`, racing the
  page's own render + `scrollTop = 0`. Fix: re-pin only when the composer
  GROWS (`composer-height.ts`), and `programmaticScrollToBottom` no longer
  opens a "programmatic" window when nothing needs scrolling.
- **Send button disabled / new conversation missing from the sidebar.**
  Tests click New Chat as soon as `#new-chat-btn` exists, i.e. while
  `loadInitialData` still has `isLoading` set: the send-button check ran
  during loading and was never re-run, and the initial conversation list
  overwrote the local `temp-*` conversation. Both are handled in
  `loadInitialData` now.
- **Alert modal 1px bottom-edge shift** (CI only, unreproducible locally):
  bounded with `maxDiffPixels: 512` - a real regression moves thousands.

The Linux baseline regeneration artifact (`/regen-baselines`) captures
whatever state the run happened to land in, so it can carry unrelated
drift; commit only the snapshots your change actually touched.

## E2E first-run reliability (Sep 2026 pass)

The E2E job now runs **one browser project per runner** (matrix in
`test.yml`). With both projects on one 2-vCPU runner, 8 browser contexts
shared a single mock server and the suite only passed through retries -
webkit tests timing out on mock responses that were never slow in
isolation. Retries are still configured as a safety net, but the goal is
zero `flaky` in the Playwright summary; when a test needs a retry, treat
it as a bug and diff the first-attempt `error-context.md` against the code.

**CI layout (Oct 2026):** the browser jobs (E2E + visual) are gated only on
lint, so they run alongside the backend and unit suites instead of after
them. E2E browsers run inside the `mcr.microsoft.com/playwright` image like
the visual tests: `playwright install --with-deps` fetched ~100 media
packages from the runner's apt mirror, which intermittently crawled at KB/s
and hung shards until the 30-min job timeout. Python deps install with `uv`.
Playwright shards by test count in file order, so chromium runs as 2 shards
and webkit as 6 to keep the streaming-heavy slice off the critical path.

Races found and fixed in that pass (all reproduced from CI artifacts, not
by guessing):

- **Send button stuck disabled / temp conversation vanishing** - tests
  click New Chat before `loadInitialData` finishes (see the visual section
  above). Showed up in E2E as `page.click('#send-btn')` hitting the 30s
  test timeout (Playwright waits for the button to become enabled).
- **Image-load scroll yanked a reader who was at the top** - on WebKit a
  five-message chat is only ~155px scrollable, below the 200px "near
  bottom" tolerance, so scrollTop 0 still counted as "at bottom" when the
  scheduled scroll fired late. The genuine-scroll-up guard in
  `image-load-scroll.ts` now runs before that tolerance.
- **Throughput-bound assertions** - the read-from-start test streamed a
  400-line answer (2400 tokens, one DOM re-render each) and asserted
  mid-stream; it now uses a short viewport so 80 lines are "taller than the
  viewport", waits for the stream to end, and polls the position.
- **One-shot reads of async state** - `localStorage` journal cleanup read
  once right after the final render; use `expect.poll`.
- **Lazy web-font subsets** - both fonts ship as `unicode-range` subsets
  with `font-display: swap`, so a face starts loading the first time text
  uses it. A visual test injecting the first display-font heading captured
  the fallback font. The shared fixture (`global-setup.ts`) now kicks off
  `document.fonts.load()` for the faces at page load.
- **Composer stealing focus from a modal** - a send that was still settling
  re-focused `#message-input` behind an open delete confirmation (focus ring
  in the snapshot). `focusMessageInput` now no-ops while a modal is open.
- **Check-then-act on a loader** - the sidebar load-more test waited for
  the loader, then counted its dots in a second call. Hold the request with
  `page.route` (and the sync request, which delivers every conversation at
  boot) so the loading state is observable (this relies on service workers
  being blocked suite-wide - see below).
- **Runner CPU starvation, not the mock server** - the e2e-server's SLOW
  log showed `/test/reset` taking up to 12s on the webkit runner at only
  4-10 server threads (a reset is ~6ms in isolation; even `GET /` took
  3.8s). Four webkit contexts saturate a 2-vCPU runner. WebKit now runs as
  shards of two workers (six since Oct 2026); the server also prints `INFLIGHT` lines for
  requests still running after 3s. (Running the browsers under `nice` was
  tried and reverted - chromium went from 0 to 6 retries.)
- **WebKit flakes under sustained load (settled Sep 2026)** - two specs
  (`search.spec.ts`, and `deeplink.spec.ts:379` "reloading an archived
  conversation URL") failed only under parallel load and were never
  reproduced deliberately (~430 targeted executions all passed). The
  mitigation is retry budget, not a fix: the webkit project gets 3 CI
  retries vs chromium's 2 (per-project `retries` in
  `playwright.config.ts`). Thirty main-branch runs after that change
  produced zero false reds. If red E2E returns under load, the forensics
  are already in place - `SearchResults.ts` warns when the search hint
  renders while the DOM input still has text (distinguishing a lost input
  event from a cleared input), and CI retries retain traces including
  console. Pull the trace from the failed run's artifacts BEFORE
  theorizing - the earlier "stray version banner" lead was a red herring
  (see the version-banner note under E2E Stability Pitfalls).

- **Per-test context creation ran yoyo** - `Database()` on a template copy
  re-read and hashed every migration file: 6ms locally, 5-6.5s on a CI
  runner, under the context lock and holding the GIL - unrelated requests
  stalled 12s+ (`SLOW ... init=5.00` in the phase log). The e2e-server now
  patches `DatabaseBase._init_db` to a no-op once the templates exist.
- **fsync on a runner disk** - with migrations gone, the phase log moved the
  time into the handlers: a `/test/reset` is a few commits, a chat turn
  several, and under eight concurrent contexts each fsync on the GitHub
  runner's disk queued for seconds (`INFLIGHT` counts of 45-55 per shard).
  The e2e-server keeps its databases on `/dev/shm` when it exists and sets
  `PRAGMA synchronous=OFF` on every pooled connection - test data is
  disposable.
- **"Response never arrived" was a lost message, not a slow server** - the
  Playwright trace of a failing run showed the follow-up message posted to
  `/chat/interject`, not `/chat/batch`: the active-request flag stayed set
  until the post-response cost fetch finished, so a message sent in that
  window was queued into an already-finished turn and never answered. Real
  users hit this too (fast follow-up after a reply). Both send paths now
  release the active request the moment the turn ends; batch-mode.spec has
  the regression test (delays `/cost`, sends two messages back to back).
  Lesson: when a test waits for a response that "never arrives", read the
  network trace before blaming load - `--trace on` plus the request bodies
  in `trace.zip` pinpointed this in one run.
- **Archived deep-link reload** - the test waited for `.message.assistant`,
  which also matches the streaming placeholder, so on a slow run it archived
  and reloaded before the response was saved. Wait for
  `.message.assistant:not(.streaming)` when the next step depends on the
  turn being persisted (79 bare waits remain in the suite; most are in
  batch-mode tests, where no placeholder exists).
- **Smooth scroll-to-bottom fought a user scroll-up** - `scrollToBottom`'s
  animator now stops when the position moves against it (up); it keeps
  going when scroll anchoring nudges it down as content above loads, and
  retargets to the new bottom when the content height changes. A downward
  deviation must NOT count as the user: application code adjusts scrollTop
  around these animations (pagination re-anchoring, the scroll-to-bottom
  button after loading remaining messages) - "any deviation cancels" broke
  those flows on both browsers.
- **A forced click into a sidebar still sliding in** (Oct 2026, mobile.spec
  trash restore, ~1-3% under load). The test opened the mobile sidebar,
  hovered a row and force-clicked its Delete button; the trace showed hover
  reporting "stable" 130ms into the 300ms slide and the forced click landing
  where Delete was mid-slide - on the Archive button once the sidebar came to
  rest - so the confirm modal never opened. `force` skips every check at
  click time; wait for the motion to end first (`openSidebar` in
  mobile.spec waits for `#sidebar.getAnimations()` to drain, like
  `clickStop` does for the composer).
- **A test whose premise wasn't true** - conversation.spec:797 ("user scrolled
  up, image loads, don't yank") sent five one-word exchanges that on WebKit
  did not overflow the viewport, so the "scroll to the top" was a 0 -> 0
  no-op the app could not distinguish from never having scrolled. The setup
  now sends longer messages and asserts the overflow before the image step.
- **Deferred pin re-checked position, not intent** - after a reply the
  batch/streaming paths pin or jump inside a `requestAnimationFrame`, guarded
  by "did scrollTop move since?". On WebKit a five-message chat is not
  scrollable until the sixth, so the user's scroll "to the top" moved a few
  px and the late frame yanked them back (conversation.spec:797 again, only
  on loaded runners). `watchForUserScroll` now records a genuine scroll-up
  (moved up AND not at the bottom) between the insert and the frame;
  finalization clamps and scroll anchoring don't count.

- **Hold live states with a gate, not the clock** (Oct 2026,
  thinking-indicator.spec "while thinking", ~1/250 WebKit under load). The
  test tapped the live thinking line inside a fixed 4s `hold_ms`, then asserted
  the collapsed toggle "while the reply still writes" during a 1.4s reply. The
  server log showed the mock's tokens on time, yet WebKit handed the first token,
  the rest and `done` to the page in one burst 3s late, so the streaming state
  never existed for the assertion. The thinking is now held until
  `POST /test/release-thinking` (`until_released` on `/test/set-emit-thinking`)
  and the reply is far longer than the test, which ends it with Stop. Two
  related pitfalls: re-sending thinking re-renders the live line, and WebKit
  fires no click when the node pressed is replaced before release (the tap is
  lost, for real users too). The app now holds the line's updates while it is
  pressed and applies them after the tap (`holdUpdatesWhilePressed` in
  ThinkingIndicator.ts), so one tap is enough.

## E2E Gotchas (Streaming, Service Workers, Media)

- **E2E serves BUILT assets** — `make test-fe-e2e` runs `make build` first, but a
  direct `npx playwright test` does not: rebuild after every `web/src` change or you
  test the stale bundle (see also the first Stability Pitfall below).
- **Streaming outruns assertions**: the default mock stream delay is ~10ms/token,
  so the stream finishes before any mid-stream click/assertion. Specs that must
  observe streaming state set a larger delay via `POST /test/set-stream-delay`
  (per-execution-id isolated).
- **Service workers are blocked for the whole suite** (`serviceWorkers:
  'block'` in `web/playwright.config.ts`, Oct 2026). The app registers `/sw.js`
  ([src/app.py](../../src/app.py)), and with a worker active WebKit breaks the
  harness two ways: `page.route()` misses requests that pass through the
  worker (Playwright 1.64 sends even more through it - 27 webkit tests that
  mock or fail requests broke), and Playwright's WebKit has no push service,
  so the app's `pushManager.getSubscription()` on a controlled page never
  resolves (1.61) or freezes the page outright (1.64+: every webkit test timed
  out). No test exercises the worker itself; specs used to opt out one
  describe at a time.
- **Playwright-WebKit navigation stalls (upstream, Oct 2026)**: about 1 in 40
  under load, a WebKit navigation starts but never commits - `page.goto`
  waits for `load` with no request issued (microsoft/playwright#42385), and
  `pdf-viewer.spec.ts` "a chunk deleted by a deploy reloads the page" saw the
  app's own `location.reload()` fire `beforeunload` and then nothing for 29s.
  The app side was verified correct with an event log; the CI retry restarts
  the worker, which clears it. Don't chase these as app bugs. That test hits
  it most (Oct 25 2026: 1 in 10 to 1 in 40 under `--repeat-each` on a laptop):
  its trace shows the reload's document request issued with no response, and
  the server's access log shows it never arrived. A server without keep-alive
  (HTTP/1.0) stalled just as often, so it is not a reused connection.
  `settings.spec.ts` "Color Scheme" hit it in every full run on Oct 25 2026
  (1 in 21 in isolation): its `beforeEach` loaded the page only to clear an
  already-empty localStorage, then every test reloaded while the app was still
  starting - twice the navigations, half of them mid-startup. A trace again
  showed the reload's `GET /` never reaching the server (no app request
  pending it). The group now loads once per test. Keep tests to the
  navigations they assert on: a fresh context needs no clean-up load.
- **Scroll forensics**: `installScrollLog(page)` / `attachScrollLog(page,
  label)` (`web/tests/e2e/chat/fixtures.ts`) record every scroll write to
  `#messages` with its app caller (minified bundle frames - `make
  decode-stack < job.log` at the same commit maps them to source lines; a
  sourcemap build has the same chunk hashes as the tested build), scroll events no logged write explains
  (anchoring, layout shifts) and real input; attach on the failing branch only.
  Install AFTER navigation counts too: a bare `page.addInitScript` only arms
  the next navigation, which is why an earlier inline hook never logged.
- **WebKit reuses a failed module load**: after a lazy `import()` of a URL
  fails, WebKit fails the same URL again without a network request, even after
  a reload and `unroute`. A test cannot fail a chunk and then load that same
  chunk successfully.
- **Config-shrinking route mocks race app init**: after `goto`, await the config
  response (e.g. `waitForResponse('**/api/config/upload')`) before acting, or the
  store still holds defaults.
- **libmagic video detection**: production validation uses `magic.from_buffer`,
  which can return `application/octet-stream` for real video containers — hence
  the `_matches_video_signature()` fallback in
  [src/utils/files.py](../../src/utils/files.py). Hand-crafted `ftyp` headers are
  not enough; use real (tiny, ffmpeg-generated) fixtures under `tests/fixtures/`.
- **Swipe actions need `(hover: none)`**: sidebar swipe actions only render under the
  `(hover: none)` media query, so desktop Chromium at a 375px mobile viewport never shows
  them. Mobile-viewport specs there use the hover row actions (`row.hover()`) instead (see
  the trash test in `web/tests/e2e/mobile.spec.ts`).
- **Stop button never satisfies Playwright actionability**: `#send-btn.btn-stop`
  has an infinite CSS pulse animation, so use `click({ force: true })` and assert
  the resulting effect rather than the button state.

## E2E Stability Pitfalls (Aug 2026)

- **A condition that needs a running stream must slow the stream** (Oct 27
  2026): "scroll position is maintained when scrolling up during active token
  streaming" waited for the reply to grow after the scroll-up. On CI the
  default mock stream (10ms a token) had finished before the scroll, so it
  never grew and the test failed on every run there (local machines were fast
  enough). The fixed sleep it replaced had hidden that the test exercised
  nothing on CI. Set `/test/set-stream-delay` when a test acts mid-stream.

- **A click while the list re-renders reaches no handler** (Oct 26 2026): the
  pin test hovered a row and clicked its pin just as the second conversation's
  generated title re-rendered the sidebar - no pin request was sent at all.
  Wait for the state that triggers the re-render (both titles generated)
  before acting on a row.

- **A switch back can land between the server's save and the client's done** (Oct 26 2026):
  the fetched history already held the finished reply while the client still
  had the stream as active, so the switch rendered it from history AND
  restored a live bubble - the reply showed twice (same `data-message-id`).
  Reproduced 5/100 with `--workers=10`; the active request now records the
  reply's id (`user_message_saved`) and the restore skips a reply the history
  shows. "Streaming message never appears" under load was this race.

- **A list loaded from several places needs a race token** (Oct 26 2026):
  the trash and archive lists load at startup, on a change-log refetch and on
  opening the view. Under load the slow startup answer landed after the
  refetch and put the user-menu badge back to 0 - a "flake" that was a real
  stale-overwrite bug. `loadTrashedConversations` / `loadArchivedConversations`
  apply only the newest load's answer; do the same for any list with
  overlapping loaders.

- **E2E always tests the LAST `make build`, not your source**: the e2e
  server serves the production bundle from `static/assets/`. After any
  frontend change, run `make build` before Playwright or you'll debug the
  previous build's behavior (symptom: your new classes/log lines never
  appear in the browser).
- **`page.route` interceptions persist across `page.reload()`**: a test
  that blocks requests and then reloads is still blocked after the reload -
  `unroute` explicitly when the post-reload phase needs a working network.
- **Stale e2e server after `make build`**: Playwright reuses a running
  server (`reuseExistingServer`). A server started before a rebuild serves
  the old bundle while `/api/version` etc. reflect old state - kill the
  listener first: `lsof -tiTCP:8001 -sTCP:LISTEN | xargs kill` (or the port
  in `E2E_PORT`).
- **Two suites side by side**: `E2E_PORT=8011` (env or `make test-fe-e2e
  E2E_PORT=8011`) gives a run its own server, PID file and database files
  (`tests/e2e-test-<port>-*.db`), so two worktrees or sessions don't kill or
  wipe each other's server. One checkout still shares `static/assets` - a
  `make build` in it changes what both runs serve.
- **Parallel-load setup timeouts**: the mock server (threaded Flask +
  SQLite) sustains ~8 concurrent browser contexts; beyond that, setup
  waits (`waiting for locator('.message.assistant').nth(N)`) time out
  ~1/600 tests. Workers are therefore PINNED to 4 in
  `playwright.config.ts` - don't raise without 5x consecutive clean
  full-suite runs at the higher value.
- **Version banner in accessibility snapshots**: `.version-banner` is
  always in the DOM (hidden via transform), so it appears in every
  Playwright error-context snapshot - it is NOT evidence the banner was
  shown.

## Key Files

- [web/playwright.config.ts](../../web/playwright.config.ts) - per-project retries (webkit 3, chromium 2 on CI), pinned `workers: 4`
- [tests/e2e_server/](../../tests/e2e_server/) - the mock server: `/dev/shm` databases (`settings.py`), `synchronous=OFF` (`db.py`), `SLOW`/`INFLIGHT` phase log (`request_log.py`)
- [.github/workflows/test.yml](../../.github/workflows/test.yml) - one browser project per runner, webkit shards

## See Also

- [Frontend and E2E Testing](frontend.md) - E2E structure and the mock server
- [Visual Regression Tests](visual.md) - baselines
- [Scroll Behavior](../ui/scroll-behavior.md) - the scroll logic most of these races touched

## Open flakes

CI fails when a test passes only on a retry (T6, `web/tests/flaky-gate.ts`), unless
`web/tests/e2e/flaky-quarantine.json` lists it with the entry below that tracks it.
Fix a flake: delete its entry here and in the quarantine list together.

One-off failures not yet reproduced (each passed on retry). Oct 26 2026: none of the entries below failed in 15 repeats each under `--workers=10`, nor in a broad E2E run while the backend suite saturated every core (that run is what caught the pin race, below in Pitfalls). Capture the
trace and `test-results/` on the next occurrence - copy them before rerunning,
since a rerun clears the folder. Fixed or quiet for a month: delete the entry.

- **CI hang: WebKit E2E shard froze in deep research** (Oct 9 2026) - run 37948653042 (95249c0), `Frontend E2E Tests (webkit 2/4)` hit the 30-min job timeout (normally ~6 min): `deep-research.spec.ts` "an explicit request starts by itself" (test 86, the countdown autostart) never reported and nothing after test 87 ran; the mock server's SLOW/INFLIGHT log was empty. A hang past Playwright's per-test timeout points at a frozen worker/browser, not an assertion. Re-ran the job; capture the Playwright trace if it recurs. Likely the same root cause found Oct 23 2026: Playwright's WebKit has no push service and `pushManager.getSubscription()` on a service-worker-controlled page could freeze the page; service workers are now blocked suite-wide - drop this item if it does not recur.
- **Chromium flake: stream resume after a connection drop** (Oct 13 2026) - `stream-resume.spec.ts:63` "connection drop mid-stream resumes from offset to full message" timed out once in a full `make test-all`: `page.waitForRequest('/resume?after_seq=')` never saw the client's resume request within 30s. Webkit passed in the same run; 5/5 alone on chromium. The trace was lost (isolated reruns clear `test-results/`) - copy `test-results/` before rerunning next time.
- **WebKit stall: sync specs can't find visible buttons** (Oct 14 2026) - one full `make test-all` failed 4 WebKit tests (`sync.spec.ts` x3 in `beforeEach` on `#stream-btn`, `sync-other-device.spec.ts:374` on `#send-btn`): the screenshot shows the button rendered, yet the call log never got past "waiting for locator" - a frozen page, not an assertion. Both specs passed 132/132 with `--repeat-each=3` right after, and the next full run was green. Same shape as the Oct 9 deep-research hang; capture a trace on the next occurrence. Likely the same root cause found Oct 23 2026: Playwright's WebKit has no push service and `pushManager.getSubscription()` on a service-worker-controlled page could freeze the page; service workers are now blocked suite-wide - drop this item if it does not recur.
- **Two one-off CI flakes, Oct 24 2026 (main run 40069972669, each passed on retry)** - capture artifacts on recurrence: (1) [chromium visual] `grounding.visual.ts:43` claim card rendered 320x99 vs the 320x98 baseline (one-pixel height, 452 px); (2) [webkit] `stream-recovery.spec.ts:333` "handles conversation switch during recovery" - the first conversation's user message never became visible after switching back (30s). Also seen once the same day: [webkit] `chat/thinking-indicator.spec.ts:119` "the live line's chevron is centred on its row (desktop)" (run 40071139480). And on Oct 24 (run 40077189760): [chromium] `grounding-annotations.spec.ts:25` "underline opens a card; Look it up sends a follow-up" - `#claim-card .claim-card__reply` ("Looked up below ↓") resolved, then was detached from the DOM and never came back within 30s (the card closed or re-rendered between the claim click and the reply click).
- **WebKit flake: PDF chunk reload specs** (Oct 26 2026) - `chat/pdf-viewer.spec.ts` "a chunk deleted by a deploy reloads the page" and "a chunk that still fails right after the reload does not reload again" time out waiting for the page `load` event after clicking the PDF link, about 3 in 30-60 isolated runs (`--repeat-each`), with both the old single-file mock server and the split `tests/e2e_server/` package. Not Playwright's interception: since Oct 26 the mock server answers the 404 (`/test/set-missing-assets`, no `page.route`), and it still fails about 1 in 120 WebKit runs (2/240, both on the second spec; chromium 30/30). Trace evidence (failed run): the click starts ~15 chunk preloads, 7 revalidate (304), the chunk 404s, the reload's `GET /` starts while the other 8 are cancelled (status -1) - and `GET /` never completes and never reaches the server (no request log line, no INFLIGHT). In the passing run compared, the reload went out before most preloads did. Next suspect: WebKit's connection pool against the dev server's keep-alive connections after cancelled loads.
- **Chromium visual: wide table row antialiasing under load** (Oct 27 2026) - `visual/mobile.visual.ts:221` "wide table has horizontal scroll on mobile" differs from its baseline by ~450 px, all in the text of the first body row (Data A1-A4) and only in its antialiasing: grayscale instead of subpixel, as if that row were painted on its own layer. About 1-2 in 25 under `--workers=10` with the backend suite loading the machine, 0 in 16 alone; also seen on the commit before the Oct 27 CSS consolidation, so it predates it. Not a sticky header (there is none) and not a running animation (`pageSettled` waits for them). Next: capture a trace and check which layer row A paints into (the overflow-x scroll wrapper is the prime suspect - Chromium may composite a scroller late on a busy machine).
- **WebKit one-off: trash view confirm modal** (Oct 27 2026) - `conversation.spec.ts:438` "trash view restores, deletes forever, and empties" timed out once in a full `make test-all` clicking `.modal-container:not(.modal-hidden) .modal-confirm` (the modal never showed or was replaced); 30/30 right after on WebKit under load. The artifacts were lost to that rerun - copy `test-results/` first next time.
- **WebKit one-off: planner model selector** (Oct 26 2026) - `planner.spec.ts:381` "model selector shows planner model when navigating to planner" failed once in a full `make test-all` (`toBeVisible` - element not found); 470/470 right after with `--repeat-each=10` on both browsers. Capture `test-results/` on the next occurrence.
