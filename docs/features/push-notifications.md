# Web Push Notifications

Native push notifications to the user's devices (iPhone PWA, desktop
Chrome, ...) via the Web Push protocol with VAPID. Primary notification
rail for autonomous agents; WhatsApp remains as a fallback.

## Setup

1. Generate a VAPID key pair:

   ```bash
   make push-keys
   ```

2. Add the printed values to `.env` (`VAPID_PRIVATE_KEY`,
   `VAPID_PUBLIC_KEY`, optionally `VAPID_CLAIMS_EMAIL` — falls back to
   `CONTACT_EMAIL`). Push is enabled only when both keys are set
   (`Config.push_enabled()`).

3. Each user enables notifications per device from **Settings →
   Notifications** ("Enable notifications" must run from a user gesture —
   browser requirement). "Send test" verifies the pipeline end to end.

### iOS

Push requires iOS 16.4+ **and** the app installed to the Home Screen.
The Settings section shows an "Add to Home Screen" hint when running in
Safari outside standalone mode. The PWA manifest and apple-touch icons
are already in place.

## Architecture

### Backend

- `migrations/0036_add_push_subscriptions.py` — `push_subscriptions`
  table, one row per device/browser, `endpoint` unique (re-subscribe
  upserts).
- `src/db/models/push.py` — `PushSubscriptionMixin`
  (`save_push_subscription`, `get_push_subscriptions`,
  `delete_push_subscription`, `touch_push_subscription`).
- `src/utils/push.py` — send pipeline. `send_push_to_user(user_id,
  title, body, url, tag)` is fire-and-forget: no-op without keys, runs
  on a daemon thread, sends to every subscription, deletes
  subscriptions the push service reports gone (404/410). `tag` coalesces
  notifications (same tag replaces instead of stacking). Stateless
  across gunicorn workers.
- `src/api/routes/push.py` — `GET /api/push/vapid-public-key`,
  `POST/DELETE /api/push/subscriptions`, `POST /api/push/test`
  (synchronous so the user sees the outcome).
- `/sw.js` route in `src/app.py` serves the worker from the site root —
  a service worker's scope is capped at its URL's directory, so it
  cannot live under `/static/assets/`.

### Frontend

- `web/public/sw.js` — minimal worker: `push` (show notification) and
  `notificationclick` (focus existing window + navigate, else open).
  Deliberately no caching/offline logic.
- `web/src/core/push.ts` — registration (`registerServiceWorker()` on
  app init keeps existing subscriptions alive), `enablePush()` /
  `disablePush()` / `getPushState()` / `sendTestNotification()`.
  States: `subscribed`, `not-subscribed`, `denied`, `ios-needs-install`,
  `server-disabled`, `unsupported`.
- `web/src/components/SettingsPopup.ts` — Notifications section
  rendering per state, with enable/disable toggle and test send.

### Payload

```json
{ "title": "...", "body": "...", "url": "/#/conversations/<id>", "tag": "agent-<id>" }
```

`url` is an in-app hash route; the worker navigates an existing app
window to it (or opens one).

## Current senders (Phase 1)

- **Agent execution finished** — `src/agent/executor.py` success path;
  `tag: agent-<id>` so re-runs replace the previous notification;
  deep-links to the agent's conversation.
- **Agent waiting for approval** — `ApprovalRequestedException` path;
  `tag: approval-<id>`; deep-links to `/#/agents`.

## Planned (see TODO.md)

- Turn-finished-while-backgrounded (stream journal consumed flag)
- Daily Briefing, planner reminders, program nudges, budget alerts
