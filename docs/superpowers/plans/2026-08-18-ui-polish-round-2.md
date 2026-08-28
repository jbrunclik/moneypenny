# UI Polish Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Aug 2026 design system to the surfaces round 1 missed (planner, login, search/archive, quiz, thinking, settings internals, toasts/FAB), fix PWA theming, harden accessibility, and make the test infrastructure deterministic (pinned workers + CI visual tests with Linux baselines).

**Architecture:** Frontend-only except CI workflow changes. CSS-restyle tasks apply the established token/pattern vocabulary; a11y adds one shared focus-trap utility; infra pins Playwright workers and adds a Docker-based visual CI job.

**Tech Stack:** Same as round 1. Playwright 1.61.1 (Docker image `mcr.microsoft.com/playwright:v1.61.1-jammy`), Docker 28.4 available locally.

**Spec:** `docs/superpowers/specs/2026-08-18-ui-polish-round-2-design.md`

## Global Constraints

- Commits to `main`; `make lint` + relevant suites green per commit; `make test-all` at boundaries (after Tasks 4, 9, 12).
- Kill the stale e2e server after every `make build` before Playwright runs (`lsof -tiTCP:8001 -sTCP:LISTEN | xargs kill`).
- Visual re-baseline (darwin) per pixel-affecting commit; Linux baselines generated ONCE in Task 11 after all pixel work.
- Preserve test-critical selectors; `.scroll-to-bottom.streaming-paused` contract must survive Task 8.
- Auto-scroll is regression-critical: any change near `#messages` runs the scroll suites (`conversation.spec.ts` Scroll describe + `chat/streaming.spec.ts`).
- Every UI change verified desktop+mobile x light/dark via `node web/scripts/ui-capture.cjs`.

---

### Task 1: Pin Playwright workers (stability first)

**Files:** Modify `web/playwright.config.ts`, `docs/testing.md`.

- [ ] **Step 1:** In `playwright.config.ts` set `workers: 4` (replacing `'50%'`), with a comment: the single-process mock server (already `threaded=True`) sustains 8 contexts (4 workers x 2 projects); above that, setup waits time out ~1/600 tests.
- [ ] **Step 2:** Update `docs/testing.md` "E2E Stability Pitfalls": workers now pinned; remove the "re-run with --workers=4" workaround sentence.
- [ ] **Step 3:** Verify determinism: two consecutive full runs `cd web && npx playwright test` — both must be 100% green (this also validates the pin under the visual+e2e combined load).
- [ ] **Step 4:** Commit `test(e2e): pin Playwright workers to 4 for deterministic runs`.

### Task 2: Bundle import hygiene

**Files:** Modify the files named by `INEFFECTIVE_DYNAMIC_IMPORT` warnings (agents.ts, conversation.ts, kv-store dynamic imports in conversation/events/init, sports.ts, language.ts, planner.ts, Sidebar.ts import in render.ts, AgentEditor.ts).

**Interfaces:** No API changes — dynamic `import('./x').then(({ f }) => f())` becomes static `import { f } from './x'` + direct call.

- [ ] **Step 1:** `make build 2>&1 | grep INEFFECTIVE` — list every warning (baseline: 6-8).
- [ ] **Step 2:** For each: check whether making it static creates an import cycle (`npx madge --circular web/src/main.ts` if available, else follow imports manually). If cyclic, KEEP dynamic and add `// dynamic: breaks import cycle with X` comment; otherwise convert to static import at top of file and unwrap the `.then()` body (preserve `void`/`await` semantics of call sites).
- [ ] **Step 3:** Acceptance: `make build` shows zero INEFFECTIVE warnings (or only commented cycle-breakers); record main chunk size before/after in the commit message (must be within ±1%).
- [ ] **Step 4:** `npx vitest run` + full Playwright green. Commit `refactor(web): remove ineffective dynamic imports`.

### Task 3: PWA & browser theming

**Files:** Modify `web/index.html`, `static/manifest.json`, `static/icon.svg`; regenerate `static/icon-180.png`, `icon-192.png`, `icon-512.png`.

