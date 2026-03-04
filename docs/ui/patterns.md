# UI/UX Patterns

Standard interaction and visual patterns used across the app. Follow these when building new features to maintain consistency.

## Page/Section Layout

### Feature Landing Page (Programs List, Command Center)

Every feature's main page follows the same header structure:

```
┌────────────────────────────────────────────┐
│  [Icon] Feature Title      [+ New Thing]   │
│────────────────────────────────────────────│
│                                            │
│  [Card]  [Card]  [Card]                    │
│                                            │
└────────────────────────────────────────────┘
```

- **Title row**: Feature icon (SVG, accent color) + gradient `h2` + action buttons (right-aligned)
- **Action button**: Accent background, white text, `PLUS_ICON` + label (e.g., "New Program", "New Agent")
- **Cards**: Grid layout with `auto-fill, minmax(280px, 1fr)`, single column on mobile
- **Empty state**: Centered text with muted hint

**Reference**: `CommandCenter.ts` (agents), `SportsDashboard.ts` (sports)

### Detail View Header (Program Chat, Agent Conversation)

When drilling into a specific item's conversation/detail view, add a sticky header:

```
┌────────────────────────────────────────────┐
│  [←] [Icon] Item Name         [Actions]    │  ← sticky, stays visible on scroll
└────────────────────────────────────────────┘
```

- **Back button**: Chevron-left SVG, bordered, returns to parent list view
- **Item identity**: Emoji/icon + name (truncated with ellipsis)
- **Actions**: Right-aligned action buttons (Reset, Edit, etc.) using `btn-icon` class
- **Sticky**: `position: sticky; top: 0; z-index: 10;` — always visible when scrolling through messages
- **Background**: `var(--bg-secondary)` with bottom border to separate from content
- **Prepend**: Header element is prepended to the messages container (before messages)

**Reference**: `createSportsProgramHeader()` (sports), `createAgentConversationHeader()` (agents)

## Cards

### Feature Cards (Program Cards, Agent Cards)

Cards are clickable containers that navigate to a detail view:

- **Structure**: Icon/emoji + name + action buttons (right side)
- **Hover**: `border-color: var(--accent)`, `box-shadow: 0 4px 12px`, `translateY(-2px)`
- **Cursor**: `pointer` on the whole card
- **Actions**: Use `btn-icon` class (grey bg, border, icon-only or icon+label)
  - Primary action (Continue/Run): `PLAY_ICON` + label
  - Destructive action (Delete): `DELETE_ICON`, hover turns red
- **Click handling**: Card click = navigate; action button clicks use `stopPropagation()`

**Reference**: `agents.css` (`.agent-card`, `.btn-icon`), `sports.css` (`.sports-program-card`)

### Button Styles on Cards

| Type | Class | Style | Use |
|------|-------|-------|-----|
| Primary action | `btn-icon` + specific class | Grey bg, border | Continue, Run, Edit |
| Destructive | `btn-icon` + delete class | Grey bg, red on hover | Delete |
| Header action | Feature-specific | Accent bg, white text | New Program, Refresh |

## Modals and Dialogs

### Confirmation Dialog

Use `showConfirm()` from `Modal.ts` for destructive actions:

```typescript
const confirmed = await showConfirm({
  title: 'Delete Program',
  message: 'Delete "Push-ups"? This will also delete all training data.',
  confirmLabel: 'Delete',
  danger: true,  // Red confirm button
});
```

Never use browser `confirm()` or `alert()`.

### Creation Modal (New Program, New Agent)

For creating new items, use an overlay modal (not a separate page):

```
┌─ Overlay (rgba(0,0,0,0.5)) ──────────────┐
│                                            │
│  ┌─ Modal ──────────────────────────────┐  │
│  │  [Icon] Title              [×]       │  │
│  │──────────────────────────────────────│  │
│  │                                      │  │
│  │  [Form fields]                       │  │
│  │                                      │  │
│  │──────────────────────────────────────│  │
│  │               [Cancel] [Create]      │  │
│  └──────────────────────────────────────┘  │
│                                            │
└────────────────────────────────────────────┘
```

- **Overlay**: Fixed inset, z-index 1000, click outside closes
- **Modal**: Max-width ~440px, bg-secondary, border, box-shadow
- **Header**: Icon + title + close button
- **Footer**: Cancel (grey, border) + Submit (accent bg, white)
- **Keyboard**: Escape closes, auto-focus first input
- **Animation**: Scale 0.95→1 + opacity fade in, reverse on close

**Reference**: `AgentEditor.ts`, `SportsDashboard.ts` (`showNewProgramModal`)

## Navigation

### Sidebar Nav Row

Multiple feature entries share a flex row in the sidebar:

- **Single entry**: Shows icon + label, `flex: 1`
- **Multiple entries**: Labels hidden, icon-only buttons, centered in equal flex cells
- **Active state**: `accent-muted` background via `.active` class
- **Hover**: `bg-hover` background

### Deep Links

All features use hash-based routing (`#/feature` and `#/feature/{id}`):

- Parse in `deeplink.ts` with `parseHash()`
- Set programmatically via `setFeatureHash()` with `isIgnoringHashChange` guard
- Handle in `handleDeepLinkNavigation()` and initial route loading in `init.ts`
- Always support both list view (`#/sports`) and detail view (`#/sports/pushups`)

### View Transitions

When navigating between views:

1. Set navigation token (`store.startNavigation()`) for race condition prevention
2. Clean up previous view (streaming, scroll listeners, banners)
3. Update store state flags
4. Set hash
5. Show loading state
6. Fetch data
7. Verify navigation token still valid before rendering
8. Render and restore UI state (scroll, focus)

## Cost Tracking

Cost tracking is built into the messaging system and works for all conversation types:

- **Per-conversation**: `#conversation-cost` element, updated via `updateConversationCost(convId)`
- **Monthly total**: `#monthly-cost` in sidebar, updated via `updateMonthlyCost()`
- **Persistence**: Costs survive conversation resets (stored in `message_costs` table by `user_id`)
- **Display**: Call `updateConversationCost(convId)` when loading a conversation

## Emoji Picker

For user-selectable icons (program emoji, etc.), use the popover pattern:

- **Trigger**: Large button (44px) showing current emoji
- **Popover**: Absolute-positioned grid (6 columns), opens on click
- **Close**: Click outside or select an emoji
- **Z-index**: 50+ to float above form content

## Loading States

- **Page loading**: Centered spinner + text (`.sports-loading`, `.planner-loading`)
- **Button loading**: Disable button, optionally show spinner
- **Skeleton**: Not currently used, but consider for card grids

## Accessibility

All interactive elements need:

- `:focus-visible` outline: `3px solid var(--accent)`, `outline-offset: 2px`
- `title` attributes on icon-only buttons
- `role="dialog"` + `aria-modal="true"` on modals
- Keyboard navigation (Escape closes modals/popovers)

## Mobile (768px breakpoint)

- Title rows stack vertically (`flex-direction: column`)
- Action buttons go full-width
- Card grids become single-column
- Reduced padding (`space-4` → `space-3`)
- `prefers-reduced-motion`: disable `transform` animations and spinners

## Toast Notifications

Use `toast` from `Toast.ts` for user feedback:

```typescript
toast.success('Program created.');
toast.error('Failed to delete program.');
```

Keep messages short (under 50 chars). Use for confirmation of actions and error feedback.
