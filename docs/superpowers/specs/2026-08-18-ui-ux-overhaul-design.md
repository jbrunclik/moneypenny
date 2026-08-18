# UI/UX Overhaul — Design Spec

**Date:** 2026-08-18
**Status:** Approved
**Scope:** Full visual/UX refresh across all variants (light/dark x desktop/mobile). Explicitly out of scope: product naming/branding (wordmark, logo, product name stay as-is).

## Background

The UI was originally built with much older models and reads as "competent default" rather than premium: stock Tailwind palette with two competing accents, system font stack, no chat header on desktop, cryptic compose toolbar, undifferentiated sidebar list, no motion. A full review (screenshots of all 4 variants + CSS audit) identified the gaps. Decisions locked with Jiri:

- **Typography:** self-hosted UI face + display face (no external requests).
- **Chat look:** keep message bubbles for both roles; fix widths; avatars removed on mobile only.
- **Accent:** single accent family — refreshed indigo, slightly deeper/warmer than stock Tailwind; user bubble joins the brand family (blue retired).
- **Delivery:** phased commits directly to `main`; lint + full tests green before each commit.

## Phase 1 — Foundation: tokens, fonts, contrast

**Files:** `web/src/styles/variables.css`, `web/src/styles/base.css`, `web/index.html`, new `web/public/fonts/`.

### Brand palette (both themes)

New ramp replaces `--color-brand-*` (old values in parentheses):

| Token | New | Old |
|-------|-----|-----|
| `--color-brand-300` | `#A9A6F7` | (new) |
| `--color-brand-400` | `#7B78F0` | `#818cf8` |
| `--color-brand-500` | `#5753E8` | `#6366f1` |
| `--color-brand-600` | `#4A46C6` | `#4f46e5` |
| `--color-brand-700` | `#3F3BA8` | `#4338ca` |
| `--color-brand-800` | `#34318A` | `#3730a3` |
| `--color-brand-900` | `#2B2973` | `#312e81` |
| `--color-brand-950` | `#1D1B4F` | `#1e1b4b` |