- [ ] **Step 1:** index.html: replace the single theme-color meta with:

```html
<meta name="theme-color" content="#0f0f0f" media="(prefers-color-scheme: dark)">
<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
```

- [ ] **Step 2:** manifest.json: `"theme_color": "#0f0f0f"`, `"background_color": "#0f0f0f"`; sanity-check icons array and display mode.
- [ ] **Step 3:** icon.svg: replace old palette fills (grep for `#6366f1`, `#8b5cf6`, `#a855f7`, `#1a1a2e`, `#2563eb`) with new ramp equivalents (`#5753e8`, `#7c5ce8`, `#9b6cf2`, `#0f0f0f`, `#4a46c6`). Regenerate rasters with macOS built-ins (no new deps):

```bash
for s in 180 192 512; do
  qlmanage -t -s $s -o /tmp static/icon.svg && mv "/tmp/icon.svg.png" static/icon-$s.png
done
```
(If qlmanage output is unreliable, fall back to `rsvg-convert`/`sips` or a tiny Playwright screenshot script rendering the SVG at each size.)
- [ ] **Step 4:** Verify: `make build`, open dev on phone-sized capture; check tab tint via devtools emulation; eyeball the icons. Commit `fix(pwa): theme-color and icons aligned to the new palette`.

### Task 4: Contrast bump (dark muted text)

**Files:** Modify `web/src/styles/variables.css`.

