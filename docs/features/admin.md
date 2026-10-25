# Admin Page and Spend Warning

A read-only overview for the accounts listed in `ADMIN_EMAILS`, and a neutral
banner for anyone whose spend passes a daily threshold (rule S12 in
[conventions.md](../conventions.md)). Shipped Oct 25 2026.

## Who sees what

- **Admins** (`ADMIN_EMAILS`, comma-separated; empty = nobody) get an **Admin**
  entry in the user menu. `/auth/me` and the sign-in response carry
  `is_admin`; the API checks it again (`require_admin`, 403 otherwise).
- **Everyone** whose spend today passes `SPEND_WARNING_DAILY_USD` (default 10)
  sees: "Unusually high usage today ({amount}). If this is unexpected, let the
  admin know." Dismissed, it stays away for that calendar day (localStorage).
  No notification, never a block. Checked at startup and after every turn
  (`updateConversationCost` in `core/toolbar.ts`). "Today" is the server's
  local day, like the planner's reset.

## The page

A full-screen overlay (Back or Escape closes it; focus is trapped while open),
not a routed view - so there is no `#/admin` link. Sections:

| Section | Shows | Source |
|---|---|---|
| Spend | today and this month (family and per person, highlighted past the threshold), 30-day bars, split by feature and by model | `message_costs` |
| Agents | runs and failures over 7 days, the latest 5 failures (local time; only the error's first line, cut to 120 characters - an error can quote content), pending approvals | `agent_executions`, `agent_approval_requests` |
| Web search | each provider's use against its monthly quota this billing period, whether it's usable now, whether search fell back to the free provider today | `search_provider.quota_status()` |
| Responses | turns over 7 days, median and 95th-percentile duration, share with tool errors | `message_costs` |
| System | deployed version, `chatbot.db` and `files.db` sizes, last backup, latest migration, users | files on disk, `_yoyo_migration` |

**Privacy:** names and numbers only. The overview never carries conversation
titles or content (an integration test checks it). Spend from purged
conversations still counts, as "Deleted chats".

## Code

- Backend: `src/auth/admin.py` (`is_admin`, `require_admin`),
  `src/db/models/admin.py` (the queries), `src/api/helpers/admin_overview.py`
  (assembly, currency formatting), `src/api/routes/admin.py`
  (`GET /api/admin/overview`, `GET /api/users/me/spend-status`),
  `src/api/schemas/admin.py`.
- Frontend: `web/src/components/AdminPage.ts`, `web/src/components/SpendBanner.ts`,
  `web/src/api/admin.ts`, `web/src/styles/components/admin.css`; types are
  aliases of the generated schemas (`AdminOverview`, `SpendStatus`).

## Testing

- `tests/unit/test_admin_access.py`, `tests/unit/test_admin_queries.py`,
  `tests/integration/test_routes_admin.py` (403, shape, no content leak).
- `web/tests/component/admin-page.test.ts`, `spend-banner.test.ts`.
- `web/tests/e2e/admin.spec.ts` - the E2E server lists `local@localhost` in
  `ADMIN_EMAILS`; `/test/seed` accepts `cost_usd` on a message to seed spend.
- `web/tests/visual/admin.visual.ts` (desktop and mobile, fixed JSON).

## Ideas not built (yet)

Per-user integration health (expired Calendar/Garmin tokens), the grounding
verifier's verdict mix (only in the logs today), and a deep-research cost line.
