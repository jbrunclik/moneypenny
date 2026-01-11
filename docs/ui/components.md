# UI Components and Architecture

This document covers the UI component architecture, CSS design system, and component patterns used throughout the application.

## Table of Contents

- [CSS Architecture](#css-architecture)
- [Design System Variables](#design-system-variables)
- [Component Patterns](#component-patterns)
- [Popup Escape Key Handler](#popup-escape-key-handler)
- [Adding New Components](#adding-new-components)
- [Key Files](#key-files)

## CSS Architecture

The frontend uses a modular CSS architecture with design tokens for consistency and maintainability.

### File Structure

```
web/src/styles/
├── main.css           # Entry point (imports all modules)
├── variables.css      # Design system tokens
├── base.css           # Reset, typography, utilities
├── layout.css         # App shell structure
└── components/
    ├── buttons.css    # All button variants
    ├── messages.css   # Message display, avatars, content
    ├── sidebar.css    # Conversation list, swipe actions
    ├── input.css      # Input toolbar, model selector, file preview
    └── popups.css     # Modals, toasts, lightbox, info popups
```

### Module Organization

**main.css** - Single entry point that imports all modules:
```css
@import './variables.css';
@import './base.css';
@import './layout.css';
@import './components/buttons.css';
@import './components/messages.css';
/* ... */
```

**variables.css** - All design tokens and CSS custom properties

**base.css** - CSS reset, typography, global utilities

**layout.css** - App shell structure, responsive breakpoints

**components/** - Component-specific styles, one file per major component

### Style Encapsulation

While the app doesn't use CSS Modules or Styled Components, it follows conventions for organization:

- Component-specific styles use prefixed class names (e.g., `.message-*`, `.sidebar-*`)
- Shared utilities use unprefixed names (e.g., `.hidden`, `.error`)
- All components import from the same variables.css for consistency

## Design System Variables

All design tokens are defined in [../../web/src/styles/variables.css](../../web/src/styles/variables.css).

### Color System

**Neutral scale** (dark theme base):
```css
--color-neutral-950: #0a0a0b;  /* Darkest - backgrounds */
--color-neutral-900: #18181b;
--color-neutral-800: #27272a;
--color-neutral-700: #3f3f46;
--color-neutral-600: #52525b;
--color-neutral-500: #71717a;
--color-neutral-400: #a1a1aa;
--color-neutral-300: #d4d4d8;
--color-neutral-200: #e4e4e7;
--color-neutral-100: #f4f4f5;  /* Lightest - text on dark */
```

**Brand colors** (indigo/purple):
```css
--color-brand-950: #1e1b4b;
--color-brand-900: #312e81;
--color-brand-800: #3730a3;
--color-brand-700: #4338ca;
--color-brand-600: #4f46e5;
--color-brand-500: #6366f1;
--color-brand-400: #818cf8;
```

**Semantic colors**:
```css
--color-success-500: #22c55e;
--color-error-500: #ef4444;
--color-warning-500: #f59e0b;
```

**Semantic aliases** (for easier use):
```css
--bg-primary: var(--color-neutral-950);
--bg-secondary: var(--color-neutral-900);
--bg-tertiary: var(--color-neutral-800);
--text-primary: var(--color-neutral-100);
--text-secondary: var(--color-neutral-300);
--text-muted: var(--color-neutral-400);
--border: var(--color-neutral-700);
--accent: var(--color-brand-600);
```

### Spacing Scale

```css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 20px;
--space-6: 24px;
--space-8: 32px;
--space-10: 40px;
--space-12: 48px;
```

### Typography

**Sizes**:
```css
--font-size-xs: 0.75rem;    /* 12px */
--font-size-sm: 0.875rem;   /* 14px */
--font-size-base: 1rem;     /* 16px */
--font-size-lg: 1.125rem;   /* 18px */
--font-size-xl: 1.25rem;    /* 20px */
--font-size-2xl: 1.5rem;    /* 24px */
--font-size-3xl: 1.875rem;  /* 30px */
--font-size-4xl: 2.25rem;   /* 36px */
```

**Families**:
```css
--font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", ...;
--font-family-mono: "SF Mono", Monaco, "Cascadia Code", ...;
```

### Other Design Tokens

**Border radius**:
```css
--radius-xs: 2px;
--radius-sm: 4px;
--radius-md: 6px;
--radius-lg: 8px;
--radius-xl: 12px;
--radius-full: 9999px;
```

**Shadows**:
```css
--shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
--shadow-md: 0 4px 6px rgba(0, 0, 0, 0.1);
--shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.1);
```

**Transitions**:
```css
--transition-fast: 150ms ease;
--transition-normal: 300ms ease;
--transition-slow: 500ms ease;
```

**Z-index layers**:
```css
--z-dropdown: 1000;
--z-sticky: 1100;
--z-modal: 1200;
--z-toast: 1300;
--z-tooltip: 1400;
```

### Theme Support

The app supports light and dark themes via `[data-theme="light"]` selector:

```css
:root {
  /* Dark theme (default) */
  --bg-primary: var(--color-neutral-950);
  --text-primary: var(--color-neutral-100);
}

[data-theme="light"] {
  /* Light theme overrides */
  --bg-primary: #ffffff;
  --text-primary: var(--color-neutral-950);
}
```

Theme is applied by setting `data-theme` attribute on `<html>`:

```typescript
document.documentElement.setAttribute('data-theme', 'light');
```

## Component Patterns

### Component Structure

Components are implemented as TypeScript modules with initialization functions:

```typescript
// MessageInput.ts
export function initMessageInput() {
  const textarea = document.getElementById('message-input');
  // Initialize component
  return {
    focus: () => textarea?.focus(),
    clear: () => { if (textarea) textarea.value = ''; },
  };
}
```

### Event Delegation

Use event delegation for dynamic content instead of inline handlers:

```typescript
// Bad - inline handler
element.innerHTML = `<button onclick="handleClick()">Click</button>`;

// Good - event delegation
element.innerHTML = `<button data-action="click">Click</button>`;
element.addEventListener('click', (e) => {
  const target = e.target as HTMLElement;
  if (target.dataset.action === 'click') {
    handleClick();
  }
});
```

### DOM Helpers

Use helpers from [../../web/src/utils/dom.ts](../../web/src/utils/dom.ts):

```typescript
import { createElement, clearElement, escapeHtml } from './utils/dom';

// Create elements programmatically
const button = createElement('button', {
  class: 'btn-primary',
  'data-id': '123',
}, ['Click me']);

// Clear element content
clearElement(container);

// Escape user content
element.textContent = escapeHtml(userInput);
```

### innerHTML Usage Guidelines

**When innerHTML is ACCEPTABLE**:
- Setting SVG icons from [../../web/src/utils/icons.ts](../../web/src/utils/icons.ts) (SVG markup must be rendered as HTML)
- Rendering markdown content from `renderMarkdown()` (returns sanitized HTML)
- Complex HTML structures that would be cumbersome to build with createElement
- Any content that legitimately needs HTML markup (line breaks as `<br>`, styled elements)

**When to AVOID innerHTML**:
- Clearing element content → Use `clearElement(element)` from dom.ts
- Setting plain text → Use `element.textContent = text`
- Building simple lists → Consider `createElement` with loops

**Security requirements**:
- ALWAYS use `escapeHtml()` for any user-controlled content before interpolating into innerHTML
- SVG icons from icons.ts are safe (static constants, not user input)
- Markdown is rendered through marked.js which handles sanitization

### Icon Management

Centralize SVG icons in [../../web/src/utils/icons.ts](../../web/src/utils/icons.ts):

```typescript
// icons.ts
export const SEND_ICON = `
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
  <path d="M22 2L11 13" />
  <path d="M22 2L15 22L11 13L2 9L22 2Z" />
</svg>
`;

// Usage in component
import { SEND_ICON } from './utils/icons';

button.innerHTML = SEND_ICON;
```

Benefits:
- Prevents duplication across components
- Makes icons easy to find and update
- Single source of truth

### State Management

Use Zustand store in [../../web/src/state/store.ts](../../web/src/state/store.ts):

```typescript
import { useStore } from './state/store';

// Subscribe to state changes
const unsubscribe = useStore.subscribe(
  (state) => state.currentConversation,
  (conversation) => {
    // Handle conversation change
  },
);

// Update state
useStore.getState().setCurrentConversation(conv);

// Cleanup
unsubscribe();
```

## Popup Escape Key Handler

All popups use a centralized Escape key handler instead of individual document-level listeners. This consolidates 5+ listeners into a single one.

### How It Works

1. `initPopupEscapeListener()` is called once in main.ts during app initialization
2. Each popup registers via `registerPopupEscapeHandler(popupId, closeCallback)`
3. On Escape key, the handler finds the topmost visible popup and closes it
4. Handlers are called in reverse registration order (most recent first)

### Usage

```typescript
import { registerPopupEscapeHandler } from '../utils/popupEscapeHandler';

// In popup init function
export function initMyPopup() {
  const popup = document.getElementById('my-popup');

  function close() {
    popup?.classList.add('hidden');
  }

  // Register escape handler
  registerPopupEscapeHandler('my-popup', close);

  return { close };
}
```

### Why Centralized

**Before** (multiple listeners):
```typescript
// Each popup had its own listener
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeSourcesPopup();
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeCostPopup();
});
// ... 5+ more listeners
```

**After** (single listener):
```typescript
// One listener for all popups
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    // Find topmost visible popup and close it
  }
});
```

Benefits:
- Reduces memory usage
- Prevents event listener leaks
- Easier to debug
- Centralized logic for popup priority

### Modal Exception

[../../web/src/components/Modal.ts](../../web/src/components/Modal.ts) retains its own keydown handler because it also needs Enter (confirm) and Tab (focus trapping) handling, not just Escape.

## Adding New Components

### Step 1: Create Component File

Create a TypeScript file in `web/src/components/`:

```typescript
// web/src/components/MyComponent.ts
import { createElement } from '../utils/dom';
import { MY_ICON } from '../utils/icons';

