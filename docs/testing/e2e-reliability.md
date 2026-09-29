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
  `thumbnails.ts` now runs before that tolerance.
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
  boot) so the loading state is observable; note `page.route` cannot see
  requests that pass through the service worker on WebKit - that describe
  uses `test.use({ serviceWorkers: 'block' })`.
- **Runner CPU starvation, not the mock server** - the e2e-server's SLOW
  log showed `/test/reset` taking up to 12s on the webkit runner at only
  4-10 server threads (a reset is ~6ms in isolation; even `GET /` took
  3.8s). Four webkit contexts saturate a 2-vCPU runner. WebKit now runs as
  four shards of two workers; the server also prints `INFLIGHT` lines for
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

## E2E Gotchas (Streaming, Service Workers, Media)

- **E2E serves BUILT assets** — `make test-fe-e2e` runs `make build` first, but a
  direct `npx playwright test` does not: rebuild after every `web/src` change or you
  test the stale bundle (see also the first Stability Pitfall below).
- **Streaming outruns assertions**: the default mock stream delay is ~10ms/token,
  so the stream finishes before any mid-stream click/assertion. Specs that must
  observe streaming state set a larger delay via `POST /test/set-stream-delay`
  (per-execution-id isolated).
- **Service worker blocks route mocks**: the app registers `/sw.js`
  ([src/app.py](../../src/app.py)), and `page.route()` does **not** intercept
  service-worker-mediated fetches. Any spec that mocks API responses must opt out
  with `test.use({ serviceWorkers: 'block' })` (see
  `web/tests/e2e/chat/attachments.spec.ts`).
- **Config-shrinking route mocks race app init**: after `goto`, await the config
  response (e.g. `waitForResponse('**/api/config/upload')`) before acting, or the
  store still holds defaults.
- **libmagic video detection**: production validation uses `magic.from_buffer`,
  which can return `application/octet-stream` for real video containers — hence
  the `_matches_video_signature()` fallback in
  [src/utils/files.py](../../src/utils/files.py). Hand-crafted `ftyp` headers are
  not enough; use real (tiny, ffmpeg-generated) fixtures under `tests/fixtures/`.
- **Stop button never satisfies Playwright actionability**: `#send-btn.btn-stop`
  has an infinite CSS pulse animation, so use `click({ force: true })` and assert
  the resulting effect rather than the button state.

## E2E Stability Pitfalls (Aug 2026)

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
  listener first: `lsof -tiTCP:8001 -sTCP:LISTEN | xargs kill`.
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
- [tests/e2e-server.py](../../tests/e2e-server.py) - `/dev/shm` databases, `synchronous=OFF`, `SLOW`/`INFLIGHT` phase log
- [.github/workflows/test.yml](../../.github/workflows/test.yml) - one browser project per runner, webkit shards

## See Also

- [Frontend and E2E Testing](frontend.md) - E2E structure and the mock server
- [Visual Regression Tests](visual.md) - baselines
- [Scroll Behavior](../ui/scroll-behavior.md) - the scroll logic most of these races touched
