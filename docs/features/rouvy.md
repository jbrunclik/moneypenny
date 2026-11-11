# Rouvy Integration

Lets the sports agent manage a user's **Rouvy** (indoor cycling) workouts — upload
an agent-authored ZWO straight into the user's account, list/get/delete them, and
"update" (delete + create). Removes the manual "download the ZWO, drag it into the
Riders Portal" step.

Rouvy has **no public API** (official tokens are B2B-only), so the integration
replicates the authenticated web flow, mirroring the Garmin integration.

## How it works

- **Auth:** Rouvy has no OAuth. Connect (in Settings) runs a **headless Playwright
  login** at `account.rouvy.com` (email → password; invisible reCAPTCHA, which a
  headless login passes in practice) and captures the `.rouvy.com` session cookies.
- **Storage:** the session cookie **and** the email + password are stored
  Fernet-encrypted on the `users` table (`rouvy_session`, `rouvy_email`,
  `rouvy_password`, `rouvy_connected_at`), reusing `TOKEN_ENCRYPTION_KEY`. The
  password is persisted (a deliberate departure from Garmin) because Rouvy sessions
  are short-lived and auto-refresh needs to re-login.
- **CRUD:** all operations are plain `httpx` calls to the `riders.rouvy.com`
  React-Router `.data` endpoints, authenticated by the stored cookie — Playwright is
  used **only** for (re)login, never in the CRUD hot path. On an expired session the
  client re-logs-in with the stored credentials, re-persists the cookie, and retries
  once; if refresh fails (e.g. reCAPTCHA blocks a headless login), the user is told
  to reconnect.
- **Token rotation (pitfall):** `rouvy_session` wraps a **1-hour Firebase id
  token** plus a refresh token. Once the id token has expired, Rouvy does *not*
  401 — it refreshes the token server-side, rotates the cookie via `Set-Cookie`,
  and answers with a turbo-stream **redirect to the same URL** (HTTP 202,
  `"redirect",<same url>,"status",302`) instead of running the loader/action.
  The client must persist the rotated cookie and retry once
  (`_persist_rotated_cookies` / `_is_refresh_redirect`); before this was handled
  (Sep 2026) every call made more than an hour after connect silently failed:
  `list` parsed to `[]` and `create` raised "could not parse created workout id".
  A successful **delete** also answers with a redirect (to `/workouts`) but rotates
  no cookie — the cookie rotation is the distinguishing signal.

### Confirmed endpoint contract

All cookie-authed; responses are turbo-stream (`text/x-script`). The create reply is decoded (`_turbo_data`: one JSON array of interned values, objects map `"_<key index>"` to a value index, negative = undefined); list still uses a regex. Nov 2026 pitfall: the id turned into a quoted string and the old unquoted-number regex reported every upload as failed, so the agent's retries made duplicates; a reply that doesn't decode is logged by shape only (`Rouvy create reply not understood`: status, content type, length, field names - never values, since replies can carry the user's profile).

| Op | Request |
|----|---------|
| create | `POST /resources/workout-upload.data`, multipart field **`file`** → `data.workoutId` (quoted since Nov 2026: `"workoutId","4904455"`), or `data.error` ("Failed to import workout") on a rejected file |
| delete | `POST /workouts/{id}.data`, urlencoded body **`id=<id>`** |
| list | `GET /workouts/collections/created.data` (the user's created workouts) |
| get | `GET /workouts/{id}.data` (unknown id: 404) |

Replies checked against the live service on Nov 11 2026 (probe: login, create
valid + broken, list, get, get unknown, dead session, no session, delete):

- **Delete** answers 202 with a single-fetch redirect to `/workouts` (success).
- **A dead or missing session** answers **202** with a single-fetch redirect to
  `account.rouvy.com/sign-in` - not a 401/403 or an HTML login page. Before Nov
  11 the tool missed it (list read "no workouts", create "could not parse");
  `_is_sign_in_redirect` now counts it as expired, which re-logs in.
- **Cloudflare's bot challenge** ("Just a moment...", 403 HTML, or the
  `cf-mitigated: challenge` header) answers any request it does not trust - in
  Nov 2026 every request with httpx's default `python-httpx` User-Agent, while
  the same request with a browser User-Agent passed. It is reported as
  `RouvyBlockedError` ("Rouvy is blocking automated access") with no re-login:
  treating it as an expired session started a ~50 s login that hit the same wall.
- The headless login is blocked the same way since Nov 2026: right after the
  password step `riders.rouvy.com/login?token=...` serves Cloudflare's "Sorry, you
  have been blocked" to a browser calling itself `HeadlessChrome`; the same
  login with that word removed from the User-Agent reaches `/feed`.
- **Fix (Nov 11 2026):** the login presents the browser's own User-Agent minus
  "Headless" (`browser_user_agent`), and the stored session is now
  `{"cookies": [...], "user_agent": "..."}` so every httpx request sends the
  identity the login's cookies (incl. Cloudflare's `__cf_bm`) were issued to.
  Old bare-list sessions read fine and send `FALLBACK_USER_AGENT`. This works
  around Rouvy's bot protection for the user's own account (Jiri's call); if
  Rouvy tightens it, the fallback plan is a session the user hands over from
  their own browser, kept fresh in the background.
- **List** returned exactly 30 workouts for an account with more: possibly the
  first page only (`pageMeta`) - unverified.

## The tool

`rouvy_workout(action, workout_id?, content?, name?, description?)` — actions:
`list`, `get`, `create` (upload ZWO), `delete`, and `update` (= delete + create, so
the workout id/URL **changes**). Gated on the browser tool (Chromium, needed for
login) and per-user connect state. Available in sports program chats (they get the full chat tools).

## Key files

- Auth/login: [src/auth/rouvy_auth.py](../../src/auth/rouvy_auth.py)
- Client + tool: [src/agent/tools/rouvy.py](../../src/agent/tools/rouvy.py)
- Routes: [src/api/routes/rouvy.py](../../src/api/routes/rouvy.py) (`/auth/rouvy/connect|status|disconnect`)
- Settings UI: [web/src/components/settings/rouvy.ts](../../web/src/components/settings/rouvy.ts)
- DB columns: migration `0052_add_rouvy_fields.py`

## Non-goals

- No native structured edit (Rouvy's edit UI posts internal JSON, not ZWO — hence
  `update` = delete + create).
- No scheduling to a calendar date, no `.erg`/`.mrc` conversion, no B2B API tokens.

## Config

No secret required (reuses `TOKEN_ENCRYPTION_KEY`). Optional overrides:
`ROUVY_ACCOUNT_URL`, `ROUVY_RIDERS_URL`, `ROUVY_LOGIN_TIMEOUT_MS`,
`ROUVY_HTTP_TIMEOUT_SECONDS` (see `.env.example`).
