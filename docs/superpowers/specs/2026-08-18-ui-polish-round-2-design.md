# UI Polish Round 2 — Design Spec

**Date:** 2026-08-18
**Status:** Draft for review
**Prerequisite:** The Aug 2026 UI/UX overhaul (`2026-08-18-ui-ux-overhaul-design.md`) — this round extends its design system to the surfaces it didn't reach and hardens what it exposed.

## Scope

Seven visual items, three accessibility items, two infrastructure items. Explicitly out of scope: product naming/branding, suggested prompts (rejected), and empty-conversation pruning (deferred by Jiri).

---

## 1. PWA & browser theming (bug-adjacent)

**Files:** `web/index.html`, `web/public/manifest.json` (or `.webmanifest`), `web/public/icon.svg`, `web/public/icon-192.png`.

- `theme-color` meta still ships the pre-overhaul `#1a1a2e`. Replace with theme-aware pair:
  `<meta name="theme-color" content="#0f0f0f" media="(prefers-color-scheme: dark)">` and `content="#ffffff"` for light.
- Manifest `theme_color`/`background_color` aligned to `#0f0f0f`; verify `display` and icon entries while in there.
- `icon.svg` retinted to the new brand ramp (`#5753e8` family); regenerate `icon-192.png` (and any other raster sizes referenced) from it. No shape/identity change — recolor only (branding remains out of scope).
- Verify on a real iPhone: status bar/tab tint matches the app background in both themes after reinstalling the PWA.

## 2. Bundle import hygiene

**Files:** `web/src/core/agents.ts`, `conversation.ts`, `events.ts`, `init.ts`, `messaging.ts`, `search.ts`, `stream-recovery.ts`, `web/src/components/AgentEditor.ts`, `messages/render.ts` (exact set = build warning list).

- Every `INEFFECTIVE_DYNAMIC_IMPORT` warning is a module imported dynamically in one place and statically in another — the dynamic form adds async ceremony and misleads readers while splitting nothing. Convert those dynamic imports to static (the modules are already in the main chunk; bundle size is unchanged) **except** where the dynamic import exists to break a circular dependency — verify each case; where circularity is the reason, keep the dynamic import and add a comment saying so.
- Acceptance: `make build` emits zero `INEFFECTIVE_DYNAMIC_IMPORT` warnings; main chunk size within ±1% of before.
- Non-goal: aggressive code splitting (katex/highlight.js chunking). Record current chunk sizes in the PR/commit message as a baseline for a future pass.

## 3. Planner restyle

**Files:** `web/src/styles/components/planner.css`, `web/src/components/PlannerDashboard.ts` (markup only where classes must change).

