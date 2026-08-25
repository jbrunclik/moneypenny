# UI/UX Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the 7-phase UI/UX overhaul (tokens/fonts, chat surface, compose card, sidebar, settings, dashboards, motion) so the app reads as a polished premium product in all 4 variants (light/dark x desktop/mobile).

**Architecture:** Pure frontend work in `web/`. Phase 1 rewrites the design tokens (`variables.css`) and adds self-hosted fonts; later phases restructure component markup in `init.ts`/component TS files and their CSS, preserving test-critical ids/classes wherever possible and updating tests where markup deliberately changes.

**Tech Stack:** Vite + TypeScript (strict), plain DOM components, Zustand, CSS custom properties, Fontsource (self-hosted woff2), Vitest (unit/component), Playwright (E2E + visual, chromium & webkit).

**Spec:** `docs/superpowers/specs/2026-08-18-ui-ux-overhaul-design.md`

## Global Constraints

- Commits go directly to `main`; every commit must have `make lint` green and the tests named in the task green. Run the full `make test-all` at each phase boundary (end of Tasks 4, 9, 13, 18, 20, 22, 25).
- E2E always with timeout: `cd web && timeout 600 npx playwright test`. Zero tolerance for flaky tests.
- Visual baselines: any pixel-affecting commit must re-baseline (`make test-fe-visual-update`) and the diff must be eyeballed via `make test-fe-visual-browse` before committing.
- Preserve these test-critical selectors unless a task explicitly says to update the tests: `#message-input`, `#send-btn`, `#new-chat-btn`, `#menu-btn`, `#settings-btn`, `#settings-popup`, `#model-selector-btn`, `#model-dropdown`, `.model-option`, `[data-model-id]`, `#current-model-name`, `.welcome-message`, `.conversation-item-wrapper`, `[data-conv-id]`, `.conversation-delete`, `.command-center*`, `.sports-*`, `.language-*`, `.planner-entry`.
- No external network requests from the frontend (fonts self-hosted via Fontsource, bundled by Vite).
- Every UI change verified on desktop (1440px) and mobile (390px) in both themes. Capture helper: `node web/scripts/ui-capture.cjs` (created in Task 1).
- Conventional Commits (`feat(ui): ...`, `fix(settings): ...`).
- The auto-format hook runs after every Edit/Write; do not hand-format.

---

## Phase 1 — Foundation

### Task 1: Self-hosted fonts + capture utility

**Files:**
- Modify: `web/package.json` (via npm install)
- Modify: `web/src/main.ts` (font imports at top)
- Modify: `web/src/styles/variables.css:171-172`
- Create: `web/scripts/ui-capture.cjs` (move of the existing scratchpad script)

**Interfaces:**
- Produces: `--font-family` = Inter Variable stack; `--font-family-display` (new token) for later tasks.

- [ ] **Step 1: Install fonts**

```bash
cd web && npm install @fontsource-variable/inter @fontsource-variable/bricolage-grotesque
```

- [ ] **Step 2: Verify latin-ext (Czech) coverage is included**

```bash
grep -c "latin-ext" web/node_modules/@fontsource-variable/inter/index.css
grep -c "latin-ext" web/node_modules/@fontsource-variable/bricolage-grotesque/index.css
```
Expected: >= 1 for each. If 0, additionally import the `latin-ext` css file from the package in Step 3 (check `ls web/node_modules/@fontsource-variable/inter/`).

- [ ] **Step 3: Import fonts in `web/src/main.ts`** — add as the FIRST imports of the file:

```ts
import '@fontsource-variable/inter';
import '@fontsource-variable/bricolage-grotesque';
```

- [ ] **Step 4: Update font tokens in `variables.css`** — replace lines 171-172:

```css
    --font-family: 'Inter Variable', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    --font-family-display: 'Bricolage Grotesque Variable', var(--font-family);
    --font-family-mono: 'SF Mono', 'Consolas', 'Monaco', monospace;
```

- [ ] **Step 5: Create `web/scripts/ui-capture.cjs`** — copy the capture script from the session scratchpad (`capture.js`), change the `require` to plain `require('playwright')` (run it from `web/`), change `OUT` to `web/ui-captures/` and add `ui-captures/` to `web/.gitignore`. Script content (adjust the conversation URL to any seeded conversation when running):

```js
const { chromium } = require('playwright');
const fs = require('fs');
const OUT = __dirname + '/../ui-captures';
fs.mkdirSync(OUT, { recursive: true });
const BASE = process.env.CAPTURE_BASE || 'http://localhost:5173';
const PAGES = [
  { name: 'home', url: '/' },
  { name: 'conversation', url: process.env.CAPTURE_CONV || '/' },
  { name: 'sports', url: '/#/sports' },
  { name: 'agents', url: '/#/agents' },
];
(async () => {
  const browser = await chromium.launch();
  for (const theme of ['light', 'dark']) {
    for (const vp of [
      { name: 'desktop', width: 1440, height: 900, mobile: false },
      { name: 'mobile', width: 390, height: 844, mobile: true },
    ]) {
      const ctx = await browser.newContext({
        viewport: { width: vp.width, height: vp.height },
        deviceScaleFactor: 2, isMobile: vp.mobile, hasTouch: vp.mobile,
      });
      await ctx.addInitScript((t) => localStorage.setItem('ai-chatbot-color-scheme', t), theme);
      for (const p of PAGES) {
        const page = await ctx.newPage();
        await page.goto(BASE + p.url);
        await page.waitForTimeout(2500);
        await page.screenshot({ path: `${OUT}/${vp.name}-${theme}-${p.name}.png` });
        await page.close();
      }
      await ctx.close();
    }
  }
  await browser.close();
})();
```

- [ ] **Step 6: Verify in dev** — with `make dev` running, capture and inspect: text renders in Inter (compare "ř", "ě" glyphs render, no fallback serif), no network requests to external font hosts (check dev tools or `grep -r "fonts.googleapis\|fonts.gstatic" web/dist` after a build — must be empty).

```bash
cd web && node scripts/ui-capture.cjs
```

- [ ] **Step 7: Run lint + unit/component tests**

```bash
make lint && cd web && npx vitest run
```
Expected: PASS (CSS/import-only change).

- [ ] **Step 8: Build + re-baseline visual tests (font change affects every snapshot)**

```bash
make build && cd web && timeout 600 npx playwright test tests/e2e && make test-fe-visual-update && make test-fe-visual-browse
```
Eyeball the gallery: only font rendering changes, no layout breakage.

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat(ui): self-host Inter + Bricolage Grotesque via Fontsource"
```

### Task 2: Brand palette refresh + user-bubble unification

**Files:**
- Modify: `web/src/styles/variables.css` (brand block 34-45, user colors 69-73, gradients 115-129, accent aliases 92-95, light overrides 242-250)
- Modify: `web/src/styles/components/messages.css` (selection override)

**Interfaces:**
- Produces: new `--color-brand-*` values; `--bg-user: var(--color-brand-600)`; `--color-user-500` DELETED (grep confirms no consumers).

- [ ] **Step 1: Replace the brand palette block in `variables.css`** (dark `:root`, lines 34-45):

```css
    /* ----------------------------------------
       Color Palette - Brand (Indigo)
       ---------------------------------------- */
    --color-brand-300: #a9a6f7;     /* Subtle accent text on dark */
    --color-brand-400: #7b78f0;     /* Accent hover (dark) */
    --color-brand-500: #5753e8;     /* Primary accent */
    --color-brand-600: #4a46c6;     /* Pressed state / user bubble */
    --color-brand-700: #3f3ba8;     /* Dark accent */
    --color-brand-800: #34318a;     /* Version banner bg */
    --color-brand-900: #2b2973;     /* Darker variant */
    --color-brand-950: #1d1b4f;     /* Darkest - banner text */

    /* Purple shades (for gradients) */
    --color-purple-500: #7c5ce8;    /* Gradient middle */
    --color-purple-400: #9b6cf2;    /* Gradient end */
```

- [ ] **Step 2: Replace the user-color block** (lines 69-73). Delete `--color-user-500`, repoint `--bg-user`:

```css
    --color-info-500: #3b82f6;      /* Info blue */
    --color-user-text: #ffffff;     /* User message text */
    --color-user-text-secondary: rgba(255, 255, 255, 0.85); /* User message secondary text */
    --color-user-overlay: rgba(255, 255, 255, 0.2); /* User message overlay bg */
```
and in the Semantic Aliases block change `--bg-user: var(--color-user-500);` to:

```css
    --bg-user: var(--color-brand-600);