- `--bg-user: var(--color-brand-600)` in **both** themes; white text (verify >= 4.5:1 — #4A46C6/white is ~7:1).
- Delete `--color-user-500` (blue) and its aliases; `--color-user-text*` and `--color-user-overlay` stay.
- `--gradient-assistant-avatar` retuned to the new hue (brand-500 -> `#7C5CE8` -> `#9B6CF2`); purple gradient tokens updated to harmonize.
- `--accent-muted` recomputed from new brand-500 (`rgba(87, 83, 232, 0.15)` dark / `0.10` light).

### Neutrals — contrast fixes

Hover and border must be visually distinct in both themes:

- **Dark:** `--color-neutral-800` (tertiary) `#242424`, `-700` (hover) `#2a2a2a`, `-600` (border) `#383838`. Backgrounds 950/900/850 unchanged.
- **Light:** secondary `#f8f9fb`, assistant `#f3f4f6` (unchanged), tertiary `#eceef1`, hover `#eef0f4`, border `#e2e5ea`.
- Light scrollbar thumb: `#d1d5db` (currently invisible `--bg-tertiary` on white).
- `--overlay-bg`: `rgba(0,0,0,0.55)` dark / `rgba(0,0,0,0.45)` light; modal/popup backdrops gain `backdrop-filter: blur(8px)`.
- `::selection` inside `.message.user .message-content`: `rgba(255,255,255,0.3)` background, inherit color.

### Fonts

- **Inter** (variable or 400/500/600/700 static, latin + latin-ext for Czech) — UI and message text. `--font-family: 'Inter', -apple-system, ...` fallback chain preserved.
- **Bricolage Grotesque** (600/700, latin-ext) — new `--font-family-display`. Used ONLY for: empty-state headline, dashboard page titles, modal titles. If it reads too quirky in situ, swap token to Space Grotesk or Sora (one-line change; both latin-ext).
- Self-hosted woff2 in `web/public/fonts/`, `@font-face` with `font-display: swap`, `<link rel="preload">` for the two primary weights in `index.html`. No external font requests (CSP-friendly).

### Type tokens

Semantic cleanup so names match reality (body = 16px = `--font-size-base`):

- New scale: `--font-size-xs: 11px`, `sm: 12px`, `ui: 14px`, `md: 15px`, `base: 16px`, `xl: 18px`, `2xl: 20px`, `3xl: 24px`, `4xl: 32px`.
- Sweep all usages; **no blanket size changes** — every component keeps its current rendered size unless a phase deliberately changes it. Message text line-height 1.6; UI chrome 1.45.

### Motion tokens (consumed in Phase 7)

`--duration-fast: 120ms`, `--duration-base: 180ms`, `--duration-slow: 240ms`, `--ease-out: cubic-bezier(0.2, 0, 0, 1)`, `--ease-in-out: cubic-bezier(0.4, 0, 0.2, 1)`.

## Phase 2 — Chat surface

**Files:** `web/src/styles/layout.css`, `web/src/styles/components/messages.css`, new `ChatHeader` component, `web/src/core/init.ts`, welcome-message rendering.

### Chat header (desktop)

New `ChatHeader` component rendered at the top of `.main` for conversation views (~52px, `border-bottom: 1px solid var(--border)`, bg-primary):

- Left: conversation title, inline-rename on click (replaces sidebar-hover-only rename as primary affordance; sidebar actions stay).
- Right: per-conversation **cost chip** (moves the floating "0.10 Kc" text here; tooltip retains detail), archive + delete icon buttons.
- The existing Sports/Language program header becomes a variant of this same component (adds back button + emoji + Reset). One component, two variants — delete the bespoke program header styles.
- Mobile (<=768px): existing `.mobile-header` continues to serve as the header (menu + title); the new ChatHeader is hidden, its actions remain reachable via sidebar. The cost chip renders compactly on the right side of `.mobile-header` so per-conversation cost stays visible on mobile (the old floating cost line is removed in Phase 3). Program variant keeps back/Reset on mobile as today.
- `.messages` gains top padding under the header; content scrolls beneath it.

### Bubbles and avatars

- User bubble: `max-width: 70%` desktop, `85%` mobile (of the message column), right-aligned, new indigo bg.
- Assistant bubble: unchanged width/card treatment (decision: keep bubbles).
- Avatars: desktop unchanged except **remove `box-shadow: var(--shadow-glow-accent)`** from the assistant avatar. Mobile: `.message-avatar { display: none }` and gutter reclaimed (`.message-content { max-width: 100% }`).

### Message actions

- Desktop: hover-reveal behavior unchanged.
- Mobile: timestamp always visible; the 5 icon buttons collapse behind a single `...` overflow button that toggles them inline (no popover library; expand/collapse in place). Touch targets >= 44px.

### Empty state

Replaces "Welcome to AI Chatbot / Start a conversation with Gemini AI":

- Display-face headline: "What can I help with?" (EN; UI language is out of scope for this overhaul).
- 3-4 static suggested-prompt chips (e.g. "Summarize a link", "Plan my week", "Practice Italian", "Check my training readiness") — clicking fills the composer and focuses it. Static list, no personalization (YAGNI).
- Vertically centered; works in both themes and on mobile.

## Phase 3 — Compose card

**Files:** `web/src/styles/components/input.css`, `web/src/components/MessageInput.ts`, model-selector component (new), `web/src/core/init.ts`.

One bordered card (`--radius-lg`, `--bg-secondary`, 1px border; focus-within: accent border) containing:

1. Textarea (top) — autogrow as today, placeholder unchanged for now.
2. Integrated toolbar (bottom row, inside the card):
   - **Left:** model menu — the existing custom dropdown (`#model-selector-btn` + `#model-dropdown`) restyled and enhanced: proper chevron icon (replacing the "▼" text glyph), option rows with name + one-line description (when available), keyboard navigation (arrows + Enter, Esc closes), `aria-expanded`/`role="listbox"`.
   - Toggle buttons (live audio, web search, sparkles/effects, incognito): each gets `aria-label`, `title` tooltip, and a clear pressed state (`aria-pressed`, accent-muted bg + accent icon).
   - **Right:** mic, attach, send.
3. **Send button states:** disabled (muted gray), ready (filled brand-500), streaming (stop square). Upload progress ring on the send button is preserved exactly (see docs/features upload notes).
4. **Mobile (<=768px):** the four toggles collapse into one "options" (sliders icon) button opening an inline popover; model button, mic, attach, send stay visible. One toolbar row total.
5. Cost line under input is removed (moved to ChatHeader in Phase 2); monthly total stays in the sidebar footer.

Enter-to-send desktop-only behavior, draft persistence, and voice input are preserved.

## Phase 4 — Sidebar

**Files:** `web/src/styles/components/sidebar.css`, `web/src/components/Sidebar.ts`, `web/src/core/conversation.ts`.

- **Date grouping:** Today / Yesterday / Previous 7 days / Previous 30 days / Older — small sticky group labels; rows get right-aligned muted relative time ("2d", "3w"). Uses existing `updated_at`.
- **New Chat dedupe:** clicking New Chat navigates to an existing empty "New Conversation" (0 messages) if one exists instead of creating another. No backend change; client checks the loaded conversation list (title == default AND message_count == 0 where available, else tracked client-side).
- **Programs nav:** replace the 3-box grid with a compact nav list (icon + label rows: Agents, Sports, Language), same navigation targets.
- **Footer consolidation:** single row — avatar + name + this-month cost right-aligned. Click opens a popover menu: Settings, Data, Archive (with count badge), Log out. The separate Archive row and 3-icon cluster are removed.
- Tighten header stack spacing (title / New Chat / search / nav / list).

## Phase 5 — Settings

**Files:** `web/src/styles/components/popups.css`, `web/src/components/SettingsPopup.ts`.

- **Bug fix first (TDD):** modal opens scrolled to the bottom — root-cause (likely autofocus on a lower field or scroll anchoring) and add a regression test.
- Modal widens to ~640px; content grouped into sections with desktop tab nav: *Appearance & Language / Integrations / Notifications / AI Instructions*. Mobile: stacked sections, no tabs.
- **Save-on-change:** selects/toggles/theme apply instantly (theme already does); text inputs (WhatsApp number, custom instructions) save on blur with inline "Saved" indicator and validation errors inline. Global Save bar removed.
- Backdrop uses new overlay tokens + blur.

## Phase 6 — Dashboards (Command Center / Sports / Language)

**Files:** `web/src/styles/components/agents.css`, `sports.css`, `language.css`, corresponding TS components.

- Two-tone headings (a `linear-gradient(--text-primary, --accent)` + `background-clip: text` treatment on the dashboard `<h2>`s) become single-color display-face titles.
- **Button system** (defined in `buttons.css`, applied everywhere): `btn-primary` (filled brand), `btn-secondary` (subtle bg + border), `btn-ghost` (icon-only). Continue/Run/New Agent/New Program all map onto it with consistent sizing; no more gray-outline-vs-filled-pill mismatch.
- Recent Activity: chevron disclosure (not play triangle); first 3 items visible by default with "Show all".
- Approvals empty state: slim inline note replaces the large gray slab.
- **Mobile title dedupe:** in-page page titles hidden <=768px (the mobile header already shows the title); page-level actions remain visible.

## Phase 7 — Motion & final polish

**Files:** component CSS, small TS hooks where classes are applied.

- Message entrance: 150ms fade + 4px rise — only for newly appended messages (streamed or sent), never on history load.
- Modal/popover: scale 0.98 -> 1 + fade, 160ms; overlay fade.
- Primary buttons: `:active` scale(0.97).
- Streaming indicator: pulsing caret dot while tokens arrive.
- Conversation-list skeleton rows while the list loads.
- All motion wrapped in `@media (prefers-reduced-motion: reduce)` disable.
- **Final audit:** full screenshot pass (light/dark x desktop/mobile x chat/home/dashboards/settings) using the Playwright capture script; fix stragglers; re-baseline visual tests.

## Testing & delivery

- One commit per phase to `main`; `make lint` + `make test-all` green before each commit (per-phase E2E run: `cd web && timeout 600 npx playwright test`).
- Known test impact (in scope per phase, not afterthought):
  - Phase 3 replaces the native model `<select>` — E2E and unit tests targeting it must be updated.
  - Phase 4 sidebar restructure changes DOM that tests/mocks may reference.
  - Phase 2/6 header and title changes affect E2E title assertions.
  - Visual regression tests re-baselined in Phase 7 (and per phase if they gate CI).
- Every UI phase verified on desktop + mobile viewports, both themes (project rule), via the capture script at `scratchpad/capture.js` (to be checked into `web/tests/` as a dev utility if useful).
- Settings scroll bug (Phase 5) follows TDD: failing test first.

## Out of scope

- Product naming, wordmark, logo, favicon.
- UI copy localization (Czech UI).
- Backend/API changes (everything above is frontend-only; New Chat dedupe is client-side).
- PWA/native niceties.
