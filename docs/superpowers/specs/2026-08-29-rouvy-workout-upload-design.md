# Rouvy Workout Upload Integration — Design

- **Date:** 2026-08-29
- **Status:** Approved (design); implementation pending
- **Author:** Jiri Brunclik + Claude

## Context & motivation

The sports agent generates structured cycling workouts as ZWO files (Zwift/Rouvy
XML) for the user to ride in Rouvy. Today the agent hands the user a downloadable
`.zwo` via the `create_file` tool, and the user manually drags it into Rouvy's
Riders Portal. This integration removes that manual step: the agent uploads the
workout straight into the user's Rouvy account.

Rouvy has **no public API** — official API tokens are B2B-only and not available
for this deployment. The integration therefore replicates the authenticated web
flow, mirroring the structure of the existing Garmin integration.

## Goals

- A `rouvy_upload_workout` agent tool the sports agent can call to push a
  workout (ZWO/ERG/MRC text) into the user's Rouvy account.
- Per-user connect/disconnect in Settings, mirroring the Garmin section.
- Automated session refresh so uploads keep working without frequent manual
  reconnects.

## Non-goals (YAGNI for v1)

- Scheduling a workout onto a specific calendar date.
- Listing / editing / deleting Rouvy workouts.
- `.erg` / `.mrc` generation or conversion (the agent authors ZWO directly).
- Any use of official Rouvy B2B API tokens.

## Confirmed API facts (from live recon, 2026-08-29)

Established by logging into the production portal, uploading a throwaway ZWO
(which parsed correctly — duration, TSS, power targets), and deleting it.

- **Upload endpoint:** `POST https://riders.rouvy.com/resources/workout-upload.data`
  - `multipart/form-data`, file field name **`workout`**.
  - Accepts `.zwo`, `.erg`, `.mrc`.
  - On success creates a workout (Private by default) and returns its id; the
    portal then refetches `GET /workouts.data`.
- **Auth:** session **cookies** scoped to `.rouvy.com`, obtained from the
  identity provider `account.rouvy.com` via an email-first flow:
  `POST /sign-in` (email) → `POST /login` (password) → redirect to
  `riders.rouvy.com/feed`. No OAuth, no social login.
- **reCAPTCHA:** the login page carries an **invisible** reCAPTCHA
  (`RECAPTCHA_KEY` in the SPA config); no interactive checkbox/challenge
  appeared during a real-browser login. A headless server login therefore has
  no challenge to *solve*, but may still be scored low and blocked — see Risks.
- The portal is a React-Router (single-fetch, `.data`) SSR app.

## Key decisions

1. **Auth / refresh model — store password, auto-refresh (user-approved).**
   Store the user's Rouvy email + password Fernet-encrypted (alongside the
   cookie blob). On upload, if the stored cookie is missing/expired, a headless
   Playwright login silently re-acquires it. If the headless login is ever
   blocked (reCAPTCHA), fall back to asking the user to reconnect in Settings.
   This is a deliberate departure from the Garmin integration, which never
   persists the password (Garmin's tokens last ~1 year; Rouvy cookie lifetime is
   unknown and likely shorter, so automated refresh needs the credentials).

2. **Playwright only for login → cookie; `httpx` for the upload.** Playwright is
   used solely to get past login/reCAPTCHA and capture cookies. The upload is a
   plain authenticated `httpx` multipart POST — no Chromium in the hot path.

3. **Isolated login worker.** The login path runs on its own self-contained
   Playwright worker, separate from the shared agent `browser` tool (which is
   explicitly forbidden from entering credentials and is SSRF-gated).

## Architecture & components

| Component | File | Responsibility |
|---|---|---|
| Auth/session module | `src/auth/rouvy_auth.py` | Headless Playwright login → extract cookies (`context.cookies()`) → serialize JSON blob. Owns its own Playwright lifecycle on a dedicated thread. Classifies login failures. |
| DB fields | migration `00NN_add_rouvy_fields.py`, `src/db/models/user.py`, `src/db/models/dataclasses.py` | `users.rouvy_email`, `rouvy_password`, `rouvy_session` (all Fernet), `rouvy_connected_at`. Decrypt on hydration in `User.from_row`. |
| Upload client + tool | `src/agent/tools/rouvy.py` | `httpx` multipart POST to the upload endpoint with stored cookies; expired→refresh→retry-once. Exposes `rouvy_upload_workout` `@tool`. |
| Connect API | `src/api/routes/rouvy.py`, `src/api/schemas.py` | `POST /auth/rouvy/connect`, `GET /auth/rouvy/status`, `POST /auth/rouvy/disconnect`. No MFA (Rouvy has none). |
| Settings UI | `web/src/components/SettingsPopup.ts`, `web/src/api/client.ts` | "Rouvy" section: email/password + Connect/Disconnect, mirroring `renderGarminSection`. |
| Tool registration & gating | `src/agent/tools/__init__.py` | `is_rouvy_available()`, add to `get_available_tools`/`_TOOL_MAP`, keep **out** of `_SPORTS_EXCLUDED_TOOLS`. |

## Data model

New columns on `users` (all nullable TEXT), following the `garmin_token` /
`garmin_connected_at` precedent (migration `0028`):

- `rouvy_email` — Fernet-encrypted.
- `rouvy_password` — Fernet-encrypted.
- `rouvy_session` — Fernet-encrypted JSON cookie blob (`context.cookies()` shape:
  name, value, domain, path, expires, httpOnly, secure).
