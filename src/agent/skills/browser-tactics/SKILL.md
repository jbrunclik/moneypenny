---
name: browser-tactics
description: Driving the browser tool on real sites - batching actions, choosing selectors from `elements`, screenshots, cookie banners, timeouts, and the step budget. Load BEFORE the first browser call of a task.
---
# Browser tactics

## Batches (`actions`)

When you already know the steps - a known URL, then fill a field, then click submit -
send them as one `actions` list instead of one call per step, e.g.
`actions=[{"action": "navigate", "url": "..."}, {"action": "type", "selector": "#q",
"text": "..."}, {"action": "click", "selector": "button[type=submit]"}]`.
Steps run in order and stop at the first failure (the result says which step failed).
Batchable: navigate, click, type, scroll, back, extract.

## Page state

navigate/click/type/scroll/back return `elements`: the visible buttons, links and
inputs with ready-to-use selectors. Prefer those selectors over guessing.

## Screenshots

- `screenshot=True` on any action or batch takes a screenshot (after the last step)
  for YOU to see the page; the `screenshot` action does the same on its own.
- `share_screenshot=True` also shares it with the user as a visible attachment.

Use internal screenshots freely for navigation (finding elements, understanding layout).
Only share screenshots when the result is relevant to the user (final page, visual answer).

## Tactics

- Batch known sequences: when you already know the steps (navigate to a known URL, fill a field, click submit), send them as ONE call with `actions=[...]` instead of one call per step. On an unfamiliar page, look first (navigate returns the page's `elements` with ready-to-use selectors), then batch the rest
- Never issue several separate browser calls in parallel - the session is shared, so they would race; use `actions` for sequences
- If a click or action fails with a timeout, do NOT retry the same selector. Take a screenshot
  to reassess, try a different selector, or fall back to `extract` to get the page content as text
- **Turn budget**: Each tool call uses a graph step. You have ~20 tool calls per request before
  hitting the limit. Plan your browsing efficiently — navigate, read the returned `elements`, then batch the actions.
  Do not spend more than 3-4 browser actions on a single page. If stuck, use `extract` instead
- Cookie banners and consent dialogs are common — if they block interaction, try clicking
  common accept buttons (e.g., `#accept`, `.consent-accept`, `button:has-text("Accept")`).
  If that fails after one attempt, just use `extract` — the text content is usually accessible
