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
    ├── popups.css     # Modals, toasts, lightbox, info popups
    └── planner.css    # Planner dashboard, events, tasks
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

1. `initPopupEscapeListener()` is called once in init.ts during app initialization
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

### Step 4: Wire in init.ts

Initialize component in [../../web/src/core/init.ts](../../web/src/core/init.ts):

```typescript
import { initMyComponent } from '../components/MyComponent';

// In init function
const myComponent = initMyComponent();
```

### Step 5: Add to HTML

Add container to [../../src/templates/index.html](../../src/templates/index.html):

```html
<div id="my-component"></div>
```

## Planner Components

The Planner feature uses a specialized dashboard component with unique visual design patterns optimized for displaying calendar events and tasks.

### Dashboard Container

The planner dashboard renders as a special message element (`.planner-dashboard-message`) at the top of the messages container, but is NOT a `.message` class to avoid interference with message pagination logic.

**Key Design Principles:**
- **Professional and polished** - Premium visual quality worthy of showcase
- **Clear visual hierarchy** - Priority and importance are immediately obvious
- **Interactive and delightful** - Smooth hover states, animations, micro-interactions
- **Responsive** - Adapts gracefully from desktop to mobile

### CSS Classes

#### Container
- `.planner-dashboard-message` - Main dashboard container (not `.message`)
- `#planner-dashboard` - Dashboard ID for easy targeting

#### Header
- `.dashboard-header` - Title and action buttons
- `.dashboard-title` - Gradient title text
- `.dashboard-actions` - Button group (refresh, reset)
- `.planner-refresh-btn` - Refresh schedule button
- `.planner-reset-btn` - Clear and restart button

#### Sections
- `.dashboard-section` - Section containers (today, tomorrow, week)
- `.dashboard-section.overdue` - Overdue tasks section (alert styling)
- `.dashboard-day` - Individual day container
- `.dashboard-day-header` - Day name and date
- `.dashboard-day-empty` - Empty state for days with no items

#### Items (Events & Tasks)
- `.planner-item` - Base class for all items
- `.planner-item-event` - Event item
- `.planner-item-task` - Task item
- `.planner-item-time` - Time badge (events only)
- `.planner-item-content` - Content area (tasks only)
- `.planner-item-text` - Main text content
- `.planner-item-location` - Location link (events only)
- `.planner-item-project` - Project label (tasks only)
- `.planner-item-copy` - Copy to clipboard button

### Visual Design Patterns

#### Priority Indicators (Tasks)

Priority is indicated by colored left border thickness:

```css
/* P1 (Low Priority) - 2px blue border */
.planner-item[data-priority="1"] {
    border-left: 2px solid #3B82F6; /* Blue-500 */
}

/* P2 (Medium Priority) - 3px blue border */
.planner-item[data-priority="2"] {
    border-left: 3px solid #3B82F6;
}

/* P3 (High Priority) - 4px orange border + shadow */
.planner-item[data-priority="3"] {
    border-left: 4px solid #F97316; /* Orange-500 */
    box-shadow: 0 2px 8px rgba(249, 115, 22, 0.12);
}

/* P4 (Urgent) - 5px red border + glow + pulse animation */
.planner-item[data-priority="4"] {
    border-left: 5px solid #EF4444; /* Red-500 */
    box-shadow: 0 2px 12px rgba(239, 68, 68, 0.2), -2px 0 8px rgba(239, 68, 68, 0.15);
    animation: priority-glow 3s ease-in-out infinite;
}
```

**Why this works:**
- Intuitive visual progression (thicker = more urgent)
- Unobtrusive for low/medium priorities
- Impossible to miss P4 tasks (red + glow + animation)
- Color-blind friendly (thickness is primary indicator)

#### Copy Button Positioning

Copy buttons are positioned contextually based on item type:

**Events:** Integrated into time pill
```html
<div class="planner-item-time">
  <span>10:00 AM-11:00 AM</span>
  <button class="planner-item-copy">...</button>
</div>
```

**Tasks:** Right-aligned in content area
```html
<div class="planner-item-content">
  <div class="planner-item-text">Task content...</div>
  <button class="planner-item-copy">...</button>
</div>
```

**Interaction:**
- Hidden by default (`opacity: 0`)
- Revealed on hover
- Smooth opacity + transform transitions
- Copied state shows checkmark with `.copied` class

#### Location Links

Location links use subtle indigo tinting instead of bold gradients:

```css
.planner-item-location {
    color: #6366F1; /* Indigo-500 */
    background: rgba(99, 102, 241, 0.08); /* Subtle tint */
    border: 1px solid rgba(99, 102, 241, 0.2);
    border-radius: var(--radius-md);
    padding: var(--space-1) var(--space-2);
}
```

**Why:**
- Not visually overwhelming
- Still clearly actionable
- Consistent with design system

#### Project Labels

Project labels are inline with task content, not separate lines:

```html
<div class="planner-item-text">
  Task content here
  <span class="planner-item-project">Project Name</span>
</div>
```

```css
.planner-item-project {
    font-size: var(--font-size-xs);
    font-weight: 600;
    color: #6B7280; /* Gray-500 */
    padding: var(--space-1) var(--space-2);
    background: rgba(156, 163, 175, 0.15);
    border: 1px solid rgba(156, 163, 175, 0.3);
    border-radius: var(--radius-sm);
}
```