- `rouvy_connected_at` — ISO timestamp.

Encryption reuses `src/utils/token_crypto.py` (`encrypt_token`/`decrypt_token`,
key = `Config.TOKEN_ENCRYPTION_KEY`). `User.from_row` decrypts all three secret
columns on hydration, matching the Garmin pattern. Write path: a
`db.update_user_rouvy_*` method that encrypts on the way in.

## Data flow

### Connect (Settings, one-time)

1. `POST /auth/rouvy/connect {email, password}` (HTTPS).
2. `rouvy_auth.login(email, password)`: launch ephemeral context → `sign-in`
   (fill email, Continue) → `login` (fill password, submit) → wait for redirect
   to `riders.rouvy.com/feed` → `context.cookies()` → serialize → close.
3. Success → store `enc(email)`, `enc(password)`, `enc(cookies)`,
   `rouvy_connected_at=now`; return `{connected:true}`.
4. Failure → classify, store nothing, return `{connected:false, error}`.

### Upload (agent tool, per request)

1. Agent authors the ZWO and calls
   `rouvy_upload_workout(content, name, description?)`.
2. Load `user.rouvy_session`. Absent → `{error:"not connected — connect Rouvy in
   Settings", retriable:false}`.
3. `httpx` multipart POST to the upload endpoint (field `workout` = filename +
   content), cookies attached.
4. Success → parse created id → `{success:true, workout_url}`.
5. Expired (401 / redirect to sign-in / login-HTML instead of `.data`) →
   `rouvy_auth.login()` with stored creds → re-persist cookies → retry POST once.
6. Re-login fails → `{error:"session expired and refresh failed — please
   reconnect in Settings", retriable:false}`.

No cross-worker in-memory cache (matches the multi-gunicorn-worker constraint):
each upload reads cookies from the DB; refresh writes them back.

## Login worker

Sync Playwright cannot be shared across threads, so login runs on a dedicated
thread that owns the entire Playwright lifecycle (launch → context → login →
cookies → close → stop). Kept separate from the shared agent `browser` worker
because this path enters credentials. Headless; launch args reuse the existing
`_browser_launch_args()` conventions. Bounded by `ROUVY_LOGIN_TIMEOUT_MS`.

## Error handling

- **Login:** `invalid_credentials` ("email or password is wrong"),
  `captcha_blocked`, `timeout`, `unknown` — each a friendly message.
- **Upload:** `not_connected`, `session_expired_refresh_failed`,
  `invalid_workout` (Rouvy rejects the file), `http_error`.
- **Never log** email / password / cookies — redacted everywhere.

## Security

- Password at rest: Fernet (existing `TOKEN_ENCRYPTION_KEY`). Deliberate,
  user-approved departure from Garmin's no-password model; documented here.
- Connect accepted over HTTPS only in production.
- Credentials/cookies never written to logs or tool results.

## Config

- Reuse `TOKEN_ENCRYPTION_KEY` (no new secret).
- New: `ROUVY_LOGIN_TIMEOUT_MS` (default ~45000). Constants for the base URLs
  (`account.rouvy.com`, `riders.rouvy.com`) in `config.py`/`constants.py`.
- Availability requires Chromium (login needs it): `is_rouvy_available()` =
  `Config.BROWSER_ENABLED and is_browser_available()`.
- Document in `.env.example` and `docs/features/`.

## Testing

- **Unit (no network — the bulk):**
  - Cookie serialize/deserialize round-trip.
  - Login error-classification from mocked page states (Playwright mocked).
  - Upload client with mocked `httpx`: asserts field name `workout`, URL,
    cookies attached, success parsing, **and the expired→refresh→retry path**.
  - Tool gating: `is_rouvy_available`, per-user not-connected behavior, presence
    in sports toolset & `_TOOL_MAP`, absence from `_SPORTS_EXCLUDED_TOOLS`.
  - DB encrypt/decrypt round-trip + `from_row` hydration.
  - Routes: connect stores creds (login mocked), status, disconnect clears.
- **No live-Rouvy calls in CI** — everything mocked.
- **One manual real verification** during the build (using local `.tmp` creds
  while they exist): real connect + real upload + delete, like the recon, to
  confirm the `httpx` replay works past any CSRF/single-fetch header
  requirement.

## Open risks

1. **httpx replay of `/resources/workout-upload.data`.** The endpoint is a
   React-Router single-fetch action; it may require headers beyond cookies
   (e.g. a client-minted CSRF token). **Mitigation:** validate this first, before
   building the full tool. If httpx cannot replay it, fall back to driving the
   upload through Playwright (navigate → set file input → submit).
2. **Headless reCAPTCHA on refresh.** A headless/datacenter login may be scored
   low and blocked, breaking automated refresh. **Mitigation:** the design
   degrades gracefully to manual reconnect; hardening (persistent profile /
   stealth / xvfb) is deferred until refresh is observed to fail in practice.
3. **Cookie lifetime unknown.** If sessions are very short-lived, refresh runs
   often; the stored password makes this automatic, but frequent Chromium
   launches have a cost. Acceptable for a single-family deployment.

## Rollout / verification

- Ship behind the same availability gate as other integrations (no separate
  feature flag needed; gated by browser availability + per-user connect state).
- Verify end-to-end locally (connect + upload + delete) before deploying.
