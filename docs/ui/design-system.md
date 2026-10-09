# Design System and CSS Architecture

The frontend uses plain CSS modules and design tokens (CSS custom properties) - no CSS
Modules or CSS-in-JS. Component patterns live in [components.md](components.md);
reusable interaction patterns in [patterns.md](patterns.md).

## File Structure

```
web/src/styles/
├── main.css           # Entry point (imports all modules, in cascade order)
├── variables.css      # Design tokens + light-theme overrides
├── base.css           # Reset, typography, utilities
├── layout.css         # App shell structure, responsive breakpoints
└── components/        # One file per major component or feature area
    ├── chat-header.css    buttons.css    messages.css   sidebar.css
    ├── input.css          popups.css     thinking.css   planner.css
    ├── agents.css         kv-store.css   sports.css     language.css
    ├── quick-actions.css  quiz.css       pdf-viewer.css
    └── glass.css          # Liquid-glass materials - imported LAST
```

`main.css` imports `variables.css`, `base.css`, `layout.css`, then the component files.
`glass.css` comes last on purpose: it upgrades chrome surfaces (header, sidebar,
popovers, modals) with translucent materials and must win the cascade.

## Style Encapsulation

- Component-specific styles use prefixed class names (`.message-*`, `.sidebar-*`,
  `.planner-*`). Generic names collide across files: `popups.css` and `kv-store.css`
  once both styled `.memory-*`, so one page silently restyled the other.
- Shared utilities use unprefixed names (`.hidden`, `.error`).
- Every file reads the same tokens from `variables.css`; never hard-code a color that
  has a token.
- Only read tokens that exist. An undefined `var(--x)` silently falls back to the
  property's initial value (Oct 2026: `--radius-xl` squared the agent editor, `--font-mono`
  lost the monospace face). `tests/unit/css-undefined-vars.test.ts` fails on any
  fallback-less `var()` that no stylesheet or `style.setProperty` defines.

## Tokens

All tokens are defined in [variables.css](../../web/src/styles/variables.css). The
lists below are the families and the values you reach for most; read the file for the
full set.

### Color

**Neutral scale** (dark theme values; the light theme redefines the same names):

```css
--color-neutral-950: #0f0f0f;   /* primary bg */
--color-neutral-900: #1a1a1a;   /* secondary bg */
--color-neutral-850: #1f1f1f;   /* assistant message bg */
--color-neutral-800: #242424;   /* tertiary bg */
--color-neutral-700: #2a2a2a;   /* hover bg */
--color-neutral-600: #383838;   /* borders */
--color-neutral-400: #8a8a8a;   /* muted text (AA on bg-primary) */
--color-neutral-300: #a0a0a0;   /* secondary text */
--color-neutral-100: #e5e5e5;   /* primary text */
```

**Brand** (indigo, refreshed Aug 2026 - deeper/warmer than stock Tailwind):
`--color-brand-300` `#a9a6f7` ... `--color-brand-500` `#5753e8` (primary accent),
`--color-brand-600` `#4a46c6` (pressed state / user bubble) ... `--color-brand-950`
`#1d1b4f`. There is deliberately a single accent family: the user bubble uses
`--bg-user: var(--color-brand-600)` in both themes (the old blue `--color-user-500` was
removed). `--color-purple-400/500` exist only for gradients.

**Status**: `--color-success-*`, `--color-error-*`, `--color-warning-*` (400/500/600,
plus a translucent `-900` badge background), `--color-info-500`, and the theme-aware
`--warning-text`.

**Semantic aliases** - use these in component CSS:

```css
--bg-primary / --bg-secondary / --bg-tertiary / --bg-hover / --bg-assistant / --bg-user
--text-primary / --text-secondary / --text-muted
--accent: var(--color-brand-500);  --accent-hover;  --accent-muted
--border: var(--color-neutral-600);  --border-light
--success / --error / --error-hover / --warning
--overlay-bg / --lightbox-bg / --code-bg / --code-inline-bg / --scrollbar-thumb
```

**Glass materials** (`--glass-bg`, `--glass-bg-strong` for toasts and floating buttons,
`--glass-bg-dialog` + `--glass-blur-dialog` for dialogs and sheets, `--glass-bg-menu`,
`--glass-bg-header`, `--glass-bg-sidebar`, `--glass-blur*`, `--glass-border`,
`--glass-highlight`, `--glass-shadow`) are consumed by `glass.css`.

**Dialogs and sheets share one material** (Oct 2026): `.modal`, `.info-popup-content`,
`.action-sheet`, `.agent-editor`, `.qa-editor`, `.sports-modal` and `.language-modal` all
get `--glass-bg-dialog` in `glass.css`, and every scrim is `--overlay-bg` with **no
backdrop blur** - iOS alerts dim, the dialog is the glass. A blurred scrim becomes the
dialog's backdrop root (Filter Effects), so the dialog's own glass sees only the scrim
colour and turns into flat grey. A new overlay joins those selector lists instead of
setting its own `rgba(0,0,0,...)` scrim or solid surface.