**Layout:** `display: block; line-height: 1.6` on `.planner-item-text` keeps everything in flow

#### Empty States

Empty day sections are centered with dashed borders:

```css
.dashboard-day-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--space-4) var(--space-2);
    background: rgba(209, 250, 229, 0.2); /* Light green tint */
    border: 2px dashed rgba(52, 211, 153, 0.3);
    border-radius: var(--radius-md);
}
```

### Loading State

Loading uses modern bouncing dots animation matching the app's design:

```css
.dashboard-loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-4);
}

.dashboard-loading-icon {
    font-size: 48px;
    animation: float 2s ease-in-out infinite;
}

.dashboard-loading-dots span {
    width: 8px;
    height: 8px;
    background: var(--accent);
    border-radius: 50%;
    animation: bounce-loading 1.4s ease-in-out infinite;
}
```

### Mobile Responsive

The dashboard adapts for mobile viewports (< 768px):

- Vertical item layout (no flexbox row)
- Time badges at top of events
- Copy buttons always visible (`opacity: 0.6`)
- Smaller action buttons (32px instead of 36px)
- Reduced padding and spacing

### Scroll Behavior

**Important:** Planner uses DIFFERENT scroll behavior from normal chats:

- Normal chats: Scroll to bottom to show latest message
- Planner: Scroll to top to show dashboard

```typescript
// In planner.ts navigateToPlanner()
messagesContainer.scrollTop = 0; // NOT scrollToBottom()
```

### Accessibility

The dashboard includes comprehensive accessibility features:

- Focus states for all interactive elements
- High contrast mode support (`@media (prefers-contrast: high)`)
- Reduced motion support (`@media (prefers-reduced-motion: reduce)`)
- Keyboard navigation for all actions
- ARIA labels on icon buttons
- Semantic HTML structure

### Files

**Styles:**
- [../../web/src/styles/components/planner.css](../../web/src/styles/components/planner.css) - Complete dashboard styles

**Components:**
- [../../web/src/components/PlannerDashboard.ts](../../web/src/components/PlannerDashboard.ts) - Dashboard rendering
- [../../web/src/components/PlannerView.ts](../../web/src/components/PlannerView.ts) - Planner view container

**Main Integration:**
- [../../web/src/core/planner.ts](../../web/src/core/planner.ts) - `navigateToPlanner()` function

**Backend:**
- [../../src/api/routes/planner.py](../../src/api/routes/planner.py) - `/api/planner` endpoint

### Testing

Comprehensive E2E and visual tests ensure dashboard quality:

- **E2E tests:** 32 tests in `web/tests/e2e/planner.spec.ts`
- **Visual tests:** ~30 snapshots in `web/tests/visual/planner.visual.ts`
- **Coverage:** All sections, states, interactions, responsive layouts

See [Testing](../testing.md#planner-tests) for details.

## Key Files

**Styles:**
- [../../web/src/styles/main.css](../../web/src/styles/main.css) - Entry point
- [../../web/src/styles/variables.css](../../web/src/styles/variables.css) - Design tokens
- [../../web/src/styles/layout.css](../../web/src/styles/layout.css) - App shell, responsive breakpoints
- [../../web/src/styles/components/buttons.css](../../web/src/styles/components/buttons.css) - Button variants
- [../../web/src/styles/components/popups.css](../../web/src/styles/components/popups.css) - Modals, toasts, overlays
- [../../web/src/styles/components/planner.css](../../web/src/styles/components/planner.css) - Planner dashboard

**Components:**
- [../../web/src/components/Messages.ts](../../web/src/components/Messages.ts) - Message display
- [../../web/src/components/Sidebar.ts](../../web/src/components/Sidebar.ts) - Conversation list
- [../../web/src/components/MessageInput.ts](../../web/src/components/MessageInput.ts) - Input area
- [../../web/src/components/Modal.ts](../../web/src/components/Modal.ts) - Modal dialogs
- [../../web/src/components/Toast.ts](../../web/src/components/Toast.ts) - Toast notifications
- [../../web/src/components/PlannerDashboard.ts](../../web/src/components/PlannerDashboard.ts) - Planner dashboard
- [../../web/src/components/PlannerView.ts](../../web/src/components/PlannerView.ts) - Planner view

**Utilities:**
- [../../web/src/utils/dom.ts](../../web/src/utils/dom.ts) - DOM helpers
- [../../web/src/utils/icons.ts](../../web/src/utils/icons.ts) - SVG icon constants
- [../../web/src/utils/popupEscapeHandler.ts](../../web/src/utils/popupEscapeHandler.ts) - Centralized Escape handler

**State:**
- [../../web/src/state/store.ts](../../web/src/state/store.ts) - Zustand store

**Main:**
- [../../web/src/main.ts](../../web/src/main.ts) - Entry point
- [../../web/src/core/init.ts](../../web/src/core/init.ts) - App initialization

**Template:**
- [../../src/templates/index.html](../../src/templates/index.html) - HTML shell

## See Also

- [Mobile and PWA](mobile-and-pwa.md) - Mobile-specific UI patterns
- [Scroll Behavior](scroll-behavior.md) - Scroll handling and pagination
- [Testing](../testing.md) - Component testing strategies
