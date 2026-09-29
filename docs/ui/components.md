# UI Components

How frontend components are structured, wired and styled. Tokens and the CSS file layout live in [Design System](design-system.md); the planner dashboard in [Planner Dashboard UI](planner-dashboard.md).

## Component Patterns

### Component Structure

Components are implemented as TypeScript modules with initialization functions:

```typescript
// Illustrative shape (real modules, e.g. MessageInput.ts, take callbacks)
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

Use helpers from [web/src/utils/dom.ts](../../web/src/utils/dom.ts):

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
- Setting SVG icons from [web/src/utils/icons.ts](../../web/src/utils/icons.ts) (SVG markup must be rendered as HTML)
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

Centralize SVG icons in [web/src/utils/icons.ts](../../web/src/utils/icons.ts):

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

Use Zustand store in [web/src/state/store.ts](../../web/src/state/store.ts):

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

[web/src/components/Modal.ts](../../web/src/components/Modal.ts) retains its own keydown handler because it also needs Enter (confirm) and Tab (focus trapping) handling, not just Escape.

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
  font-size: var(--font-size-xl);
  color: var(--text-primary);
  margin-bottom: var(--space-2);
}
```

### Step 3: Import in main.css

Add import to [web/src/styles/main.css](../../web/src/styles/main.css):

```css
@import './components/my-component.css';
```

### Step 4: Wire in init.ts

Initialize component in [web/src/core/init.ts](../../web/src/core/init.ts):

```typescript
import { initMyComponent } from '../components/MyComponent';

// In init function
const myComponent = initMyComponent();
```

### Step 5: Add to HTML

Add container to [src/templates/index.html](../../src/templates/index.html):

```html
<div id="my-component"></div>
```

## Chat Header

`web/src/components/ChatHeader.ts` renders the shared conversation header
into the `#chat-header` mount in the app shell (above `#messages`):

- Regular conversations: title (click to rename inline), compaction chip
  (`#conversation-compaction`, hidden until the conversation is compacted -
  see `CompactionIndicator.ts` below), per-conversation cost chip
  (`#conversation-cost`), archive + delete actions.
- Program variants: sports/language/agent conversation headers delegate to
  the same component via `renderSportsProgramHeader` /
  `renderLanguageProgramHeader` / `renderAgentConversationHeader`, passing
  a back button, emoji/icon and their action button (Reset / New Lesson /
  Edit). The variant's legacy class (e.g. `.sports-program-header`) is kept
  on the mount as a styling/test hook.
- Mobile (<= 768px) hides the header; `.mobile-header` shows the title, the
  compaction chip (`#conversation-compaction-mobile`, depth only) and a
  compact cost chip (`#conversation-cost-mobile`).
- Dashboards hide it with `renderChatHeader(null)`.

`updateChatTitle()` (messages/utils.ts) keeps both the mobile header title
and the chat header title in sync.

### Compaction indicator

`web/src/components/CompactionIndicator.ts` shows when the model no longer
sees older messages verbatim (see [Conversation Compaction](../architecture/conversation-context.md#conversation-compaction)):
the header chips (`48/72 · ×4`), a `.compaction-divider` in `#messages` after
the last summarized message with the summarized messages dimmed
(`.message--compacted`, opacity only), and a popup with the stats and the
summary text. Chip and divider turn warning-tinted at
`COMPACTION_DEEP_GENERATION` summary passes (`config.ts`).

- Refreshed by `updateConversationCost()` (toolbar.ts), i.e. on conversation
  load and at the end of every turn. The cached status is dropped as soon as
  another conversation is open.
- `applyCompactionMarkers()` is idempotent and re-run by `renderMessages()`
  and the pagination prepend (the boundary message may only arrive with an
  older page). Only the fetch-driven call passes `preserveScroll: true`:
  `#messages` has `overflow-anchor: none`, so a late insertion re-pins to the
  bottom (if following) or keeps the first visible message in place. The
  render/prepend paths manage scroll themselves - preserving there too would
  double-adjust.

## Wide Tables

On viewports >= 1200px, assistant messages containing a table widen the
whole bubble (`.message.assistant:has(.table-wrapper)`) beyond the 800px
column, up to the available chat width - the table stays inside the card
instead of overflowing it. Truly huge tables still scroll inside their
own wrapper, and the page never scrolls horizontally. Covered by the
`desktop-wide-table` visual baseline.

## UI Capture Utility

`node web/scripts/ui-capture.cjs` (dev server running) screenshots the app
across light/dark x desktop/mobile x main pages into `web/ui-captures/`
(gitignored). Use `CAPTURE_CONV='/#/conversations/<id>'` to include a rich
conversation. Use it to eyeball all four variants after UI changes -
project rule: every UI change is verified on desktop and mobile in both
themes.

## Key Files

**Components:**
- [web/src/components/messages/](../../web/src/components/messages/) - Message display
- [web/src/components/Sidebar.ts](../../web/src/components/Sidebar.ts) - Conversation list
- [web/src/components/MessageInput.ts](../../web/src/components/MessageInput.ts) - Input area
- [web/src/components/Modal.ts](../../web/src/components/Modal.ts) - Modal dialogs
- [web/src/components/Toast.ts](../../web/src/components/Toast.ts) - Toast notifications
- [web/src/components/ChatHeader.ts](../../web/src/components/ChatHeader.ts) - Conversation header
- [web/src/components/CompactionIndicator.ts](../../web/src/components/CompactionIndicator.ts) - Compaction chips, divider, popup

**Utilities:**
- [web/src/utils/dom.ts](../../web/src/utils/dom.ts) - DOM helpers
- [web/src/utils/icons.ts](../../web/src/utils/icons.ts) - SVG icon constants
- [web/src/utils/popupEscapeHandler.ts](../../web/src/utils/popupEscapeHandler.ts) - Centralized Escape handler

**State:**
- [web/src/state/store.ts](../../web/src/state/store.ts) - Zustand store

**Main:**
- [web/src/main.ts](../../web/src/main.ts) - Entry point
- [web/src/core/init.ts](../../web/src/core/init.ts) - App initialization

**Template:**
- [src/templates/index.html](../../src/templates/index.html) - HTML shell

## See Also

- [Design System](design-system.md) - CSS architecture, tokens, themes
- [UI Patterns](patterns.md) - reusable interaction and visual patterns
- [Mobile and PWA](mobile-and-pwa.md) - Mobile-specific UI patterns
- [Scroll Behavior](scroll-behavior.md) - Scroll handling and pagination
- [Frontend Testing](../testing/frontend.md) - component and E2E tests