**On mobile every overlay is one bottom sheet** ("Mobile sheets (shared)" at the end of
`popups.css`; the claims list matches it in `grounding.css`): a floating card inset
`--space-2` from the edges and the home indicator, all corners `--radius-lg`, capped at
85vh, with a grab handle. Confirms and prompts become sheets too, with full-width stacked
buttons (primary on top). The handle is real: `attachSheetDismiss()` in
`web/src/utils/sheet-gesture.ts` drags the sheet down to dismiss it, starting only in the
top `SHEET_GRAB_ZONE_PX` so the body keeps scrolling. A sheet with an input needs a
`:root.kb-open` lift by `--keyboard-inset` (fixed overlays span the layout viewport, which
the iOS keyboard covers). Tests: `web/tests/e2e/mobile-sheets.spec.ts`.

### Spacing

`--space-0-5` 2px, `--space-1` 4px, `--space-1-5` 6px, `--space-2` 8px, `--space-2-5` 10px, `--space-3`
12px, `--space-4` 16px, `--space-5` 20px, `--space-6` 24px, `--space-8` 32px,
`--space-10` 40px, `--space-12` 48px.

### Typography

**Sizes** (semantic: `base` = 16px body/message text, `ui` = 14px chrome default):

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
```

There is no `--font-size-lg`. Line heights: `--line-height` 1.45,
`--line-height-relaxed` 1.6.

**Families** (self-hosted via Fontsource, latin + latin-ext for Czech; no external font
requests):

```css
--font-family: 'Inter Variable', -apple-system, BlinkMacSystemFont, ...;  /* UI + message text */
--font-family-display: 'Bricolage Grotesque Variable', var(--font-family); /* page titles, empty states */
--font-family-mono: 'SF Mono', 'Consolas', 'Monaco', monospace;
```

The display face is used sparingly: the welcome headline, dashboard page titles, and
nothing else. Fonts are imported at the top of `main.ts`
(`@fontsource-variable/inter`, `@fontsource-variable/bricolage-grotesque`). Both ship as
`unicode-range` subsets with `font-display: swap`, which matters for visual tests (see
[E2E Reliability](../testing/e2e-reliability.md)).

### Motion

```css
--duration-fast: 120ms;   /* popover/modal entrances */
--duration-base: 180ms;   /* message entrance */
--duration-slow: 240ms;
--ease-out: cubic-bezier(0.2, 0, 0, 1);
--ease-in-out: cubic-bezier(0.4, 0, 0.2, 1);
--transition-fast: 0.15s ease;  --transition-normal: 0.2s ease;  --transition-slow: 0.3s ease;
```

All animation is disabled under `prefers-reduced-motion`.

### Radius, Shadows, Layout, Z-index

- **Radius**: `--radius-xs` 4px, `--radius-sm` 8px, `--radius-md` 12px, `--radius-lg`
  16px, `--radius-pill` 10px (badges/counts), `--radius-full`; legacy alias `--radius`
  = `--radius-md`.
- **Shadows**: `--shadow-sm`, `--shadow-md`, `--shadow-lg`, `--shadow-glow-accent`,
  `--shadow-scroll-btn` (lighter values in the light theme).
- **Layout**: `--sidebar-width` 280px, `--header-height` 56px, `--input-height` 60px,
  `--message-max-width` 800px, `--message-gutter` 52px (desktop avatar gutter),
  `--dialog-width-sm` 440px (confirms, small dialogs) / `--dialog-width-md` 560px (forms,
  editors). Dialog surfaces use `--radius-lg`.
- **Z-index**: `--z-overlay` 40, `--z-dropdown` / `--z-sidebar` 50, `--z-banner` 150,
  `--z-modal-backdrop` 200, `--z-popup` / `--z-lightbox` 300, `--z-toast` 10000,
  `--z-modal` 10001.

## Theme Support

Dark is the default (`:root`). The light theme is a `[data-theme="light"]` block that
**redefines the neutral palette** (and a few accent, badge, glass, code and shadow
tokens); the semantic aliases (`--bg-primary`, `--text-primary`, ...) are not
redefined - they follow the neutrals automatically:

```css
:root               { --color-neutral-950: #0f0f0f; --color-neutral-100: #e5e5e5; }
[data-theme="light"] { --color-neutral-950: #ffffff; --color-neutral-100: #111827; }
/* both themes: --bg-primary: var(--color-neutral-950); */
```

The theme is applied by setting `data-theme` on `<html>`:

```typescript
document.documentElement.setAttribute('data-theme', 'light');
```

How the user's choice (system / light / dark) is stored and applied is covered under
Color Scheme in [UI Features](../features/ui-features.md#color-scheme).

## Key Files

- [web/src/styles/main.css](../../web/src/styles/main.css) - entry point and cascade order
- [web/src/styles/variables.css](../../web/src/styles/variables.css) - tokens and light theme
- [web/src/styles/layout.css](../../web/src/styles/layout.css) - app shell, breakpoints
- [web/src/styles/components/glass.css](../../web/src/styles/components/glass.css) - glass materials
- [web/src/main.ts](../../web/src/main.ts) - font imports

## See Also

- [UI Components](components.md) - component structure, DOM helpers, popups
- [UI Patterns](patterns.md) - reusable interaction and visual patterns
- [Mobile and PWA](mobile-and-pwa.md) - mobile-specific layout