export function initMyComponent() {
  const container = document.getElementById('my-component');
  if (!container) return;

  function render() {
    container.innerHTML = `
      <div class="my-component">
        <h2>Title</h2>
      </div>
    `;
  }

  render();

  return {
    update: (data: any) => {
      // Update component
      render();
    },
  };
}
```

### Step 2: Create Component Styles

Create a CSS file in `web/src/styles/components/`:

```css
/* web/src/styles/components/my-component.css */
.my-component {
  padding: var(--space-4);
  background: var(--bg-secondary);
  border-radius: var(--radius-md);
}

.my-component h2 {
  font-size: var(--font-size-lg);
  color: var(--text-primary);
  margin-bottom: var(--space-2);
}
```

### Step 3: Import in main.css

Add import to [../../web/src/styles/main.css](../../web/src/styles/main.css):

```css
@import './components/my-component.css';
```

### Step 4: Wire in main.ts

Initialize component in [../../web/src/main.ts](../../web/src/main.ts):

```typescript
import { initMyComponent } from './components/MyComponent';

// In init function
const myComponent = initMyComponent();
```

### Step 5: Add to HTML

Add container to [../../src/templates/index.html](../../src/templates/index.html):

```html
<div id="my-component"></div>
```

## Key Files

**Styles:**
- [../../web/src/styles/main.css](../../web/src/styles/main.css) - Entry point
- [../../web/src/styles/variables.css](../../web/src/styles/variables.css) - Design tokens
- [../../web/src/styles/layout.css](../../web/src/styles/layout.css) - App shell, responsive breakpoints
- [../../web/src/styles/components/buttons.css](../../web/src/styles/components/buttons.css) - Button variants
- [../../web/src/styles/components/popups.css](../../web/src/styles/components/popups.css) - Modals, toasts, overlays

**Components:**
- [../../web/src/components/Messages.ts](../../web/src/components/Messages.ts) - Message display
- [../../web/src/components/Sidebar.ts](../../web/src/components/Sidebar.ts) - Conversation list
- [../../web/src/components/MessageInput.ts](../../web/src/components/MessageInput.ts) - Input area
- [../../web/src/components/Modal.ts](../../web/src/components/Modal.ts) - Modal dialogs
- [../../web/src/components/Toast.ts](../../web/src/components/Toast.ts) - Toast notifications

**Utilities:**
- [../../web/src/utils/dom.ts](../../web/src/utils/dom.ts) - DOM helpers
- [../../web/src/utils/icons.ts](../../web/src/utils/icons.ts) - SVG icon constants
- [../../web/src/utils/popupEscapeHandler.ts](../../web/src/utils/popupEscapeHandler.ts) - Centralized Escape handler

**State:**
- [../../web/src/state/store.ts](../../web/src/state/store.ts) - Zustand store

**Main:**
- [../../web/src/main.ts](../../web/src/main.ts) - App initialization

**Template:**
- [../../src/templates/index.html](../../src/templates/index.html) - HTML shell

## See Also

- [Mobile and PWA](mobile-and-pwa.md) - Mobile-specific UI patterns
- [Scroll Behavior](scroll-behavior.md) - Scroll handling and pagination
- [Testing](../testing.md) - Component testing strategies