- "Your Schedule" title → display face, single color (same treatment as Command Center) — the title stays visible on mobile (it differs from the mobile header's "Planner").
- Buttons/chips onto the shared vocabulary: accent pills for primary actions, hairline-bordered secondary, no bespoke paddings/radii.
- Replace remaining decorative accent-tinted boxes/gradients with the flat `bg-secondary` + hairline card pattern used across the redesigned dashboards.
- Sections separated by hairlines, section labels in the small uppercase group-label style where lists are grouped (events/tasks).
- Both themes, desktop + mobile captures before/after.

## 4. Login screen restyle

**Files:** login overlay markup in `web/src/core/init.ts` (or its component), `web/src/styles/components/popups.css` (login styles).

- Display-face headline ("What can I help with?" spirit — copy: "Sign in to continue"), centered card on `bg-primary`, Google button unchanged (Google brand rules), subtle entrance animation consistent with the motion tokens.
- Both themes; `login.visual.ts` baselines updated.

## 5. Sidebar consistency: search results & archive

**Files:** `web/src/components/SearchResults.ts`, `Sidebar.ts` (archive view), `web/src/styles/components/sidebar.css`.

- Archive rows get the same row anatomy as conversations: title + right-aligned relative time (`formatRelativeTime(updated_at)`); archive view header restyled with the shared back-button pattern.
- Search result rows aligned to conversation-row styling (paddings, hover, snippet in `--text-muted` at `--font-size-sm`); highlight matches with `--accent-muted` background rather than any legacy highlight color.
- No behavior changes; component tests updated only where markup changes.

## 6. Quiz blocks & thinking indicator restyle

**Files:** `web/src/styles/components/quiz.css`, `thinking.css`.

- Thinking indicator: drop the legacy gradient chip; flat `bg-secondary` + hairline card, animated dots keep working, entrance via motion tokens.
- Quiz blocks: radii to `--radius-md`, borders to hairline `--border`, correct/incorrect states use the semantic success/error tokens with `-muted` backgrounds (match badge treatment), buttons onto the shared vocabulary. No interaction changes — CSS only.
- Language visual suite re-baselined.

## 7. Settings internals & small chrome (toasts, scroll FAB)

**Files:** `web/src/styles/components/popups.css`, `web/src/components/SettingsPopup.ts` (class swaps only), `buttons.css`.

- Integration connect/disconnect buttons ("Connect Todoist", etc.) move from bespoke full-width 12px pills to the shared inline pill vocabulary (primary for connect, hairline secondary for disconnect); status rows get the badge treatment used elsewhere.
- Toasts: `--radius-md`, `--shadow-lg`, entrance/exit via motion tokens (respecting reduced motion), success/error accents via semantic tokens.
- Scroll-to-bottom FAB: align shadow/radius with the system, replace remaining hardcoded rgba accents with tokens; keep the streaming-paused highlighted state contract (`.streaming-paused` class, tests depend on it).

## 8. Accessibility hardening

**Files:** `web/src/utils/popupEscapeHandler.ts` or new `web/src/utils/focus-trap.ts`, `web/src/components/messages/streaming.ts`, `Sidebar.ts`, `variables.css`.

- **Focus trap:** while any modal/popup is open (`.info-popup:not(.hidden)`, `.modal-container:not(.modal-hidden)`, agent editor, program modals), Tab cycles within it; focus returns to the invoking element on close. One shared utility, wired where popups open/close.
- **Streaming announcements:** the streaming message container gets `aria-live="polite"` (set once on the streaming bubble, not per token) so screen readers announce replies; verify it doesn't spam by announcing per-chunk.
- **Sidebar keyboard navigation:** conversation list focusable (`tabindex`, `role="listbox"`-style semantics or plain buttons), ArrowUp/Down move focus, Enter opens, Delete key optional non-goal.
- **Contrast bump:** dark `--color-neutral-400` (muted text) `#666666` → `#8a8a8a` (≈5.3:1 on `#0f0f0f`); light equivalent checked (`#6b7280` on white is 4.9:1 — passes, unchanged). Sweep captures to confirm nothing else relied on the old value for "disabled" affordance.
- Focus-visible audit on the components added in round 1: user menu items, settings tabs, model dropdown options, message-action overflow toggle.

## 9. CI visual tests (Linux baselines)

**Files:** `.github/workflows/*` (Tests workflow), committed `-linux.png` baselines.

- New CI job "Visual Tests" running in the official Playwright Docker image (pinned to the repo's Playwright version), executing `npx playwright test tests/visual`.
- Baseline generation: run the same Docker image locally (`docker run mcr.microsoft.com/playwright:v<version>-jammy`) with `--update-snapshots` to produce and commit `-linux` baselines. If Docker isn't available locally, bootstrap via a one-off CI run that uploads the generated snapshots as an artifact, commit them, then enable the job as required.
- macOS `-darwin` baselines remain for local runs; document the dual-baseline workflow in `docs/testing.md` (update both when pixels change: local `make test-fe-visual-update` + docker variant; add a `make` target wrapping the docker invocation).

## 10. E2E stability: mock-server capacity

**Files:** `web/playwright.config.ts`, `tests/e2e-server.py`, `docs/testing.md`.

- Pin Playwright workers to a value the mock server sustains (measured today: failures at ~14 contexts, clean at 8 with `--workers=4` across two browser projects). Set `workers: 4` in config (CI and local) — slower wall-clock (~4.4 min vs 3.5) but deterministic beats fast.
- Investigate the server side: if the Flask dev server is single-threaded, enable `threaded=True` (or serve via `waitress` with a thread pool) and re-measure whether higher worker counts hold; raise the pinned count only if a 5x consecutive full-suite run stays clean.
- Update `docs/testing.md` pitfalls section to reflect the new defaults and remove the "re-run with --workers=4" workaround note once pinned.

## Delivery

Same as round 1: phased commits to `main`, lint + relevant suites green per commit, `make test-all` at boundaries, visual re-baseline (both platforms once item 9 lands) for every pixel-affecting change, desktop+mobile × light/dark captures per surface. Suggested order: 10 (stability first — everything else re-runs suites), 2, 1, 8-contrast, 3, 4, 5, 6, 7, 8-rest, 9 last (so Linux baselines are generated once, after all pixel changes).