```

- [ ] **Step 3: Update accent-muted for the new hue** — dark `:root`: `--accent-muted: rgba(87, 83, 232, 0.15);` light block: `--accent-muted: rgba(87, 83, 232, 0.1);`. Update `--shadow-glow-accent` rgba to `rgba(124, 92, 232, 0.5)` dark / `rgba(87, 83, 232, 0.3)` light (still used by scroll FAB etc. until Task 7 removes it from avatars).

- [ ] **Step 4: Check for stray consumers**

```bash
grep -rn "color-user-500\|user-bg\b" web/src --include="*.css" --include="*.ts"
```
Expected: only the `--user-bg: var(--bg-user)` legacy alias in variables.css remains; fix anything else found by pointing it at `--bg-user`.

- [ ] **Step 5: Add selection override in `messages.css`** (append near `.message.user .message-content` rules):

```css
.message.user .message-content::selection,
.message.user .message-content *::selection {
    background-color: rgba(255, 255, 255, 0.3);
    color: inherit;
}
```

- [ ] **Step 6: Verify contrast** — `#4a46c6` vs white is ~7.4:1 (AA+AAA). Spot-check with the capture script in both themes: user bubbles now indigo, no remaining blue.

- [ ] **Step 7: Lint, tests, visual re-baseline, commit**

```bash
make lint && cd web && npx vitest run && make build && cd web && timeout 600 npx playwright test tests/e2e && make test-fe-visual-update
git add -A && git commit -m "feat(ui): refreshed indigo brand palette, user bubble joins brand family"
```

### Task 3: Neutral/contrast fixes (hover vs border, scrollbar, overlays)

**Files:**
- Modify: `web/src/styles/variables.css` (neutrals 22-30 dark, 232-240 light; overlay 108-109, 256-257)
- Modify: `web/src/styles/base.css:57-72` (scrollbar)
- Modify: `web/src/styles/components/popups.css` (backdrop blur on the overlay container)

- [ ] **Step 1: Dark neutrals** — in `:root` set: `--color-neutral-800: #242424;`, `--color-neutral-700: #2a2a2a;`, `--color-neutral-600: #383838;` (950/900/850/400/300/100 unchanged).

- [ ] **Step 2: Light neutrals** — in `[data-theme="light"]` set: `--color-neutral-900: #f8f9fb;`, `--color-neutral-800: #eceef1;`, `--color-neutral-700: #eef0f4;`, `--color-neutral-600: #e2e5ea;` (850/400/300/100 unchanged).

- [ ] **Step 3: Scrollbar token** — add `--scrollbar-thumb: var(--bg-tertiary);` to `:root` and `--scrollbar-thumb: #d1d5db;` to the light block; change `base.css` `::-webkit-scrollbar-thumb` to `background-color: var(--scrollbar-thumb);`.

- [ ] **Step 4: Overlays** — `:root`: `--overlay-bg: rgba(0, 0, 0, 0.55);` light block: `--overlay-bg: rgba(0, 0, 0, 0.45);`. Find the fullscreen popup backdrop rule:

```bash
grep -n "overlay-bg" web/src/styles -r
```
On the `.info-popup` (and any `.modal-backdrop`/`.sidebar-overlay` rule using it) add:

```css
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
```

- [ ] **Step 5: Verify with capture script** — hover a sidebar row in dev (manually or via screenshot of `:hover` forced in devtools): hover fill and borders visibly distinct in both themes; light scrollbar visible; settings backdrop blurs instead of blacking out.

- [ ] **Step 6: Lint, tests, visual re-baseline, commit**

```bash
make lint && cd web && npx vitest run && make build && cd web && timeout 600 npx playwright test tests/e2e && make test-fe-visual-update
git add -A && git commit -m "fix(ui): separate hover/border neutrals, visible light scrollbar, blurred overlays"
```

### Task 4: Type-scale token cleanup + motion tokens

**Files:**
- Modify: `web/src/styles/variables.css:174-186` and all `var(--font-size-*)` consumers (sweep)
- Modify: `web/src/styles/base.css:21-27` (body), `web/src/styles/components/messages.css` (message line-height)

**Interfaces:**
- Produces: `--font-size-ui` (14px, new), `--font-size-base` now 16px, `--line-height-relaxed: 1.6`, motion tokens `--duration-fast/base/slow`, `--ease-out`, `--ease-in-out`.

- [ ] **Step 1: Ordered sweep (order matters — do exactly this sequence):**

```bash
cd web/src
grep -rl "font-size-base" . | xargs sed -i '' 's/var(--font-size-base)/var(--font-size-ui)/g'
grep -rl "font-size-lg" . | xargs sed -i '' 's/var(--font-size-lg)/var(--font-size-base)/g'
```

- [ ] **Step 2: Update the token definitions** in `variables.css`:

```css
    --font-size-2xs: 0.5rem;     /* 8px - dropdown arrows */
    --font-size-xs: 0.6875rem;   /* 11px */
    --font-size-sm: 0.75rem;     /* 12px */
    --font-size-badge: 0.7rem;   /* ~11px - badge numbers */
    --font-size-ui: 0.875rem;    /* 14px - UI chrome default */
    --font-size-md: 0.9375rem;   /* 15px */
    --font-size-base: 1rem;      /* 16px - body/message text */
    --font-size-xl: 1.125rem;    /* 18px */
    --font-size-2xl: 1.25rem;    /* 20px */
    --font-size-3xl: 1.5rem;     /* 24px */
    --font-size-4xl: 2rem;       /* 32px */

    --line-height: 1.45;
    --line-height-relaxed: 1.6;
```
(`--font-size-lg` is deleted; the sweep removed all consumers. Verify: `grep -rn "font-size-lg" web/src` returns nothing.)

- [ ] **Step 3: Apply line-heights** — `base.css` body keeps `line-height: var(--line-height);` (now 1.45). In `messages.css` add to `.message-content`:

```css
    line-height: var(--line-height-relaxed);
```

- [ ] **Step 4: Add motion tokens** to `variables.css` (new section before Z-Index):

```css
    /* ----------------------------------------
       Motion
       ---------------------------------------- */
    --duration-fast: 120ms;
    --duration-base: 180ms;
    --duration-slow: 240ms;
    --ease-out: cubic-bezier(0.2, 0, 0, 1);
    --ease-in-out: cubic-bezier(0.4, 0, 0.2, 1);
```

- [ ] **Step 5: Verify no rendered size changed unintentionally** — capture script before/after diff on the four main pages; the only expected change is message line-height (1.5 -> 1.6) and UI chrome line-height (1.5 -> 1.45).

- [ ] **Step 6: Full phase-boundary test run + commit**

```bash
make lint && make test-all && make test-fe-visual-update
git add -A && git commit -m "refactor(ui): semantic type-scale tokens, relaxed message line-height, motion tokens"
```

---

## Phase 2 — Chat surface

### Task 5: ChatHeader component (regular conversations) + cost relocation

**Files:**
- Create: `web/src/components/ChatHeader.ts`
- Create: `web/src/styles/components/chat-header.css` (import in `main.css` after `layout.css`)
- Modify: `web/src/core/init.ts:99-106` (shell: add header mount, cost chip in mobile header)
- Modify: `web/src/core/conversation.ts` (render header on conversation select/clear)
- Modify: wherever `#conversation-cost` is updated (find with grep) — keep the id on the new chip
- Test: `web/tests/component/ChatHeader.test.ts` (new)

**Interfaces:**
- Produces:
  - `createChatHeader(opts: ChatHeaderOptions): HTMLElement` where `ChatHeaderOptions = { title: string; extraClass?: string; emoji?: string; onBack?: () => void; onRenameCommit?: (title: string) => void; actions?: HTMLElement[] }`
  - `renderChatHeader(opts: ChatHeaderOptions | null): void` — renders into `#chat-header` (null hides it)
  - `updateChatHeaderTitle(title: string): void`
  - Cost chip keeps `id="conversation-cost"` (desktop, inside header) and a mirrored `#conversation-cost-mobile` chip in `.mobile-header`.

- [ ] **Step 1: Write failing component test** `web/tests/component/ChatHeader.test.ts` (pattern-match `Sidebar.test.ts`: shell injection + assertions):

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { createChatHeader, renderChatHeader, updateChatHeaderTitle } from '@/components/ChatHeader';