- [ ] **Step 1:** Dark `:root`: `--color-neutral-400: #666666` → `#8a8a8a` (≈5.3:1 on #0f0f0f). Light theme unchanged.
- [ ] **Step 2:** Capture sweep (all 16 shots) — confirm nothing relied on the old value to look "disabled"; check send-button disabled state and placeholder legibility specifically.
- [ ] **Step 3:** vitest + Playwright + darwin re-baseline. **Phase boundary: run `make test`.** Commit `fix(a11y): dark-mode muted text to 5.3:1 contrast`.

### Task 5: Planner restyle

**Files:** Modify `web/src/styles/components/planner.css`, `web/src/components/PlannerDashboard.ts` (class/markup only where needed).

- [ ] **Step 1:** Read both files + capture planner before-state (`/#/planner` needs Todoist/Calendar; use e2e server with `/test/set-planner-integrations` + `/test/set-planner-dashboard` and screenshot at 1440/390, both themes).
- [ ] **Step 2:** Apply the system: `.dashboard-title` → `font-family: var(--font-family-display); font-weight: 600; letter-spacing: -0.01em; color: var(--text-primary);` (kill any gradient/two-tone). Cards → `bg-secondary` + 1px `--border`, `--radius-md`; remove decorative accent-tinted backgrounds (the swept `rgba(87,83,232,...)` boxes) except genuine state highlights; primary buttons → accent pill vocabulary; section labels → uppercase group-label style.
- [ ] **Step 3:** `planner.spec.ts` + `planner.visual.ts` green (selectors preserved: `.planner-entry`, `#planner-dashboard`, `.dashboard-title`, `.dashboard-error`); darwin re-baseline; captures both themes/viewports. Commit `feat(planner): align dashboard with the design system`.

### Task 6: Login screen restyle

**Files:** Modify `web/src/core/init.ts` (login markup at ~line 206), `web/src/styles/components/popups.css` (login styles).

- [ ] **Step 1:** Markup keeps ids/classes (`#login-overlay`, `.login-box`, `#google-login-btn`, `.login-privacy-link`); h2 gets the display face via CSS (copy unchanged - branding out of scope).
- [ ] **Step 2:** CSS: `.login-overlay` on `--bg-primary`; `.login-box` → `bg-secondary`, 1px border, `--radius-lg`, `--shadow-lg`, `popup-in` entrance animation; h2 → display face `--font-size-3xl`; `p` → `--text-secondary`; privacy link → `--text-muted` small.
- [ ] **Step 3:** `auth.spec.ts` + `login.visual.ts` green, re-baseline. Commit `feat(login): align sign-in screen with the design system`.

### Task 7: Search results & archive consistency

**Files:** Modify `web/src/components/SearchResults.ts`, `web/src/components/Sidebar.ts` (`renderArchivedConversationItem`, archive view header), `web/src/styles/components/sidebar.css`.

- [ ] **Step 1:** Archive rows: add `<span class="conversation-time">${formatRelativeTime(conv.updated_at)}</span>` after the title (same anatomy as active rows); archive view header uses the shared back-button pattern (keep `.archive-back-btn`, `.archive-view-header` selectors — tests use them).
- [ ] **Step 2:** Search results: row paddings/hover/active states matched to `.conversation-item`; snippet `--text-muted` `--font-size-sm`; match highlight `<mark>`/highlight class → `background: var(--accent-muted); color: inherit;`.
- [ ] **Step 3:** `Sidebar.test.ts` archive tests + `search.spec.ts` + `search.visual.ts` green; re-baseline. Commit `feat(sidebar): search and archive rows join the conversation-row system`.

### Task 8: Quiz, thinking indicator, settings internals, toasts, scroll FAB

**Files:** Modify `web/src/styles/components/quiz.css`, `thinking.css`, `popups.css` (toasts + settings sections), `buttons.css` (FAB), `web/src/components/SettingsPopup.ts` (button class swaps only).

- [ ] **Step 1:** Thinking indicator: replace gradient chip (`thinking.css` ~line 206 `linear-gradient(...bg-tertiary, rgba(87,83,232,...))`) with `background: var(--bg-secondary); border: 1px solid var(--border);`; entrance `popup-in`.
- [ ] **Step 2:** Quiz: radii → `--radius-md`, borders → `--border`; correct → `--color-success-900` bg + `--color-success-400` text (dark) / semantic equivalents light; incorrect → error equivalents; buttons → shared pill vocabulary. CSS only; `quiz-block.test.ts` + `language.visual.ts` green.
- [ ] **Step 3:** Settings integrations: connect buttons → `class="btn btn-primary btn-inline"` style (define `.btn-inline { width: auto; }` modifier in buttons.css if absent), disconnect → hairline secondary; connected status → badge treatment. Update `settings.spec.ts`/`popups.visual.ts` if selectors change (keep button text).
- [ ] **Step 4:** Toasts: `--radius-md`, `--shadow-lg`, entrance/exit via `--duration-base`/`--ease-out`; success/error left-accent via semantic tokens.
- [ ] **Step 5:** Scroll FAB: shadow → `--shadow-lg`, replace remaining hardcoded rgba pulse colors with `--accent`-derived tokens; `.streaming-paused` visual kept distinct; scroll suites + `error-ui.visual.ts` green.
- [ ] **Step 6:** Full frontend suites + re-baseline. Commit `feat(ui): quiz, thinking, settings internals, toasts and scroll FAB join the design system`.

### Task 9: Accessibility — focus trap, aria-live, sidebar keyboard nav, focus audit

**Files:** Create `web/src/utils/focus-trap.ts`; modify `web/src/utils/popupEscapeHandler.ts` call sites (or popup open/close fns), `web/src/components/messages/streaming.ts`, `web/src/components/Sidebar.ts`, `web/src/core/events.ts`.
**Test:** Create `web/tests/unit/focus-trap.test.ts`.

**Interfaces:**
- Produces: `trapFocus(container: HTMLElement): () => void` — installs a keydown listener cycling Tab/Shift+Tab within container's focusables, remembers `document.activeElement`, returns a release fn that restores focus.

- [ ] **Step 1 (TDD):** unit test: trap in a container with 2 buttons; Tab from last wraps to first; Shift+Tab from first wraps to last; release restores prior focus. Run — FAIL.
- [ ] **Step 2:** Implement `focus-trap.ts` (~40 lines: query `a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])`; keydown handler on container). Run — PASS.
- [ ] **Step 3:** Wire: `openSettingsPopup`/`closeSettingsPopup`, generic info-popup open/close helpers (`InfoPopup.ts`), `Modal.ts` (showConfirm/showPrompt/alert), sports/language program modals, AgentEditor. Store the release fn per popup.
- [ ] **Step 4:** aria-live: in `messages/streaming.ts`, when the streaming bubble's `.message-content` is created, `el.setAttribute('aria-live', 'polite')`; remove attribute on stream end (prevents later edits re-announcing).
- [ ] **Step 5:** Sidebar keyboard nav: `.conversation-item` gets `tabindex="0"` + `role="button"`; keydown delegation on `#conversations-list`: ArrowDown/ArrowUp move focus between `.conversation-item`s, Enter/Space opens (reuse click path).
- [ ] **Step 6:** Focus-visible audit: verify `:focus-visible` outline renders on user-menu items, settings tabs, model options, message overflow toggle; add rules where missing.
- [ ] **Step 7:** Full frontend suites green (keyboard changes can affect e2e tab order — watch `settings.spec.ts`). **Phase boundary: `make test`.** Commit `feat(a11y): focus trapping, streaming announcements, sidebar keyboard navigation`.

### Task 10: (reserved — merged into Task 8)

Removed during planning; numbering kept stable for cross-references.

### Task 11: CI visual tests + Linux baselines

**Files:** Create workflow job in `.github/workflows/<tests>.yml`; commit `*-linux.png` baselines; modify `Makefile` (new target), `docs/testing.md`.

- [ ] **Step 1:** Makefile target:

```make
test-fe-visual-linux-update: ## Regenerate Linux visual baselines via Docker
	docker run --rm -v $(PWD):/work -w /work/web \
	  mcr.microsoft.com/playwright:v1.61.1-jammy \
	  /bin/bash -lc "cd /work && .venv-linux-guard 2>/dev/null; cd web && npm ci && npx playwright test tests/visual --update-snapshots"
```
NOTE: the e2e webServer needs Python + the venv inside the container — if that proves heavy, instead run the Flask server on the HOST (`python tests/e2e-server.py`) and point the container at `host.docker.internal:8001` via `PLAYWRIGHT_BASE_URL` env (config already reads baseURL; add env override `baseURL: process.env.PW_BASE_URL || 'http://localhost:8001'` and `reuseExistingServer` guard). Choose whichever works first; document the winner.
- [ ] **Step 2:** Generate + commit `-linux` baselines for all visual suites (~150 files).
- [ ] **Step 3:** CI job "Visual Tests": container `mcr.microsoft.com/playwright:v1.61.1-jammy`, steps mirroring the existing E2E job but `npx playwright test tests/visual`; artifacts on failure (playwright-report).
- [ ] **Step 4:** Push, watch the run green. Document dual-baseline workflow in docs/testing.md. Commit `ci: visual regression tests with Linux baselines`.

### Task 12: Final audit

- [ ] **Step 1:** Full capture matrix review; fix stragglers.
- [ ] **Step 2:** `make lint && make test-all`; both baseline sets updated if stragglers changed pixels.
- [ ] **Step 3:** Docs touch-up (components.md: planner/login/toast patterns now on-system; testing.md final state). Commit `docs(ui): round-2 polish documentation`.
- [ ] **Step 4:** Push + deploy to the server (`git pull && make update`), verify health + bundle parity.

## Self-review notes

- Spec coverage: item 1→Task 3, 2→Task 2, 3→Task 5, 4→Task 6, 5→Task 7, 6→Task 8(1-2), 7→Task 8(3-5), 8→Tasks 4+9, 9→Task 11, 10→Task 1. Delivery order per spec (stability first, Linux baselines last).
- Task 10 intentionally vacated (settings/toasts/FAB merged into Task 8) — kept to avoid renumbering.
- Risk callouts: Task 9 focus trap can break e2e flows that Tab through pages (audit settings.spec); Task 11 webServer-in-Docker is the only genuinely uncertain step and has a documented fallback.
