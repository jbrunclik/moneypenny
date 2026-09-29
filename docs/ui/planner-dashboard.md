# Planner Dashboard UI

The frontend of [Planner mode](../features/planner.md): a dashboard of calendar events,
tasks, weather and Garmin health metrics rendered above the planner conversation.

## Dashboard Container

`createDashboardElement()` in [PlannerDashboard.ts](../../web/src/components/PlannerDashboard.ts)
builds a `.planner-dashboard-message` element that is inserted at the top of
`#messages`. It is deliberately **not** a `.message`, so message pagination and
message-count logic ignore it. While data loads, the same container renders with a
`loading` class and the bouncing-dots loader (`.dashboard-loading`).

Content order (`buildDashboardContent`):

1. **Health summary strip** (`.health-summary-strip`) - resting HR, Body Battery, stress,
   steps; only when Garmin is connected and returned data
2. **Errors** (`.dashboard-error`) - Todoist, Calendar, Garmin or weather errors
3. **Overdue** (`.dashboard-section.overdue`) - only when there are overdue tasks
4. **Today** and **Tomorrow** (`.dashboard-day`) - always expanded; today gets the
   "Now" line (`.time-indicator`) and dims past events (`data-past="true"`)
5. **Rest of the week** (`.dashboard-section.week`) - a collapsible `<details>`
6. **Empty state** (`.dashboard-empty`) - no events, tasks or overdue items

## CSS Classes

- **Header**: `.dashboard-header`, `.dashboard-title` (`.dashboard-title-text` in the
  display face, `.dashboard-date`), `.dashboard-actions` with `.planner-refresh-btn`
  (refetch, bypassing the cache) and `.planner-reset-btn` (clear the conversation and
  trigger a new proactive analysis)
- **Days**: `.dashboard-day`, `.dashboard-day-header` (`.dashboard-day-name`,
  `.dashboard-day-meta`, `.weather-badge`), `.dashboard-day-empty`,
  `.dashboard-events` / `.dashboard-tasks` groups
- **Items**: `.planner-item` plus `.planner-item-event` (with `.all-day`) or
  `.planner-item-task`; `.planner-item-time` (events), `.planner-task-ring` (tasks),
  `.planner-item-body` holding `.planner-item-title` and chips
  (`.planner-item-calendar`, `.planner-item-project`, `.planner-item-location`), and
  `.planner-item-copy`

## Visual Patterns

- **Priority** is carried by the task ring's color, a checkbox-like 14px circle:
  muted (P1), info blue (P2), warning amber (P3), error red with a 2px border (P4) -
  `.planner-item[data-priority="N"] .planner-task-ring` in `planner.css`.
- **Chips**: calendar name (non-primary calendars only), Todoist project and location
  are small inline chips in the row body (`--font-size-xs`, `--bg-tertiary`,
  `--radius-xs`); location links open Google Maps in a new tab and use `--accent-hover`
  text instead of a filled pill.
- **Copy button**: every item carries `data-copy-text`; `.planner-item-copy` is hidden
  (`opacity: 0`) until row hover or focus, and shows a success-colored `.copied` state.
- **Past events** dim to `opacity: 0.45`.

## Mobile Responsive

Under 768px:

- Items wrap: the event time stacks above the title (`.planner-item-body` takes the
  full row)
- The event copy button is pinned to the row's top-right corner
- Copy buttons stay discoverable on touch (`opacity: 0.55`, 32px target)
- Refresh / Reset become icon-only 40px touch targets
- Reduced padding; smaller weather badge

## Scroll Behavior

Planner scrolls to the **top** (to show the dashboard), unlike normal chats which scroll
to the latest message:

```typescript
// In core/planner.ts, after rendering the dashboard and messages
messagesContainer.scrollTop = 0; // NOT scrollToBottom()
```

## Accessibility

- `:focus-visible` outlines on the refresh/reset buttons, copy buttons, location links
  and the week `<summary>`
- `aria-label` on icon-only copy buttons; the task ring is `aria-hidden`
- Animations follow the global `prefers-reduced-motion` rule in `base.css`

## Testing

- E2E: 23 tests in [planner.spec.ts](../../web/tests/e2e/planner.spec.ts), including UI
  state resets when navigating to and from the planner (model selector shows the
  planner's model, cost display cleared)
- Visual: 24 snapshots in [planner.visual.ts](../../web/tests/visual/planner.visual.ts)
- Details and fixtures: [Frontend and E2E Testing](../testing/frontend.md#planner-tests)

## Key Files

- [web/src/components/PlannerDashboard.ts](../../web/src/components/PlannerDashboard.ts) - dashboard rendering, copy handlers
- [web/src/components/PlannerView.ts](../../web/src/components/PlannerView.ts) - planner view container
- [web/src/core/planner.ts](../../web/src/core/planner.ts) - `navigateToPlanner()`, refresh/reset handlers
- [web/src/styles/components/planner.css](../../web/src/styles/components/planner.css) - dashboard styles

## See Also

- [Planner](../features/planner.md) - backend, dashboard data shape, caching, weather
- [Design System](design-system.md) - tokens used by the dashboard
- [Routing Race Condition Prevention](../features/agents.md#routing-race-condition-prevention) - navigation token used by `navigateToPlanner()`