describe('ChatHeader', () => {
  beforeEach(() => {
    document.body.innerHTML = '<header id="chat-header" class="chat-header hidden"></header>';
  });

  it('renders title and actions', () => {
    const action = document.createElement('button');
    action.className = 'test-action';
    renderChatHeader({ title: 'My chat', actions: [action] });
    const header = document.getElementById('chat-header')!;
    expect(header.classList.contains('hidden')).toBe(false);
    expect(header.querySelector('.chat-header-title')!.textContent).toBe('My chat');
    expect(header.querySelector('.test-action')).not.toBeNull();
    expect(header.querySelector('#conversation-cost')).not.toBeNull();
  });

  it('hides when rendered with null', () => {
    renderChatHeader({ title: 'x' });
    renderChatHeader(null);
    expect(document.getElementById('chat-header')!.classList.contains('hidden')).toBe(true);
  });

  it('commits inline rename on Enter', () => {
    const onRenameCommit = vi.fn();
    renderChatHeader({ title: 'Old', onRenameCommit });
    const title = document.querySelector<HTMLElement>('.chat-header-title')!;
    title.click();
    const input = document.querySelector<HTMLInputElement>('.chat-header-title-input')!;
    input.value = 'New title';
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(onRenameCommit).toHaveBeenCalledWith('New title');
  });

  it('renders back button and emoji for program variant', () => {
    const onBack = vi.fn();
    renderChatHeader({ title: 'Pushups', emoji: '🤼', onBack, extraClass: 'sports-program-header' });
    const header = document.getElementById('chat-header')!;
    expect(header.classList.contains('sports-program-header')).toBe(true);
    header.querySelector<HTMLElement>('.chat-header-back')!.click();
    expect(onBack).toHaveBeenCalled();
  });

  it('updates title in place', () => {
    renderChatHeader({ title: 'One' });
    updateChatHeaderTitle('Two');
    expect(document.querySelector('.chat-header-title')!.textContent).toBe('Two');
  });
});
```

- [ ] **Step 2: Run to verify failure** — `cd web && npx vitest run tests/component/ChatHeader.test.ts` — FAIL (module not found).

- [ ] **Step 3: Implement `web/src/components/ChatHeader.ts`:**

```ts
/**
 * Shared conversation header: title (inline-renameable), optional back
 * button/emoji for program variants, cost chip, action buttons.
 */

export interface ChatHeaderOptions {
  title: string;
  extraClass?: string;
  emoji?: string;
  onBack?: () => void;
  onRenameCommit?: (title: string) => void;
  actions?: HTMLElement[];
}

const BACK_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 18l-6-6 6-6"/></svg>`;

function getHeaderEl(): HTMLElement | null {
  return document.getElementById('chat-header');
}

export function createChatHeader(opts: ChatHeaderOptions): HTMLElement {
  const header = document.createElement('div');
  header.className = 'chat-header-inner';

  if (opts.onBack) {
    const back = document.createElement('button');
    back.className = 'btn-icon chat-header-back';
    back.setAttribute('aria-label', 'Back');
    back.innerHTML = BACK_ICON;
    back.addEventListener('click', opts.onBack);
    header.appendChild(back);
  }

  if (opts.emoji) {
    const emoji = document.createElement('span');
    emoji.className = 'chat-header-emoji';
    emoji.textContent = opts.emoji;
    header.appendChild(emoji);
  }

  const title = document.createElement('h2');
  title.className = 'chat-header-title';
  title.textContent = opts.title;
  if (opts.onRenameCommit) {
    title.classList.add('renameable');
    title.title = 'Rename conversation';
    title.addEventListener('click', () => startInlineRename(title, opts.onRenameCommit!));
  }
  header.appendChild(title);

  const spacer = document.createElement('div');
  spacer.className = 'chat-header-spacer';
  header.appendChild(spacer);

  const cost = document.createElement('span');
  cost.id = 'conversation-cost';
  cost.className = 'chat-header-cost';
  header.appendChild(cost);

  for (const action of opts.actions ?? []) {
    header.appendChild(action);
  }
  return header;
}

function startInlineRename(title: HTMLElement, commit: (t: string) => void): void {
  if (title.querySelector('input')) return;
  const current = title.textContent ?? '';
  const input = document.createElement('input');
  input.className = 'chat-header-title-input';
  input.value = current;
  title.textContent = '';
  title.appendChild(input);
  input.focus();
  input.select();
  const finish = (save: boolean) => {
    const value = input.value.trim();
    title.textContent = save && value ? value : current;
    if (save && value && value !== current) commit(value);
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') finish(true);
    if (e.key === 'Escape') finish(false);
  });
  input.addEventListener('blur', () => finish(true));
}

export function renderChatHeader(opts: ChatHeaderOptions | null): void {
  const el = getHeaderEl();
  if (!el) return;
  el.innerHTML = '';
  el.className = 'chat-header';
  if (!opts) {
    el.classList.add('hidden');
    return;
  }
  if (opts.extraClass) el.classList.add(opts.extraClass);
  el.appendChild(createChatHeader(opts));
}

export function updateChatHeaderTitle(title: string): void {
  const el = getHeaderEl()?.querySelector('.chat-header-title');
  if (el && !el.querySelector('input')) el.textContent = title;
}
```

- [ ] **Step 4: Run test — PASS.** `cd web && npx vitest run tests/component/ChatHeader.test.ts`

- [ ] **Step 5: Mount in shell** (`init.ts`) — after `.mobile-header`, before `#messages`:

```html
<header id="chat-header" class="chat-header hidden"></header>
```
Add to `.mobile-header` (before the closing tag): `<span id="conversation-cost-mobile" class="chat-header-cost"></span>`. Remove `<div id="conversation-cost" class="conversation-cost-display"></div>` from the input area (the id now lives in the header chip).

- [ ] **Step 6: Wire rendering** — in `web/src/core/conversation.ts`, at the point a regular conversation becomes active (find where `#current-chat-title` / `setActiveConversation` is updated), call:

```ts
renderChatHeader({
  title: conversation.title,
  onRenameCommit: (newTitle) => renameConversation(conversation.id, newTitle),
  actions: [buildArchiveButton(conversation.id), buildDeleteButton(conversation.id)],
});
```
`buildArchiveButton`/`buildDeleteButton` are small local helpers creating `btn-icon` buttons that reuse the existing archive/delete flows from `Sidebar.ts` (import the same handlers the sidebar buttons call; extract them into exported functions if they're currently inline). On home/dashboard routes call `renderChatHeader(null)`.

- [ ] **Step 7: Cost updates** — find writers:

```bash
grep -rn "conversation-cost" web/src --include="*.ts"
```
Update the writer so it writes the formatted cost to BOTH `#conversation-cost` and `#conversation-cost-mobile`.

- [ ] **Step 8: CSS `chat-header.css`:**

```css
/* Chat header - desktop conversation header */
.chat-header {
    flex-shrink: 0;
    border-bottom: 1px solid var(--border);
    background-color: var(--bg-primary);
    padding: 0 var(--space-6);
}

.chat-header.hidden { display: none; }

.chat-header-inner {
    max-width: var(--message-max-width);
    margin: 0 auto;
    height: 52px;
    display: flex;
    align-items: center;
    gap: var(--space-3);
}

.chat-header-title {
    font-size: var(--font-size-md);
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.chat-header-title.renameable { cursor: text; }

.chat-header-title-input {
    font: inherit;
    color: inherit;
    background: var(--bg-secondary);
    border: 1px solid var(--accent);
    border-radius: var(--radius-xs);
    padding: 2px var(--space-2);
    min-width: 240px;
}

.chat-header-spacer { flex: 1; }

.chat-header-cost {
    font-size: var(--font-size-sm);
    color: var(--text-muted);
    background: var(--bg-secondary);
    border: 1px solid var(--border-light);
    border-radius: var(--radius-full);
    padding: 2px var(--space-2-5);
    white-space: nowrap;
}

.chat-header-cost:empty { display: none; }

.chat-header-emoji { font-size: var(--font-size-xl); }

@media (max-width: 768px) {
    .chat-header { display: none; }
    #conversation-cost-mobile { margin-left: auto; }
}
```
Import in `main.css` after `layout.css`: `@import './styles/components/chat-header.css';` (match existing import path style).

- [ ] **Step 9: Lint + unit/component + E2E; fix any test referencing `.conversation-cost-display`** (grep `conversation-cost` in `web/tests/`). Re-baseline visuals. Commit `feat(ui): desktop chat header with title, rename, cost chip and actions`.

### Task 6: Program headers unify onto ChatHeader

**Files:**
- Modify: `web/src/components/SportsDashboard.ts:247-283`, `web/src/components/LanguageDashboard.ts:231-267`, `web/src/components/CommandCenter.ts:549-571`
- Modify: `web/src/styles/components/sports.css`, `language.css`, `agents.css` (delete bespoke header layout rules)
- Test: existing visual suites

- [ ] **Step 1:** Rewrite `createSportsProgramHeader(program, onBack, onReset)` to return `createChatHeader({ title: program.name, emoji: program.emoji, onBack, extraClass: 'sports-program-header', actions: [resetBtn] })` where `resetBtn` keeps class `sports-reset-btn` and its existing confirm-dialog handler. Same pattern for language (`language-program-header`, `.language-reset-btn`, label "New Lesson") and agents (`agent-conversation-header`, edit button `.agent-conv-edit`).
- [ ] **Step 2:** These headers currently mount inside the messages area — switch call sites to `renderChatHeader({...})` into the shared `#chat-header` mount instead, so program pages and regular chats use the same slot (check `.messages.has-sticky-header` usage; remove that mechanism if the sticky header moves out of `.messages`).
- [ ] **Step 3:** Delete now-dead layout CSS for `.sports-program-header`/`.language-program-header`/`.agent-conversation-header` positioning (keep the class names as variant hooks; keep `.sports-reset-btn`/`.language-reset-btn` button styles or restyle them as `btn-icon`-with-label secondary buttons).
- [ ] **Step 4:** On mobile the program header must REMAIN visible (spec: back/Reset stay) — add:

```css
@media (max-width: 768px) {
    .chat-header.sports-program-header,
    .chat-header.language-program-header,
    .chat-header.agent-conversation-header { display: block; }
}
```
- [ ] **Step 5:** Run `cd web && npx vitest run && timeout 600 npx playwright test` (after `make build`); fix selectors in `sports.visual.ts`/`agents.spec.ts` if the header moved in the DOM (they select by class, which is preserved). Re-baseline visuals. Commit `refactor(ui): unify program conversation headers onto ChatHeader`.

### Task 7: Bubble widths, avatar cleanup, top spacing

**Files:**
- Modify: `web/src/styles/components/messages.css` (user wrapper 115-119, assistant avatar 84-87, mobile block 799-814)
- Modify: `web/src/styles/layout.css:101-117` (.messages padding)

- [ ] **Step 1:** User bubble cap — change `.message.user .message-content-wrapper` `max-width` from `calc(100% - 48px)` to `min(70%, calc(100% - 48px))`.
- [ ] **Step 2:** Remove avatar glow — in `.message.assistant .message-avatar` delete the `box-shadow: var(--shadow-glow-accent);` line.
- [ ] **Step 3:** Mobile block (messages.css 799-814) becomes:

```css
@media (max-width: 768px) {
    .message { gap: 0; }

    .message-avatar { display: none; }

    .message-content { max-width: 100%; padding: 10px 14px; }

    .message.user .message-content-wrapper { max-width: 85%; }
}
```
- [ ] **Step 4:** `.messages` top padding under the new header: keep `padding: var(--space-6)`; verify first message no longer touches the viewport/header edge with the capture script (all 4 variants).
- [ ] **Step 5:** Lint, vitest, E2E, visual re-baseline (mobile snapshots change significantly). Commit `feat(ui): cap user bubble width, remove avatar glow, reclaim mobile avatar gutter`.

### Task 8: Welcome / empty state with suggested prompts

**Files:**
- Modify: `web/src/components/WelcomeMessage.ts`
- Modify: `web/src/core/events.ts` (delegated chip click)
- Modify: `web/src/styles/components/messages.css` (.welcome-message block)
- Test: `web/tests/component/Messages.test.ts:239`, `web/tests/e2e/sync.spec.ts:211`

**Interfaces:**
- Produces: `.welcome-prompt-chip[data-prompt]` buttons; headline text becomes `What can I help with?` (tests updated to match).

- [ ] **Step 1: Update the component test FIRST** (`Messages.test.ts:239`): assert `"What can I help with?"` and that 4 `.welcome-prompt-chip` elements render. Run — FAIL.
- [ ] **Step 2: Rewrite `WelcomeMessage.ts`:**

```ts
import { escapeHtml } from '../utils/dom'; // use the project's existing escape helper (check utils/dom.ts export name)

const SUGGESTED_PROMPTS: string[] = [
  'Summarize this link: ',
  'Plan my week',
  'What should I train today?',
  'Quiz me in Italian',
];

export function renderWelcomeMessageHtml(): string {
  const chips = SUGGESTED_PROMPTS.map(
    (p) => `<button class="welcome-prompt-chip" data-prompt="${escapeHtml(p)}">${escapeHtml(p)}</button>`,
  ).join('');
  return `
    <div class="welcome-message">
      <h2>What can I help with?</h2>
      <div class="welcome-prompts">${chips}</div>
    </div>`;
}
```
- [ ] **Step 3: Delegated click in `events.ts`** (same pattern as `#menu-btn` wiring):

```ts
document.addEventListener('click', (e) => {
  const chip = (e.target as HTMLElement).closest<HTMLElement>('.welcome-prompt-chip');
  if (!chip) return;
  const input = document.getElementById('message-input') as HTMLTextAreaElement | null;
  if (!input) return;
  input.value = chip.dataset.prompt ?? '';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.focus();
});
```
- [ ] **Step 4: CSS** — replace `.welcome-message` block in messages.css:

```css
.welcome-message {
    text-align: center;
    margin: auto;              /* vertical centering inside flex .messages */
    padding: var(--space-8) var(--space-6);
    color: var(--text-secondary);
    max-width: 560px;
}

.welcome-message h2 {
    font-family: var(--font-family-display);
    font-size: var(--font-size-4xl);
    font-weight: 600;
    letter-spacing: -0.01em;
    margin-bottom: var(--space-6);
    color: var(--text-primary);
}

.welcome-prompts {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: var(--space-2);
}

.welcome-prompt-chip {
    font: inherit;
    font-size: var(--font-size-ui);
    color: var(--text-secondary);
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-full);
    padding: var(--space-2) var(--space-4);
    cursor: pointer;
    transition: background-color var(--transition-fast), border-color var(--transition-fast);
}

.welcome-prompt-chip:hover {
    background: var(--bg-tertiary);
    border-color: var(--text-muted);
}
```
- [ ] **Step 5: Update E2E strings** — `sync.spec.ts:211` `text=Welcome to Moneypenny` -> `text=What can I help with?`. Grep for other occurrences: `grep -rn "Welcome to Moneypenny\|Start a conversation" web/tests web/src`. `.welcome-message` selectors stay valid.
- [ ] **Step 6:** vitest + E2E + visual re-baseline. Commit `feat(ui): welcome empty state with suggested prompts (drops Gemini mention)`.

### Task 9: Mobile message-actions collapse

**Files:**
- Modify: `web/src/components/messages/actions.ts:151-187`
- Modify: `web/src/styles/components/messages.css:132-149`
- Modify: `web/src/core/events.ts` (delegated toggle)

- [ ] **Step 1:** In `createMessageActions`, after the time span, insert an overflow toggle (mobile-only via CSS):

```ts
const overflowBtn = document.createElement('button');
overflowBtn.className = 'message-actions-overflow btn-icon';
overflowBtn.setAttribute('aria-label', 'Message actions');
overflowBtn.textContent = '⋯';
container.appendChild(overflowBtn);
```
Wrap the existing action buttons in a `<span class="message-actions-buttons">` container.
- [ ] **Step 2:** Delegated toggle in `events.ts`: click on `.message-actions-overflow` toggles `.expanded` on the parent `.message-actions`.
- [ ] **Step 3:** CSS — desktop unchanged (hover reveal). Replace the `@media (hover: none)` block:

```css
.message-actions-overflow { display: none; }

@media (hover: none) {
    .message-actions { opacity: 1; }
    .message-actions-overflow { display: inline-flex; min-width: 44px; min-height: 32px; }
    .message-actions .message-actions-buttons { display: none; }
    .message-actions.expanded .message-actions-buttons { display: inline-flex; gap: var(--space-2); }
}
```
- [ ] **Step 4:** Check `message-actions.spec.ts` (desktop viewport — unaffected) and `mobile.visual.ts` (re-baseline). Commit `feat(ui): collapse message actions behind overflow toggle on touch devices`.

---

## Phase 3 — Compose card

### Task 10: Unified compose card markup + styles

**Files:**
- Modify: `web/src/core/init.ts:108-151` (input area structure)
- Modify: `web/src/styles/components/input.css`

**Interfaces:**
- Produces DOM (ids preserved):

```html
<div class="input-area">
  <div class="input-wrapper">
    <div id="file-preview" class="file-preview hidden"></div>
    <div id="input-container" class="input-container">
      <textarea id="message-input" placeholder="Type your message..." rows="1"></textarea>
      <div class="input-toolbar">
        <div class="toolbar-left"> [model-selector] [#stream-btn] [#search-btn] [#imagegen-btn] [#anonymous-btn] </div>
        <div class="toolbar-right"> [#voice-btn] [#attach-btn] [#send-btn] </div>
      </div>
    </div>
    <input type="file" id="file-input" ...>
  </div>
</div>
```

- [ ] **Step 1:** Restructure `init.ts` shell to the layout above — move `.input-toolbar` inside `#input-container` below the textarea; move `#send-btn` into `.toolbar-right`. All ids/classes preserved.
- [ ] **Step 2:** Rewrite the container rules in `input.css`:

```css
.input-container {
    display: flex;
    flex-direction: column;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
    transition: border-color var(--transition-fast);
}

.input-container:focus-within { border-color: var(--accent); }

.input-container textarea {
    background: transparent;
    border: none;
    outline: none;
    resize: none;
    padding: var(--space-2) var(--space-1) var(--space-1);
}

.input-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-top: var(--space-1);
}
```
Delete the old standalone toolbar/textarea border rules that conflict (`grep -n "input-toolbar\|input-container\|#message-input" web/src/styles/components/input.css` and reconcile).
- [ ] **Step 3:** Check every place that referenced the old structure: `MessageInput.ts` (`#send-btn` lookups — unchanged), `chat.visual.ts:81-87` (`.input-toolbar` screenshot — still exists), approval overlay `setInputBlockedForApproval` (injects into `#input-container` — verify it still overlays correctly).
- [ ] **Step 4:** vitest (`message-input.test.ts`), E2E (fixtures use `#message-input`/`#send-btn`), visual re-baseline. Commit `feat(ui): unified compose card with integrated toolbar`.

### Task 11: Model dropdown polish (chevron, descriptions, keyboard nav, ARIA)

**Files:**
- Modify: `web/src/components/ModelSelector.ts` (13-45, 139-165)
- Modify: `web/src/core/init.ts:112-118` (chevron icon), `web/src/utils/icons.ts` (add CHEVRON_DOWN_ICON if absent)
- Modify: `web/src/styles/components/input.css` (model dropdown styles)
- Test: `web/tests/e2e/chat/model-selection.spec.ts` (must stay green — selectors preserved)

- [ ] **Step 1:** Replace `<span class="dropdown-arrow">▼</span>` with `${CHEVRON_DOWN_ICON}` (16px stroke chevron svg added to `icons.ts` if not present; grep first).
- [ ] **Step 2:** In `renderModelDropdown()`, render richer rows (keep `.model-option`, `data-model-id`, `.model-name`, `.model-check`):

```ts
option.innerHTML = `
  <div class="model-option-text">
    <span class="model-name">${escapeHtml(model.name)}</span>
    ${model.description ? `<span class="model-option-desc">${escapeHtml(model.description)}</span>` : ''}
  </div>
  ${isSelected ? `<span class="model-check">${CHECK_ICON}</span>` : ''}`;
```
Check `types/api.ts` `Model` interface for a `description` field first; if the API doesn't provide one, add `description?: string` to the interface and render conditionally (backend addition is out of scope).
- [ ] **Step 3:** ARIA + keyboard in `initModelSelector()`: `#model-selector-btn` gets `aria-haspopup="listbox"` + `aria-expanded` synced on toggle; `#model-dropdown` gets `role="listbox"`, options `role="option"` + `aria-selected`. Keydown handler on the button/dropdown: ArrowDown/ArrowUp move a `.focused` class, Enter activates the focused option (reuse the existing `[data-model-id]` click path), Escape closes and refocuses the button.
- [ ] **Step 4:** CSS: dropdown becomes a card (`--radius-md`, `--shadow-lg`, 1px border, `--bg-secondary`), options two-line with `.model-option-desc { font-size: var(--font-size-sm); color: var(--text-muted); }`, `.focused`/`:hover` = `--bg-hover`.
- [ ] **Step 5:** Run `model-selection.spec.ts` + `planner.spec.ts` (both assert `#current-model-name` text — unchanged). Visual re-baseline (`model-selector.png`). Commit `feat(ui): model dropdown with descriptions, keyboard navigation and ARIA`.

### Task 12: Toggle affordances + send-button states

**Files:**
- Modify: `web/src/core/init.ts:119-139` (aria/title on toggles), `web/src/core/toolbar.ts` (aria-pressed sync)
- Modify: `web/src/styles/components/buttons.css:100-163`

- [ ] **Step 1:** Every `.btn-toolbar` toggle gets `title` + `aria-label` + `aria-pressed` in the shell markup: stream-btn "Live streaming responses", search-btn "Force web search", imagegen-btn "Generate an image", anonymous-btn "Incognito — don't save to memory", voice-btn "Dictate", attach-btn "Attach files". In `toolbar.ts`, wherever `.active` is toggled, mirror `btn.setAttribute('aria-pressed', String(isActive))`.
- [ ] **Step 2:** Active state becomes a visible pill (buttons.css `.btn-toolbar.active`):

```css
.btn-toolbar.active {
    color: var(--accent);
    background-color: var(--accent-muted);
    border-radius: var(--radius-sm);
}
```
- [ ] **Step 3:** Send-button states (buttons.css 137-163): ready = filled `--accent`, white icon; disabled = `background-color: var(--bg-tertiary); color: var(--text-muted); opacity: 1;` (replaces the accent-at-35%-opacity look that reads as broken). `.btn-stop` unchanged. Verify the upload ring (`.uploading`/`.processing`, buttons.css:220-283) still renders over both states by manually triggering a large file upload in dev.
- [ ] **Step 4:** vitest + E2E (stream-btn `aria-pressed` already asserted in fixtures — now also on others, no conflicts) + visual re-baseline. Commit `feat(ui): toolbar toggle affordances and distinct send-button states`.

### Task 13: Mobile toolbar collapse

**Files:**
- Modify: `web/src/core/init.ts` (wrap toggles + options button), `web/src/core/toolbar.ts` (popover toggle)
- Modify: `web/src/styles/components/input.css`

- [ ] **Step 1:** Wrap the four toggles in `<div class="toolbar-toggles">` and add before it `<button id="toolbar-options-btn" class="btn-toolbar" aria-label="Message options" aria-expanded="false">${SLIDERS_ICON}</button>` (add a sliders/tune svg to icons.ts).
- [ ] **Step 2:** `toolbar.ts`: clicking `#toolbar-options-btn` toggles `.open` on `.toolbar-toggles` + syncs `aria-expanded`; any outside click closes it.
- [ ] **Step 3:** CSS:

```css
#toolbar-options-btn { display: none; }

@media (max-width: 768px) {
    #toolbar-options-btn { display: inline-flex; }

    .toolbar-toggles {
        display: none;
        position: absolute;
        bottom: calc(100% + var(--space-2));
        left: 0;
        flex-direction: column;
        background: var(--bg-secondary);
        border: 1px solid var(--border);
        border-radius: var(--radius-md);
        box-shadow: var(--shadow-lg);
        padding: var(--space-1);
        z-index: var(--z-dropdown);
    }

    .toolbar-toggles.open { display: flex; }
}
```
(`.toolbar-left` gets `position: relative` for anchoring. Model selector stays inline on mobile.)
- [ ] **Step 4:** In the popover, toggles show icon + text label: add `<span class="toolbar-toggle-label">` next to each icon, hidden on desktop (`display:none`), shown in the mobile popover.
- [ ] **Step 5:** `mobile.spec.ts` + `mobile.visual.ts` runs (fixtures `enableStreaming` clicks `#stream-btn` — on the default 1280px viewport it stays inline, so E2E unaffected; mobile visual re-baselined). Full phase-boundary `make test-all`. Commit `feat(ui): collapse compose toggles into options popover on mobile`.

---

## Phase 4 — Sidebar

### Task 14: Date-grouped conversation list + relative times

**Files:**
- Modify: `web/src/components/Sidebar.ts:156-302`
- Create: `web/src/utils/relative-time.ts` (+ check `grep -rn "formatRelative\|timeAgo" web/src` first — reuse if one exists)
- Modify: `web/src/styles/components/sidebar.css`
- Test: `web/tests/unit/relative-time.test.ts` (new), `web/tests/component/Sidebar.test.ts`

**Interfaces:**
- Produces: `formatRelativeTime(iso: string, now?: Date): string` -> `"now" | "5m" | "3h" | "2d" | "3w" | "4mo" | "1y"`; `groupForDate(iso: string, now?: Date): 'Today' | 'Yesterday' | 'Previous 7 days' | 'Previous 30 days' | 'Older'`.

- [ ] **Step 1: Failing unit test** `web/tests/unit/relative-time.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { formatRelativeTime, groupForDate } from '@/utils/relative-time';

const NOW = new Date('2026-08-18T12:00:00Z');

describe('formatRelativeTime', () => {
  it.each([
    ['2026-08-18T11:59:40Z', 'now'],
    ['2026-08-18T11:55:00Z', '5m'],
    ['2026-08-18T09:00:00Z', '3h'],
    ['2026-08-16T12:00:00Z', '2d'],
    ['2026-07-28T12:00:00Z', '3w'],
    ['2026-04-18T12:00:00Z', '4mo'],
    ['2025-08-01T12:00:00Z', '1y'],
  ])('%s -> %s', (iso, expected) => {
    expect(formatRelativeTime(iso, NOW)).toBe(expected);
  });
});

describe('groupForDate', () => {
  it.each([
    ['2026-08-18T01:00:00Z', 'Today'],
    ['2026-08-17T23:00:00Z', 'Yesterday'],
    ['2026-08-13T12:00:00Z', 'Previous 7 days'],
    ['2026-07-25T12:00:00Z', 'Previous 30 days'],
    ['2026-01-01T12:00:00Z', 'Older'],
  ])('%s -> %s', (iso, expected) => {
    expect(groupForDate(iso, NOW)).toBe(expected);
  });
});
```
Run: FAIL (module missing).
- [ ] **Step 2: Implement `web/src/utils/relative-time.ts`:**

```ts
const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;

export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  const diff = now.getTime() - new Date(iso).getTime();
  if (diff < MINUTE_MS) return 'now';
  if (diff < HOUR_MS) return `${Math.floor(diff / MINUTE_MS)}m`;
  if (diff < DAY_MS) return `${Math.floor(diff / HOUR_MS)}h`;
  if (diff < 7 * DAY_MS) return `${Math.floor(diff / DAY_MS)}d`;
  if (diff < 30 * DAY_MS) return `${Math.floor(diff / (7 * DAY_MS))}w`;
  if (diff < 365 * DAY_MS) return `${Math.floor(diff / (30 * DAY_MS))}mo`;
  return `${Math.floor(diff / (365 * DAY_MS))}y`;
}

export function groupForDate(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday.getTime() - DAY_MS);
  if (date >= startOfToday) return 'Today';
  if (date >= startOfYesterday) return 'Yesterday';
  if (date >= new Date(startOfToday.getTime() - 7 * DAY_MS)) return 'Previous 7 days';
  if (date >= new Date(startOfToday.getTime() - 30 * DAY_MS)) return 'Previous 30 days';
  return 'Older';
}
```
Run: PASS. (Note: test dates near midnight are UTC vs local sensitive — the fixtures above keep a wide margin.)
- [ ] **Step 3: Group in `renderConversationsList()`** — conversations arrive sorted by `updated_at` desc; while iterating, emit `<div class="conversation-group-label">${label}</div>` whenever `groupForDate(conv.updated_at)` changes. Inside `renderConversationItem`, after `.conversation-title`, add `<span class="conversation-time">${formatRelativeTime(conv.updated_at)}</span>`.
- [ ] **Step 4: CSS** (sidebar.css):

```css
.conversation-group-label {
    font-size: var(--font-size-xs);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-muted);
    padding: var(--space-3) var(--space-3) var(--space-1);
    position: sticky;
    top: 0;
    background: var(--bg-secondary);
    z-index: 1;
}

.conversation-time {
    font-size: var(--font-size-xs);
    color: var(--text-muted);
    margin-left: auto;
    flex-shrink: 0;
}
```
(Hide `.conversation-time` when `.conversation-actions` show on hover — add `.conversation-item:hover .conversation-time { display: none; }`.)
- [ ] **Step 5: Component tests** — extend `Sidebar.test.ts`: conversations with `updated_at` today + 10 days ago produce two `.conversation-group-label`s ("Today", "Previous 30 days"); each item contains `.conversation-time`. Run full component suite; fix fallout (factories may need `updated_at`).
- [ ] **Step 6:** E2E + visual re-baseline (sidebar snapshots). Commit `feat(sidebar): date-grouped conversations with relative timestamps`.

### Task 15: New Chat dedupe

**Files:**
- Modify: `web/src/core/conversation.ts` (new-chat handler — find with `grep -n "new-chat-btn\|createConversation\|newConversation" web/src/core/*.ts`)
- Test: `web/tests/unit/` new test or extend existing conversation test

**Interfaces:**
- Produces: `findReusableEmptyConversation(conversations: Conversation[]): Conversation | null` exported from `web/src/core/conversation.ts`.

- [ ] **Step 1: Failing unit test:**

```ts
import { describe, it, expect } from 'vitest';
import { findReusableEmptyConversation } from '@/core/conversation';
import { DEFAULT_CONVERSATION_TITLE } from '@/types/api';

const conv = (over: object) => ({
  id: 'x', title: DEFAULT_CONVERSATION_TITLE, model: 'm',
  created_at: '2026-08-18T00:00:00Z', updated_at: '2026-08-18T00:00:00Z',
  messageCount: 0, ...over,
});

describe('findReusableEmptyConversation', () => {
  it('returns an empty default-titled conversation', () => {
    expect(findReusableEmptyConversation([conv({ id: 'a' })])?.id).toBe('a');
  });
  it('skips titled, non-empty, archived and agent conversations', () => {
    expect(findReusableEmptyConversation([
      conv({ title: 'Named' }),
      conv({ messageCount: 3 }),
      conv({ archived: true }),
      conv({ is_agent: true }),
    ])).toBeNull();
  });
});
```
- [ ] **Step 2: Implement:**

```ts
export function findReusableEmptyConversation(conversations: Conversation[]): Conversation | null {
  return (
    conversations.find(
      (c) =>
        c.title === DEFAULT_CONVERSATION_TITLE &&
        (c.messageCount ?? 0) === 0 &&
        !c.archived &&
        !c.is_agent,
    ) ?? null
  );
}
```
In the New Chat click handler, before creating: `const reusable = findReusableEmptyConversation(useStore.getState().conversations); if (reusable) { <navigate to reusable.id — same code path as clicking it>; return; }`.
- [ ] **Step 3:** Run unit test (PASS), then E2E `conversation.spec.ts` + `pagination.spec.ts` (both create conversations — verify no test depends on New Chat always creating; fix seeds if one does). Commit `feat(sidebar): reuse existing empty conversation on New Chat`.

### Task 16: Programs nav as compact list

**Files:**
- Modify: `web/src/components/Sidebar.ts:66-130, 185-200` (entry builders emit icon + label rows)
- Modify: `web/src/styles/components/sidebar.css` (.sidebar-nav-row and entry styles)

- [ ] **Step 1:** Change `.sidebar-nav-row` from grid-of-boxes to a vertical list; each entry (`.planner-entry`, `.agents-entry`, `.sports-entry`, `.language-entry` — class names preserved for tests) becomes a row:

```css
.sidebar-nav-row { display: flex; flex-direction: column; gap: 2px; padding: 0 var(--space-2); }

:is(.planner-entry, .agents-entry, .sports-entry, .language-entry) {
    display: flex;
    align-items: center;
    gap: var(--space-2-5);
    padding: var(--space-2) var(--space-2-5);
    border: none;
    border-radius: var(--radius-sm);
    background: transparent;
    font-size: var(--font-size-ui);
    color: var(--text-secondary);
    cursor: pointer;
}

:is(.planner-entry, .agents-entry, .sports-entry, .language-entry):hover {
    background: var(--bg-hover);
    color: var(--text-primary);
}
```
Delete the old boxed-grid rules (grep `sidebar-nav-row` + each entry class in sidebar.css and the ` single` modifier handling).
- [ ] **Step 2:** Ensure entry markup renders icon + label side by side (adjust the builders' innerHTML if the label was below the icon). Keep unread/waiting badges right-aligned (`margin-left: auto`).
- [ ] **Step 3:** vitest + E2E (`agents.spec.ts` clicks `.agents-entry`; `sports.visual.ts` selects `.sports-entry`) + visual re-baseline. Commit `feat(sidebar): compact programs nav list`.

### Task 17: Footer consolidation (user menu popover)

**Files:**
- Modify: `web/src/components/Sidebar.ts:344-397, 623-642`, `web/src/core/init.ts` (drop `#archive-entry-container` from shell)
- Modify: `web/src/styles/components/sidebar.css` (footer styles)
- Test: `web/tests/component/Sidebar.test.ts`, `web/tests/e2e/settings.spec.ts:11`, `web/tests/e2e/location.spec.ts:16`

**Interfaces:**
- Produces: `#user-menu-btn` (the footer row, `aria-expanded`), `.user-menu` popover containing `#settings-btn`, `#memories-btn`, `.user-menu-archive` (navigates to archive route, shows `.archive-count` badge), `#logout-btn`. `#monthly-cost` becomes a plain `<span>` inside the footer row.

- [ ] **Step 1:** Rewrite `renderUserInfo()` to render:

```html
<button id="user-menu-btn" class="user-menu-btn" aria-haspopup="menu" aria-expanded="false">
  <span class="user-avatar">…existing avatar…</span>
  <span class="user-name">…</span>
  <span id="monthly-cost" class="user-cost">0.00 Kč</span>
</button>
<div class="user-menu hidden" role="menu">
  <button id="settings-btn" class="user-menu-item" role="menuitem">…icon… Settings</button>
  <button id="memories-btn" class="user-menu-item" role="menuitem">…icon… Data</button>
  <button class="user-menu-item user-menu-archive" role="menuitem" data-route="archive">…icon… Archive <span class="archive-count">…</span></button>
  <button id="logout-btn" class="user-menu-item" role="menuitem">…icon… Log out</button>
</div>
```
Click on `#user-menu-btn` toggles `.hidden` on `.user-menu` + `aria-expanded`; outside click closes. Existing `#settings-btn`/`#memories-btn`/`#logout-btn` handlers in `events.ts` keep working (ids preserved). `renderArchiveEntry()` now populates only the menu badge; remove the standalone `.archive-entry` row and the `#archive-entry-container` mount. Archive navigation reuses the existing `data-route="archive"` delegation.
- [ ] **Step 2:** CSS: `.user-menu` = anchored card above the footer (`position: absolute; bottom: 100%;` within `.sidebar-footer { position: relative; }`), `--shadow-lg`, `--radius-md`; `.user-menu-item` rows 36px, icon + label; `.user-cost` small muted, `margin-left: auto`. Delete `.btn-monthly-cost`, `.btn-icon-action`, `.archive-entry*` styles.
- [ ] **Step 3:** Preserve the monthly-cost popup: `#monthly-cost` previously opened cost history on click — move that behavior to a `.user-menu-item` ("Cost history") OR keep click-on-cost-span; check `grep -n "monthly-cost" web/src/core/events.ts web/src/components/*.ts` and keep exactly one affordance (menu item preferred, keeps `#monthly-cost` purely informational).
- [ ] **Step 4:** Update tests: `Sidebar.test.ts` (`.archive-entry` assertions -> `.user-menu-archive`; `"This month:"` text assertion -> cost value in `#monthly-cost`), `settings.spec.ts` + `location.spec.ts` — open the menu first:

```ts
await page.click('#user-menu-btn');
await page.click('#settings-btn');
```
Grep all of `web/tests` for `#settings-btn`, `#memories-btn`, `#logout-btn`, `archive-entry`, `monthly-cost` and update each call site.
- [ ] **Step 5:** Full phase-boundary `make test-all` + visual re-baseline. Commit `feat(sidebar): consolidated footer with user menu popover`.

---

## Phase 5 — Settings

### Task 18: Fix settings-opens-scrolled-to-bottom (TDD)

Root cause (verified): `SettingsPopup.ts:1457-1462` focuses `#custom-instructions` — the LAST field — after render, scrolling the body to the bottom.

**Files:**
- Modify: `web/src/components/SettingsPopup.ts:1457-1462`
- Test: `web/tests/e2e/settings.spec.ts`

- [ ] **Step 1: Failing E2E test** (add to settings.spec.ts):

```ts
test('opens scrolled to the top with Appearance visible', async ({ page }) => {
  await page.goto('/');
  await page.click('#user-menu-btn');
  await page.click('#settings-btn');
  await page.waitForSelector('#settings-popup:not(.hidden)');
  await expect(page.locator('.settings-label', { hasText: 'Appearance' })).toBeInViewport();
  const scrollTop = await page.locator('.settings-body').evaluate((el) => el.scrollTop);
  expect(scrollTop).toBe(0);
});
```
Run: `cd web && timeout 600 npx playwright test tests/e2e/settings.spec.ts` — FAIL (scrolled to bottom).
- [ ] **Step 2: Fix** — delete the `textarea.focus()` block at SettingsPopup.ts:1457-1462 (focusing the last field is wrong regardless of scroll; no replacement focus needed).
- [ ] **Step 3:** Re-run the spec — PASS. Run the whole settings suite. Commit `fix(settings): don't autofocus custom instructions (popup opened scrolled to bottom)`.

### Task 19: Settings restructure — width, grouped tabs, save-on-change

**Files:**
- Modify: `web/src/components/SettingsPopup.ts` (renderContent 600-756, saveSettings 778-826, openSettingsPopup 1328-1486)
- Modify: `web/src/styles/components/popups.css` (settings-specific styles)
- Test: `web/tests/e2e/settings.spec.ts`, `web/tests/visual/popups.visual.ts`

**Interfaces:**
- Produces: `.settings-tabs` (desktop-only) with buttons `data-settings-tab="appearance|integrations|notifications|instructions"`; sections wrapped in `.settings-section[data-settings-section="..."]`; text fields save on blur via existing `settings.update()`; `.settings-saved-indicator` transient confirmation; footer Save bar REMOVED.

- [ ] **Step 1:** Group `renderContent()` output into four wrappers:
  - `appearance`: Appearance, Primary Language
  - `integrations`: Todoist, Google Calendar, Garmin, Location
  - `notifications`: Notifications, Daily Briefing, WhatsApp
  - `instructions`: Custom Instructions
  Each: `<div class="settings-section" data-settings-section="appearance">…existing fields…</div>`.
- [ ] **Step 2:** Tabs: render `.settings-tabs` under the popup header with 4 buttons (`data-settings-tab`); clicking sets `.active` on the tab and shows only the matching section (`.settings-section { display: none; } .settings-section.active { display: block; }`). Default tab: appearance. Mobile (<=768px): tabs hidden, ALL sections shown stacked with `.settings-section-title` headers (`@media` swap).
- [ ] **Step 3:** Save-on-change: WhatsApp input and Custom Instructions textarea get `blur` handlers calling `settings.update({ whatsapp_phone })` / `settings.update({ custom_instructions })` only when the value changed vs the cached value (reuse the comparison in `saveSettings()`); on success show `<span class="settings-saved-indicator">Saved</span>` next to the field label, fading out after 1.5s (CSS transition). Delete `saveSettings()`, the footer `.settings-save-btn`, and the `.info-popup-footer settings-footer` markup.
- [ ] **Step 4:** Width: add `.settings-content { max-width: 640px; width: calc(100vw - 32px); }` on the settings popup content (scoped class on `#settings-popup .info-popup-content` — do NOT widen other info-popups).
- [ ] **Step 5:** Update `settings.spec.ts`: the label-sequence assertion (lines 30-47) now checks labels within the active tab / after switching tabs; `.settings-save-btn` assertions removed; add a save-on-change test:

```ts
test('custom instructions save on blur', async ({ page }) => {
  await page.goto('/');
  await page.click('#user-menu-btn');
  await page.click('#settings-btn');
  await page.click('[data-settings-tab="instructions"]');
  await page.fill('#custom-instructions', 'be brief');
  await page.locator('#custom-instructions').blur();
  await expect(page.locator('.settings-saved-indicator')).toBeVisible();
});
```
- [ ] **Step 6:** Update `popups.visual.ts` settings snapshots (they build settings DOM directly — align their markup with the new structure). Phase-boundary `make test-all` + visual re-baseline. Commit `feat(settings): tabbed sections, save-on-change, wider modal`.

---

## Phase 6 — Dashboards

### Task 20: Headings, button system, approvals + activity polish

**Files:**
- Modify: `web/src/styles/components/agents.css:200-205`, `sports.css:111-119`, `language.css:111-119` (heading treatment)
- Modify: `web/src/styles/components/buttons.css` (shared inline button rules)
- Modify: `web/src/components/CommandCenter.ts:166-198` (Recent Activity), approvals empty-state block (find `.command-center-empty`/approvals markup around lines 100-165)
- Test: `web/tests/e2e/agents.spec.ts`, visual suites

- [ ] **Step 1: Headings** — in all three files replace the gradient-text block (`background: linear-gradient(...); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;`) with:

```css
    font-family: var(--font-family-display);
    font-weight: 600;
    letter-spacing: -0.01em;
    color: var(--text-primary);
```
- [ ] **Step 2: Button unification** — in buttons.css add shared rules and point the legacy classes at them:

```css
/* Inline (auto-width) primary/secondary actions - dashboards */
:is(.btn-new-agent, .sports-add-btn, .language-add-btn, .sports-card-continue, .language-card-continue) {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1-5);
    background-color: var(--accent);
    color: white;
    border: none;
    border-radius: var(--radius-full);
    padding: var(--space-2) var(--space-4);
    font-size: var(--font-size-ui);
    font-weight: 500;
    cursor: pointer;
    transition: background-color var(--transition-fast);
}

:is(.btn-new-agent, .sports-add-btn, .language-add-btn, .sports-card-continue, .language-card-continue):hover {
    background-color: var(--accent-hover);
}

.btn-run-labeled {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1-5);
    background-color: var(--bg-tertiary);
    color: var(--text-primary);
    border: 1px solid var(--border);
    border-radius: var(--radius-full);
    padding: var(--space-2) var(--space-4);
    font-size: var(--font-size-ui);
    cursor: pointer;
}
```
Then DELETE the per-component duplicates of these rules in agents.css/sports.css/language.css (grep each class name; remove conflicting declarations, keep any layout-only rules).
- [ ] **Step 3: Approvals empty state** — locate the "No pending approvals" block in CommandCenter.ts + its `.command-center-*` CSS; replace the boxed slab with a single muted line: `<p class="section-empty-note">No pending approvals.</p>` and

```css
.section-empty-note { color: var(--text-muted); font-size: var(--font-size-ui); padding: var(--space-2) 0; }
```
(Keep the `.command-center-section--approvals.has-approvals` class contract used by agents.spec.ts:250.)
- [ ] **Step 4: Recent Activity** — in `renderCommandCenter` (166-198): default to expanded-but-limited. Change `data-collapsed` default to `"false"`, remove `.collapsed` from `.executions-list`, add class `executions-list--limited` plus a "Show all" button when items > 3:

```css
.executions-list--limited .execution-item:nth-child(n + 4) { display: none; }
```
`Show all` click removes `--limited` and hides itself. Replace the `▶` `.section-toggle` glyph with a chevron SVG rotated by CSS when `data-collapsed="true"` (toggle still collapses the whole list).
- [ ] **Step 5:** Run `agents.spec.ts` (Command Center h2 text unchanged), update if it asserts collapsed-by-default activity. Visual re-baseline (agents/sports/language). Commit `feat(dashboards): display-face headings, unified buttons, slim empty states, visible recent activity`.

### Task 21: Mobile dashboard title dedupe

**Files:**
- Modify: `web/src/styles/components/agents.css`, `sports.css`, `language.css`, `planner.css`

- [ ] **Step 1:** Add to each file's mobile media block (create if absent):

```css
@media (max-width: 768px) {
    .command-center-title h2 { display: none; }
}
```
(sports: `.sports-programs-title h2`; language: `.language-programs-title h2`; planner: `.dashboard-title` — verify the mobile header shows a title on these routes first via capture script; only hide where duplicated.)
- [ ] **Step 2:** Keep icons/actions rows; verify spacing collapses cleanly (no orphan gaps) on the mobile captures.
- [ ] **Step 3:** Phase-boundary `make test-all`, `mobile.visual.ts` re-baseline. Commit `fix(ui): hide duplicated dashboard titles on mobile`.

---

## Phase 7 — Motion & polish

### Task 22: Motion pass

**Files:**
- Modify: `web/src/styles/base.css` (reduced-motion guard), `messages.css`, `popups.css`, `buttons.css`
- Modify: `web/src/components/messages/render.ts` (entrance class on live appends only)

- [ ] **Step 1: Reduced-motion guard** (base.css, bottom):

```css
@media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }
}
```
(Playwright runs with `reducedMotion: 'reduce'` — snapshots stay stable.)
- [ ] **Step 2: Message entrance** — `addMessageToUI` gains an `options?: { animate?: boolean }` param; live-append call sites (streaming/send paths in `core/messaging.ts`) pass `animate: true`; history rendering (`renderMessages`) does not. When set, add class `message--entering` and remove it on `animationend`.

```css
@keyframes message-in {
    from { opacity: 0; transform: translateY(4px); }
}

.message--entering { animation: message-in var(--duration-base) var(--ease-out); }
```
- [ ] **Step 3: Modal/popover entrance** (popups.css):

```css
@keyframes popup-in {
    from { opacity: 0; transform: scale(0.98); }
}

.info-popup:not(.hidden) .info-popup-content { animation: popup-in var(--duration-fast) var(--ease-out); }
```
Apply the same animation to `.user-menu`, `.model-dropdown`, `.toolbar-toggles.open`.
- [ ] **Step 4: Press feedback** (buttons.css):

```css
:is(.btn-primary, .btn-send, .btn-stop, .welcome-prompt-chip):active { transform: scale(0.97); }
```
- [ ] **Step 5: Streaming caret** — find the streaming append point in `core/messaging.ts` (where chunks are written into the last `.message-content`); while streaming, ensure a trailing `<span class="streaming-caret"></span>` exists; remove on stream end.

```css
.streaming-caret {
    display: inline-block;
    width: 8px;
    height: 1em;
    margin-left: 2px;
    vertical-align: text-bottom;
    background: var(--accent);
    border-radius: 2px;
    animation: caret-pulse 1s ease-in-out infinite;
}

@keyframes caret-pulse { 50% { opacity: 0.25; } }
```
- [ ] **Step 6:** vitest + E2E (streaming specs in `stream-resume.spec.ts` must stay green — caret is additive; verify no test does exact innerHTML equality on streaming content; fix if so). Commit `feat(ui): motion pass — entrances, press feedback, streaming caret, reduced-motion guard`.

### Task 23: Sidebar loading skeletons

**Files:**
- Modify: `web/src/components/Sidebar.ts` (loading branch in `renderConversationsList`), `web/src/styles/components/sidebar.css`
- Test: `web/tests/component/Sidebar.test.ts`

- [ ] **Step 1:** Component test: when store has `conversations: []` and a loading flag true (find the existing flag: `grep -n "loading" web/src/state/store.ts` — reuse; if none exists for the initial list fetch, add `conversationsLoading: boolean` to the store set around the fetch in init), `renderConversationsList()` renders 3 `.conversation-skeleton` rows. Run: FAIL.
- [ ] **Step 2:** Implement branch + CSS:

```css
.conversation-skeleton {
    height: 40px;
    margin: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
    background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--bg-hover) 50%, var(--bg-tertiary) 75%);
    background-size: 200% 100%;
    animation: skeleton-shimmer 1.4s ease-in-out infinite;
}

@keyframes skeleton-shimmer { to { background-position: -200% 0; } }
```
- [ ] **Step 3:** Test PASS, suite green. Commit `feat(sidebar): loading skeletons for conversation list`.

### Task 24: Final audit, docs, cleanup

**Files:**
- Modify: `docs/` frontend pages (see step 3), `TODO.md`
- Test: everything

- [ ] **Step 1: Full matrix capture** — `node web/scripts/ui-capture.cjs` against dev with a seeded rich conversation; review all 16 shots for stragglers (spacing collisions, theme misses, contrast). Fix anything found as small follow-up edits in the relevant component CSS (each fix verified by re-capture).
- [ ] **Step 2: Full suite + final visual re-baseline:**

```bash
make lint && make test-all && make test-fe-visual-update && make test-fe-visual-browse
```
- [ ] **Step 3: Docs** — run the `docs-updater` agent (or manually): update `docs/` for the new design tokens (type scale semantics, brand palette, motion tokens), ChatHeader component, settings save-on-change behavior, and the `web/scripts/ui-capture.cjs` utility. Remove any docs references to the Save button / archive entry / cost display that changed.
- [ ] **Step 4: Commit** `docs(ui): document overhauled design system and components` and a final `chore(ui): post-overhaul polish fixes` if step 1 produced fixes.

---

## Self-review notes

- Spec coverage: Phase 1 -> Tasks 1-4; Phase 2 -> 5-9; Phase 3 -> 10-13; Phase 4 -> 14-17; Phase 5 -> 18-19; Phase 6 -> 20-21; Phase 7 -> 22-24. Spec's "preload fonts in index.html" is intentionally satisfied via Fontsource imports bundled by Vite instead (hashed asset names make manual preload brittle; `font-display: swap` covers perceived performance).
- Known type/selector contracts repeated across tasks: `#conversation-cost` (Tasks 5, 7-writer), `renderChatHeader` (Tasks 5, 6), `--font-size-ui`/`--font-size-base` (Task 4, used in later CSS), `#user-menu-btn` -> `#settings-btn` flow (Tasks 17, 18, 19).
- Every task ends with the relevant suites green and a visual re-baseline when pixels change; phase boundaries run `make test-all`.
