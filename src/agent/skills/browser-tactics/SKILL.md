---
name: browser-tactics
description: Driving the browser tool on real sites - batching actions, choosing selectors from `elements`, cookie banners, timeouts, and the step budget. Load BEFORE the first browser call of a task.
---
# Browser tactics

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
