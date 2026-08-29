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

### Confirmed endpoint contract

All cookie-authed; responses are turbo-stream (`text/x-script`), parsed by regex.

| Op | Request |
|----|---------|
| create | `POST /resources/workout-upload.data`, multipart field **`file`** → `"workoutId",<id>` |
| delete | `POST /workouts/{id}.data`, urlencoded body **`id=<id>`** |
| list | `GET /workouts/collections/created.data` (the user's created workouts) |
| get | `GET /workouts/{id}.data` |

## The tool

`rouvy_workout(action, workout_id?, content?, name?, description?)` — actions:
`list`, `get`, `create` (upload ZWO), `delete`, and `update` (= delete + create, so
the workout id/URL **changes**). Gated on the browser tool (Chromium, needed for
login) and per-user connect state. Available to the sports agent (not excluded).

## Key files

- Auth/login: [src/auth/rouvy_auth.py](../../src/auth/rouvy_auth.py)
- Client + tool: [src/agent/tools/rouvy.py](../../src/agent/tools/rouvy.py)
- Routes: [src/api/routes/rouvy.py](../../src/api/routes/rouvy.py) (`/auth/rouvy/connect|status|disconnect`)
- Settings UI: `renderRouvySection` in [web/src/components/SettingsPopup.ts](../../web/src/components/SettingsPopup.ts)
- DB columns: migration `0052_add_rouvy_fields.py`

## Non-goals

- No native structured edit (Rouvy's edit UI posts internal JSON, not ZWO — hence
  `update` = delete + create).
- No scheduling to a calendar date, no `.erg`/`.mrc` conversion, no B2B API tokens.

## Config

No secret required (reuses `TOKEN_ENCRYPTION_KEY`). Optional overrides:
`ROUVY_ACCOUNT_URL`, `ROUVY_RIDERS_URL`, `ROUVY_LOGIN_TIMEOUT_MS`,
`ROUVY_HTTP_TIMEOUT` (see `.env.example`).
