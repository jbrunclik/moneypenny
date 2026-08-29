# Rouvy Workout Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the sports agent full CRUD over a user's *created* Rouvy workouts (list/get/create/update/delete) via a `rouvy_workout` tool, so agent-authored ZWO workouts land directly in the user's Rouvy account.

**Architecture:** Mirror the Garmin integration. A headless Playwright login at `account.rouvy.com` captures the session cookie (refreshed automatically using a stored, Fernet-encrypted password). The cookie then authenticates plain `httpx` multipart/JSON calls to the `riders.rouvy.com` React-Router `.data` endpoints — Playwright is only used for login, never for the CRUD calls. `update` is delete-then-create.

**Tech Stack:** Python 3.14, Flask/apiflask, Playwright (sync API, already installed), httpx, yoyo migrations, Fernet (`src/utils/token_crypto.py`), TypeScript/Vite frontend.

**Spec:** `docs/superpowers/specs/2026-08-29-rouvy-workout-upload-design.md`

## Global Constraints

- Type hints on all Python; TypeScript strict mode.
- Encryption reuses `TOKEN_ENCRYPTION_KEY` via `encrypt_token`/`decrypt_token` (`src/utils/token_crypto.py`). No new secret.
- **Never log** Rouvy email, password, or cookies. Redact in every log/return path.
- The `rouvy_workout` tool MUST be available to the sports agent — keep it **out** of `_SPORTS_EXCLUDED_TOOLS`.
- Conventional Commits. Run `ruff format` after editing Python; check exit codes directly (never pipe lint/pytest through grep/tail).
- Confirmed endpoints (from recon): create `POST https://riders.rouvy.com/resources/workout-upload.data` (multipart, field `workout`); get `GET https://riders.rouvy.com/workouts/{id}.data`; the user's created workouts live under the **Created collection** (`/workouts/collections/created`), not `/workouts`. The exact **delete** endpoint and any required single-fetch headers are captured in Task 1.

---

### Task 1: De-risk spike — validate headless login + httpx replay, capture delete endpoint ✅ DONE

**COMPLETED 2026-08-29 — gate passed.** Headless Playwright login works (reCAPTCHA did not block; submit via Enter, not a named button). httpx replays all CRUD with cookies only (no special headers). Cracked contract now baked into the spec's "Confirmed API facts" and Task 5 code: create field is **`file`**; create response is turbo-stream with `"workoutId",<id>`; delete is `POST /workouts/{id}.data` body `id=<id>`; list is the Created-collection `.data`. Test account left clean. Executors: **start at Task 2.** (The steps below are retained as the record of what was validated.)

**This task gates the whole plan.** It is throwaway validation, not shipped code. It confirms the two riskiest assumptions before we build: (a) a *headless* Playwright login gets usable cookies past the invisible reCAPTCHA + cookie banner, and (b) `httpx` can replay create + delete with just those cookies (or determines the extra headers needed). It also captures the exact delete endpoint.

**Files:**
- Create (throwaway, scratchpad): `<scratchpad>/rouvy_probe.py`
- Modify: `docs/superpowers/specs/2026-08-29-rouvy-workout-upload-design.md` (fill in the confirmed delete endpoint + any required headers under "Confirmed API facts")

**Interfaces:**
- Produces (for Tasks 4–5): the exact delete request (method + URL template + body), the created-collection list request (method + URL), and the set of HTTP headers required beyond cookies for the `.data` endpoints (e.g. whether a single-fetch/CSRF header is needed).

- [ ] **Step 1: Write the probe script**

Uses the local `.tmp.rouvy.txt` credentials (present during development). Headless login → cookies → httpx create → list (created collection) → get → delete. Prints each request's status and, for delete, the exact URL used.

```python
# <scratchpad>/rouvy_probe.py  — THROWAWAY, do not commit
import json, sys, threading
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright

creds = dict(
    line.strip().split("=", 1)
    for line in Path(".tmp.rouvy.txt").read_text().splitlines()
    if "=" in line
)
EMAIL, PW = creds["ROUVY_USERNAME"], creds["ROUVY_PASSWORD"]

def login():
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        ctx = b.new_context()
        pg = ctx.new_page()
        pg.set_default_timeout(45000)
        pg.goto("https://account.rouvy.com/sign-in?riders=true&redirectTo=%2Ffeed")
        # best-effort dismiss cookie banner
        try:
            pg.get_by_role("button", name="Use necessary cookies only").click(timeout=5000)
        except Exception:
            pass
        pg.fill("input[type=email], input[name=email]", EMAIL)
        pg.get_by_role("button", name="Continue").click()
        pg.fill("input[type=password]", PW)
        pg.get_by_role("button", name="Sign in").click()
        pg.wait_for_url("**/feed", timeout=45000)
        cookies = [c for c in ctx.cookies() if "rouvy.com" in c["domain"]]
        ctx.close(); b.close()
        return cookies

cookies = login()
print("LOGIN OK, cookie count:", len(cookies))
jar = {c["name"]: c["value"] for c in cookies}

zwo = ("<workout_file><name>ZZ PROBE - delete me</name><description>probe</description>"
       "<sportType>bike</sportType><workout>"
       "<SteadyState Duration=\"600\" Power=\"0.6\"/></workout></workout_file>")

with httpx.Client(cookies=jar, timeout=30, follow_redirects=False) as c:
    # CREATE
    r = c.post("https://riders.rouvy.com/resources/workout-upload.data",
               files={"workout": ("probe.zwo", zwo, "application/xml")})
    print("CREATE", r.status_code, r.headers.get("content-type"))
    print("CREATE body head:", r.text[:400])
    # LIST (created collection) — confirm URL + parse for the new id
    for url in ["https://riders.rouvy.com/workouts/collections/created.data",
                "https://riders.rouvy.com/workouts.data"]:
        rl = c.get(url)
        print("LIST", url, rl.status_code, rl.text[:200])
    # NOTE: capture the created id from CREATE/LIST output, then exercise:
    #   GET  https://riders.rouvy.com/workouts/{id}.data
    #   DELETE — try candidates and record which returns 200:
    #     POST https://riders.rouvy.com/workouts/{id}.data           (form action, intent)
    #     POST https://riders.rouvy.com/resources/workout-delete.data (resource action)
    # Print the winning delete request line.
```

- [ ] **Step 2: Run the probe and observe**

Run: `python <scratchpad>/rouvy_probe.py`
Expected: `LOGIN OK` with a non-zero cookie count; `CREATE 200`. Record: the exact list URL that returns the user's created workouts, the exact delete URL that returns success, and whether any request needed a header beyond cookies (if create/delete return an HTML login page or 403 despite valid cookies, note the missing header — inspect a real browser request in devtools to identify it).

- [ ] **Step 3: Delete the probe workout(s) and confirm the account is clean**

Use the working delete request from Step 2 to remove any `ZZ PROBE` workout created. Verify none remain under the Created collection.

- [ ] **Step 4: Record findings in the spec and commit**

Fill the confirmed delete endpoint + required headers (if any) into the spec's "Confirmed API facts" section. If httpx could NOT replay create/delete even with headers, record that the CRUD client must instead drive those actions through Playwright (the spec's documented fallback) — Tasks 4–5 then change accordingly.

```bash
git add docs/superpowers/specs/2026-08-29-rouvy-workout-upload-design.md
git commit -m "docs(spec): record Rouvy delete endpoint + httpx-replay findings"
```

Do NOT commit the scratchpad probe script.

**Decision gate:** proceed to Task 2 only after login + create + delete are all confirmed working (via httpx, or via the Playwright fallback if httpx is blocked).

---

### Task 2: Database layer — columns, dataclass fields, hydration, update method

**Files:**
- Create: `migrations/0052_add_rouvy_fields.py`
- Modify: `src/db/models/dataclasses.py:34-36` (after `garmin_connected_at`)
- Modify: `src/db/models/user.py` (`User.from_row` ~:94-101; add `update_user_rouvy_credentials` after `update_user_garmin_token` ~:570)
- Test: `tests/unit/test_user_rouvy.py`

**Interfaces:**
- Produces: `User.rouvy_email: str | None`, `User.rouvy_password: str | None`, `User.rouvy_session: str | None`, `User.rouvy_connected_at: datetime | None` (all plaintext after hydration). `db.update_user_rouvy_credentials(user_id: str, email: str | None, password: str | None, session: str | None) -> bool` (all-None clears + disconnects).

- [ ] **Step 1: Write the migration**

```python
# migrations/0052_add_rouvy_fields.py
"""Add Rouvy integration fields to users table.

Stores the user's Rouvy email + password (Fernet-encrypted) and the serialized
session-cookie blob so the session can be auto-refreshed via headless login.
"""

from yoyo import step

__depends__ = {"0051_pin_conversations"}

steps = [
    step("ALTER TABLE users ADD COLUMN rouvy_email TEXT",
         "ALTER TABLE users DROP COLUMN rouvy_email"),
    step("ALTER TABLE users ADD COLUMN rouvy_password TEXT",
         "ALTER TABLE users DROP COLUMN rouvy_password"),
    step("ALTER TABLE users ADD COLUMN rouvy_session TEXT",
         "ALTER TABLE users DROP COLUMN rouvy_session"),
    step("ALTER TABLE users ADD COLUMN rouvy_connected_at TEXT",
         "ALTER TABLE users DROP COLUMN rouvy_connected_at"),
]
```

- [ ] **Step 2: Add dataclass fields**

In `src/db/models/dataclasses.py`, after `garmin_connected_at: datetime | None = None`:

```python
    rouvy_email: str | None = None
    rouvy_password: str | None = None
    rouvy_session: str | None = None
    rouvy_connected_at: datetime | None = None
```

- [ ] **Step 3: Hydrate + decrypt in `User.from_row`**

In `src/db/models/user.py`, alongside the `garmin_token` block, add (guard each column with `in row.keys()` for pre-migration rows):

```python
            rouvy_email=(
                decrypt_token(row["rouvy_email"]) if "rouvy_email" in row.keys() else None
            ),
            rouvy_password=(
                decrypt_token(row["rouvy_password"]) if "rouvy_password" in row.keys() else None
            ),
            rouvy_session=(
                decrypt_token(row["rouvy_session"]) if "rouvy_session" in row.keys() else None
            ),
            rouvy_connected_at=(
                datetime.fromisoformat(row["rouvy_connected_at"])
                if "rouvy_connected_at" in row.keys() and row["rouvy_connected_at"]
                else None
            ),
```

- [ ] **Step 4: Write the failing test**

```python
# tests/unit/test_user_rouvy.py
from src.db.models import db

def test_rouvy_credentials_round_trip(test_user):
    ok = db.update_user_rouvy_credentials(
        test_user.id, "r@example.com", "pw-secret", '[{"name":"s","value":"v"}]'
    )
    assert ok is True
    u = db.get_user_by_id(test_user.id)
    assert u.rouvy_email == "r@example.com"
    assert u.rouvy_password == "pw-secret"           # decrypted on hydration
    assert u.rouvy_session == '[{"name":"s","value":"v"}]'
    assert u.rouvy_connected_at is not None

def test_rouvy_disconnect_clears(test_user):
    db.update_user_rouvy_credentials(test_user.id, "r@e.com", "pw", "[]")
    db.update_user_rouvy_credentials(test_user.id, None, None, None)
    u = db.get_user_by_id(test_user.id)
    assert u.rouvy_email is None
    assert u.rouvy_session is None
    assert u.rouvy_connected_at is None

def test_rouvy_password_encrypted_at_rest(test_user, raw_db_row):
    db.update_user_rouvy_credentials(test_user.id, "r@e.com", "pw", "[]")
    row = raw_db_row("SELECT rouvy_password FROM users WHERE id = ?", test_user.id)
    # When a key is configured, the stored value must not be the plaintext.
    from src.utils.token_crypto import encryption_enabled
    if encryption_enabled():
        assert row["rouvy_password"] != "pw"
        assert row["rouvy_password"].startswith("enc:")
```

(Use the existing `test_user` fixture; if a raw-row helper isn't available, read the row via `db._pool.get_connection()` in the test as other DB tests do.)

- [ ] **Step 5: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_user_rouvy.py -v`
Expected: FAIL — `update_user_rouvy_credentials` not defined.

- [ ] **Step 6: Implement the update method**

In `src/db/models/user.py`, after `update_user_garmin_token`:

```python
    def update_user_rouvy_credentials(
        self,
        user_id: str,
        email: str | None,
        password: str | None,
        session: str | None,
    ) -> bool:
        """Store (or clear) a user's Rouvy credentials + session cookie blob.

        email/password/session are encrypted at rest. Passing all-None clears
        the credentials and disconnects the integration. `rouvy_connected_at`
        is set when a session is stored, cleared otherwise.
        """
        connected_at = datetime.now().isoformat() if session else None
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE users SET rouvy_email = ?, rouvy_password = ?, "
                "rouvy_session = ?, rouvy_connected_at = ? WHERE id = ?",
                (
                    encrypt_token(email),
                    encrypt_token(password),
                    encrypt_token(session),
                    connected_at,
                    user_id,
                ),
            )
            conn.commit()
            updated = cursor.rowcount > 0
        if updated:
            logger.info(
                "User Rouvy %s",
                "connected" if session else "disconnected",
                extra={"user_id": user_id},
            )
        return updated
```

Add a convenience method for refresh-only updates (session changes without touching creds):

```python
    def update_user_rouvy_session(self, user_id: str, session: str | None) -> bool:
        """Update only the stored Rouvy session cookie blob (used on refresh)."""
        connected_at = datetime.now().isoformat() if session else None
        with self._pool.get_connection() as conn:
            cursor = self._execute_with_timing(
                conn,
                "UPDATE users SET rouvy_session = ?, rouvy_connected_at = ? WHERE id = ?",
                (encrypt_token(session), connected_at, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0
```

- [ ] **Step 7: Run tests + migration, verify pass**

Run: `python -m pytest tests/unit/test_user_rouvy.py -v` → PASS
Run: `python -m pytest tests/unit/ -k user -q` → PASS (no regressions in user tests)
Migrations apply automatically on app start; confirm the file imports cleanly: `python -c "import migrations"` is not needed — yoyo discovers by path.

- [ ] **Step 8: Commit**

```bash
git add migrations/0052_add_rouvy_fields.py src/db/models/dataclasses.py src/db/models/user.py tests/unit/test_user_rouvy.py
git commit -m "feat(db): add encrypted Rouvy credential + session columns"
```

---

### Task 3: Config constants

**Files:**
- Modify: `src/config.py` (near the browser config ~:421-428 and integration timeouts ~:655)
- Test: covered by import in later tasks (no dedicated test — trivial constants)

**Interfaces:**
- Produces: `Config.ROUVY_ACCOUNT_URL`, `Config.ROUVY_RIDERS_URL`, `Config.ROUVY_LOGIN_TIMEOUT_MS`, `Config.ROUVY_HTTP_TIMEOUT`.

- [ ] **Step 1: Add constants**

```python
    # --- Rouvy integration ---
    ROUVY_ACCOUNT_URL: str = os.getenv("ROUVY_ACCOUNT_URL", "https://account.rouvy.com")
    ROUVY_RIDERS_URL: str = os.getenv("ROUVY_RIDERS_URL", "https://riders.rouvy.com")
    ROUVY_LOGIN_TIMEOUT_MS: int = int(os.getenv("ROUVY_LOGIN_TIMEOUT_MS", "45000"))
    ROUVY_HTTP_TIMEOUT: int = int(os.getenv("ROUVY_HTTP_TIMEOUT", "30"))
```

- [ ] **Step 2: Verify import**

Run: `python -c "from src.config import Config; print(Config.ROUVY_RIDERS_URL, Config.ROUVY_LOGIN_TIMEOUT_MS)"`
Expected: `https://riders.rouvy.com 45000`

- [ ] **Step 3: Commit**

```bash
git add src/config.py
git commit -m "feat(config): add Rouvy integration constants"
```

---

### Task 4: Auth module — headless Playwright login + cookie (de)serialization

**Files:**
- Create: `src/auth/rouvy_auth.py`
- Test: `tests/unit/test_rouvy_auth.py`

**Interfaces:**
- Consumes: `Config.ROUVY_ACCOUNT_URL`, `Config.ROUVY_LOGIN_TIMEOUT_MS`.
- Produces:
  - `class RouvyAuthError(Exception)`
  - `login(email: str, password: str) -> str` — returns a JSON string of Rouvy cookies (Playwright `context.cookies()` shape). Raises `RouvyAuthError`.
  - `cookies_to_jar(session_json: str) -> dict[str, str]` — name→value map for httpx.
  - Selectors/flow encoded here are confirmed in Task 1; adjust to match.

- [ ] **Step 1: Write failing tests (Playwright mocked)**

```python
# tests/unit/test_rouvy_auth.py
import json
from unittest.mock import patch
import pytest
from src.auth import rouvy_auth
from src.auth.rouvy_auth import RouvyAuthError

def test_cookies_to_jar():
    session = json.dumps([{"name": "a", "value": "1", "domain": ".rouvy.com"},
                          {"name": "b", "value": "2", "domain": ".rouvy.com"}])
    assert rouvy_auth.cookies_to_jar(session) == {"a": "1", "b": "2"}

def test_login_success(monkeypatch):
    fake_cookies = [{"name": "sess", "value": "xyz", "domain": ".rouvy.com"}]
    monkeypatch.setattr(rouvy_auth, "_login_sync", lambda e, p: json.dumps(fake_cookies))
    out = rouvy_auth.login("e@x.com", "pw")
    assert json.loads(out)[0]["name"] == "sess"

def test_login_invalid_credentials(monkeypatch):
    def boom(e, p):
        raise RuntimeError("email or password is wrong")
    monkeypatch.setattr(rouvy_auth, "_login_sync", boom)
    with pytest.raises(RouvyAuthError, match="email or password"):
        rouvy_auth.login("e@x.com", "pw")

def test_login_timeout(monkeypatch):
    import time
    def slow(e, p):
        time.sleep(2)
    monkeypatch.setattr(rouvy_auth, "_login_sync", slow)
    monkeypatch.setattr(rouvy_auth.Config, "ROUVY_LOGIN_TIMEOUT_MS", 1)
    with pytest.raises(RouvyAuthError, match="timed out"):
        rouvy_auth.login("e@x.com", "pw")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_rouvy_auth.py -v`
Expected: FAIL — module/functions not defined.

- [ ] **Step 3: Implement `src/auth/rouvy_auth.py`**

```python
"""Rouvy authentication via headless Playwright login.

Rouvy has no public API. This drives the account.rouvy.com email->password
sign-in flow headlessly and extracts the resulting .rouvy.com session cookies,
which then authenticate direct httpx calls to riders.rouvy.com.

Unlike Garmin, the password IS stored (Fernet-encrypted, by the caller) so the
short-lived session can be auto-refreshed. The login page has an invisible
reCAPTCHA; headless login usually passes but may be scored low and blocked, in
which case the user must reconnect.

Playwright's sync API uses greenlets and cannot cross threads, so each login
runs its whole lifecycle on a dedicated thread.
"""

from __future__ import annotations

import json
import threading
from typing import Any, NoReturn

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


class RouvyAuthError(Exception):
    """Rouvy authentication failed (bad credentials, captcha, timeout, ...)."""


def cookies_to_jar(session_json: str) -> dict[str, str]:
    """Convert a stored cookie blob into an httpx-compatible name->value map."""
    try:
        cookies = json.loads(session_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return {c["name"]: c["value"] for c in cookies if "name" in c and "value" in c}


def login(email: str, password: str) -> str:
    """Headless Rouvy login. Returns a JSON string of .rouvy.com cookies.

    Raises RouvyAuthError (with a user-friendly message) on any failure.
    """
    result: dict[str, Any] = {}

    def _run() -> None:
        try:
            result["cookies"] = _login_sync(email, password)
        except Exception as e:  # noqa: BLE001 - classified in _raise_typed_error
            result["error"] = e

    t = threading.Thread(target=_run, name="rouvy-login", daemon=True)
    t.start()
    t.join(timeout=Config.ROUVY_LOGIN_TIMEOUT_MS / 1000 + 5)
    if t.is_alive():
        raise RouvyAuthError("Rouvy login timed out. Please try again.")
    if "error" in result:
        _raise_typed_error(result["error"])
    return result["cookies"]


def _login_sync(email: str, password: str) -> str:
    """Blocking headless login; runs on the dedicated rouvy-login thread.

    Selectors/flow confirmed in Task 1 — adjust to match the live page.
    """
    from playwright.sync_api import sync_playwright

    timeout = Config.ROUVY_LOGIN_TIMEOUT_MS
    sign_in = f"{Config.ROUVY_ACCOUNT_URL}/sign-in?riders=true&redirectTo=%2Ffeed"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-gpu", "--disable-dev-shm-usage"])
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(timeout)
        try:
            page.goto(sign_in)
            # Best-effort: decline non-essential cookies so the banner can't
            # overlay the form (privacy-preserving default).
            try:
                page.get_by_role("button", name="Use necessary cookies only").click(timeout=5000)
            except Exception:
                pass
            page.fill("input[type=email], input[name=email]", email)
            page.get_by_role("button", name="Continue").click()
            page.fill("input[type=password]", password)
            page.get_by_role("button", name="Sign in").click()
            page.wait_for_url("**/feed", timeout=timeout)
            cookies = context.cookies()
        finally:
            context.close()
            browser.close()

    rouvy_cookies = [c for c in cookies if "rouvy.com" in c.get("domain", "")]
    if not rouvy_cookies:
        raise RouvyAuthError("Login did not produce a session. Please try again.")
    return json.dumps(rouvy_cookies)


def _raise_typed_error(e: Exception) -> NoReturn:
    """Classify a login exception into a user-friendly RouvyAuthError."""
    if isinstance(e, RouvyAuthError):
        raise e
    s = str(e).lower()
    if "email or password" in s or "wrong" in s or "invalid" in s or "credential" in s:
        raise RouvyAuthError("Rouvy email or password is wrong.") from e
    if "captcha" in s or "recaptcha" in s or "blocked" in s or "forbidden" in s:
        raise RouvyAuthError(
            "Rouvy blocked the automated login (captcha). Please reconnect in Settings."
        ) from e
    if "timeout" in s or "timed out" in s:
        raise RouvyAuthError("Rouvy login timed out. Please try again.") from e
    logger.error("Rouvy login failed", extra={"error": str(e)}, exc_info=True)
    raise RouvyAuthError(f"Rouvy login failed: {e}") from e
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/unit/test_rouvy_auth.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/auth/rouvy_auth.py tests/unit/test_rouvy_auth.py
git commit -m "feat(auth): headless Playwright Rouvy login + cookie serialization"
```

---

### Task 5: CRUD client — httpx calls with expired→refresh→retry

**Files:**
- Create: `src/agent/tools/rouvy.py` (client half — the `@tool` is added in Task 6)
- Test: `tests/unit/test_rouvy_client.py`

**Interfaces:**
- Consumes: `rouvy_auth.login`, `rouvy_auth.cookies_to_jar`, `db.update_user_rouvy_session`, `User.rouvy_session/rouvy_email/rouvy_password`, `Config.ROUVY_RIDERS_URL/ROUVY_HTTP_TIMEOUT`, the delete endpoint from Task 1.
- Produces (used by Task 6): `RouvyNotConnected(Exception)`; `rouvy_list(user) -> list[dict]`; `rouvy_get(user, workout_id) -> dict`; `rouvy_create(user, content, name, description=None) -> dict` (`{"id", "workout_url"}`); `rouvy_delete(user, workout_id) -> dict`; `rouvy_update(user, workout_id, content, name, description=None) -> dict`.

- [ ] **Step 1: Write failing tests (httpx + auth mocked)**

```python
# tests/unit/test_rouvy_client.py
import json
from unittest.mock import MagicMock, patch
import pytest
from src.agent.tools import rouvy as rc

class FakeUser:
    id = "u1"
    rouvy_email = "e@x.com"
    rouvy_password = "pw"
    rouvy_session = json.dumps([{"name": "s", "value": "v", "domain": ".rouvy.com"}])

def _resp(status=200, text='{"ok":true}', ctype="text/x-script"):
    r = MagicMock(); r.status_code = status; r.text = text
    r.headers = {"content-type": ctype}
    return r

def test_not_connected_raises():
    u = FakeUser(); u.rouvy_session = None
    with pytest.raises(rc.RouvyNotConnected):
        rc.rouvy_list(u)

@patch("src.agent.tools.rouvy._client_request")
def test_create_posts_multipart(mock_req):
    mock_req.return_value = _resp(text='[{"_1":2},"data",{"_3":-5},"error","workoutId",123]')
    out = rc.rouvy_create(FakeUser(), "<workout_file/>", "My Ride", "desc")
    method, url, kwargs, jar = mock_req.call_args[0]  # _client_request(method, url, kwargs, jar)
    assert method == "POST"
    assert url.endswith("/resources/workout-upload.data")
    assert "file" in kwargs["files"]  # field name is `file`, not `workout`
    assert out["workout_url"].endswith("/workouts/123")

@patch("src.agent.tools.rouvy._client_request")
def test_expired_triggers_refresh_and_retry(mock_req):
    # First call looks expired (login HTML), second (after refresh) succeeds.
    mock_req.side_effect = [_resp(status=200, text="<!doctype html><title>Sign In</title>", ctype="text/html"),
                            _resp(text='"error","workoutId",9')]
    with patch("src.agent.tools.rouvy.rouvy_auth.login", return_value="[]") as login, \
         patch("src.agent.tools.rouvy.db.update_user_rouvy_session") as save:
        out = rc.rouvy_create(FakeUser(), "<x/>", "n")
    assert login.called and save.called
    assert out["id"] == 9

@patch("src.agent.tools.rouvy._client_request")
def test_refresh_failure_raises_reconnect(mock_req):
    mock_req.return_value = _resp(status=401, text="unauthorized")
    with patch("src.agent.tools.rouvy.rouvy_auth.login",
               side_effect=rc.rouvy_auth.RouvyAuthError("captcha")):
        with pytest.raises(rc.RouvySessionExpired):
            rc.rouvy_create(FakeUser(), "<x/>", "n")

@patch("src.agent.tools.rouvy.rouvy_delete")
@patch("src.agent.tools.rouvy.rouvy_create")
def test_update_is_delete_then_create(mock_create, mock_delete):
    mock_create.return_value = {"id": 5, "workout_url": ".../workouts/5"}
    out = rc.rouvy_update(FakeUser(), 4, "<x/>", "n")
    mock_delete.assert_called_once()
    mock_create.assert_called_once()
    assert out["id"] == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_rouvy_client.py -v`
Expected: FAIL — module/functions not defined.

- [ ] **Step 3: Implement the client half of `src/agent/tools/rouvy.py`**

Replace the delete URL/method with the Task 1 finding. `_looks_expired` heuristics: 401/403, or an HTML login page returned instead of `.data` JSON.

```python
"""Rouvy workout CRUD tool.

Uses the stored session cookie (see src/auth/rouvy_auth.py) to call the
riders.rouvy.com React-Router .data endpoints via httpx. On an expired session
it re-logs-in headlessly with the stored credentials, re-persists the cookie,
and retries once. Playwright is only used for (re)login, never for CRUD.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from src.auth import rouvy_auth
from src.config import Config
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)


class RouvyNotConnected(Exception):
    """User has not connected Rouvy."""


class RouvySessionExpired(Exception):
    """Session expired and automated refresh failed — user must reconnect."""


def _base() -> str:
    return Config.ROUVY_RIDERS_URL


def _client_request(method: str, url: str, kwargs: dict[str, Any], jar: dict[str, str]) -> httpx.Response:
    """Single httpx request with the given cookie jar. Isolated for test seams."""
    with httpx.Client(cookies=jar, timeout=Config.ROUVY_HTTP_TIMEOUT, follow_redirects=False) as c:
        return c.request(method, url, **kwargs)


def _looks_expired(resp: httpx.Response) -> bool:
    if resp.status_code in (401, 403):
        return True
    ctype = resp.headers.get("content-type", "")
    if resp.status_code in (302, 307) and "sign-in" in resp.headers.get("location", ""):
        return True
    # A .data endpoint returning an HTML login page means the cookie is dead.
    if "text/html" in ctype and "sign in" in resp.text[:500].lower():
        return True
    return False


def _authed_request(user: User, method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Issue a request, refreshing the session once on expiry."""
    if not user.rouvy_session:
        raise RouvyNotConnected()
    jar = rouvy_auth.cookies_to_jar(user.rouvy_session)
    resp = _client_request(method, url, kwargs, jar)
    if not _looks_expired(resp):
        return resp
    # Refresh: re-login with stored creds, persist, retry once.
    if not (user.rouvy_email and user.rouvy_password):
        raise RouvySessionExpired()
    try:
        new_session = rouvy_auth.login(user.rouvy_email, user.rouvy_password)
    except rouvy_auth.RouvyAuthError as e:
        raise RouvySessionExpired() from e
    db.update_user_rouvy_session(user.id, new_session)
    user.rouvy_session = new_session
    jar = rouvy_auth.cookies_to_jar(new_session)
    resp = _client_request(method, url, kwargs, jar)
    if _looks_expired(resp):
        raise RouvySessionExpired()
    return resp


def _parse_created_id(resp: httpx.Response) -> int:
    """Extract the new workout id from a create response (single-fetch payload)."""
    # React-Router single-fetch returns a turbo-stream-ish JSON; the id may be
    # nested. Parse defensively; Task 1 confirms the exact shape.
    # Turbo-stream (text/x-script) flat array; success looks like
    #   [...,"error",<null-ref>,"workoutId",4183941]
    import re

    m = re.search(r'"workoutId"\s*,\s*(\d+)', resp.text)
    if not m:
        raise ValueError("could not parse created workout id from Rouvy response")
    return int(m.group(1))


def rouvy_create(user: User, content: str, name: str, description: str | None = None) -> dict[str, Any]:
    """Upload a workout (ZWO/ERG/MRC text) → returns {id, workout_url}.

    Task 1 confirmed the multipart field name is `file` (not `workout`).
    """
    filename = f"{name[:60] or 'workout'}.zwo"
    resp = _authed_request(
        user, "POST", f"{_base()}/resources/workout-upload.data",
        files={"file": (filename, content, "application/xml")},
    )
    resp.raise_for_status()
    wid = _parse_created_id(resp)
    return {"id": wid, "workout_url": f"{_base()}/workouts/{wid}"}


def rouvy_delete(user: User, workout_id: int) -> dict[str, Any]:
    """Delete a workout: POST /workouts/{id}.data with urlencoded body id=<id>."""
    resp = _authed_request(user, "POST", f"{_base()}/workouts/{workout_id}.data",
                           data={"id": str(workout_id)})
    resp.raise_for_status()
    return {"deleted": True, "id": workout_id}


def rouvy_get(user: User, workout_id: int) -> dict[str, Any]:
    resp = _authed_request(user, "GET", f"{_base()}/workouts/{workout_id}.data")
    resp.raise_for_status()
    return {"id": workout_id, "raw": resp.text[:4000]}


def rouvy_list(user: User) -> list[dict[str, Any]]:
    """List the user's created workouts (Created collection). Shape per Task 1."""
    resp = _authed_request(user, "GET", f"{_base()}/workouts/collections/created.data")
    resp.raise_for_status()
    return _parse_workout_list(resp)


def _parse_workout_list(resp: httpx.Response) -> list[dict[str, Any]]:
    """Extract [{id, name}] from the created-collection turbo-stream payload.

    The payload interleaves values as a flat array; created workouts appear as
    a stringified id immediately followed by the name string, e.g.
    `...,"4183941","ZZ PROBE4 - delete me",...`. Match that pair. Task 1 captured
    this shape; add a fixture parse test from a real captured payload in Step 1.
    """
    import re

    out: list[dict[str, Any]] = []
    for wid, wname in re.findall(r'"(\d{5,})"\s*,\s*"([^"]+)"', resp.text):
        out.append({"id": int(wid), "name": wname})
    # De-dup by id, preserving order.
    seen: set[int] = set()
    return [w for w in out if not (w["id"] in seen or seen.add(w["id"]))]


def rouvy_update(user: User, workout_id: int, content: str, name: str,
                 description: str | None = None) -> dict[str, Any]:
    """Rouvy has no ZWO edit endpoint, so update = delete + create.

    The workout id/URL changes as a result — callers must surface the new URL.
    """
    rouvy_delete(user, workout_id)
    return rouvy_create(user, content, name, description)
```

Note: the `_parse_created_id` / `_parse_workout_list` walkers parse defensively; once Task 1 confirms the exact single-fetch payload shape, tighten them to read the confirmed path directly (and add a parse test with a real captured payload fixture).

- [ ] **Step 4: Run tests, verify pass**

Run: `python -m pytest tests/unit/test_rouvy_client.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent/tools/rouvy.py tests/unit/test_rouvy_client.py
git commit -m "feat(rouvy): httpx CRUD client with expired-session refresh"
```

---

### Task 6: The `rouvy_workout` tool + registration + gating

**Files:**
- Modify: `src/agent/tools/rouvy.py` (add the `@tool` + `is_rouvy_available`)
- Modify: `src/agent/tools/__init__.py` (import, `get_available_tools`, `_TOOL_MAP`, `__all__`; keep OUT of `_SPORTS_EXCLUDED_TOOLS`)
- Test: `tests/unit/test_rouvy_tool.py`, extend `tests/unit/test_tools.py::TestGetToolsForRequest`

**Interfaces:**
- Consumes: the Task 5 client functions; `is_browser_available` from `src.agent.tools.browser`.
- Produces: `rouvy_workout` LangChain tool; `is_rouvy_available() -> bool`.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_rouvy_tool.py
import json
from unittest.mock import patch
from src.agent.tools.rouvy import rouvy_workout, is_rouvy_available
from src.agent.tools import context as tool_context  # if user is resolved via contextvar

@patch("src.agent.tools.rouvy._current_user", create=True)
def test_not_connected_message(_):
    # With no connected user, the tool returns a friendly not-connected error.
    with patch("src.agent.tools.rouvy._resolve_user", return_value=_disconnected_user()):
        out = json.loads(rouvy_workout.invoke({"action": "list"}))
    assert out["success"] is False
    assert "connect" in out["error"].lower()

@patch("src.agent.tools.rouvy.rouvy_create", return_value={"id": 7, "workout_url": "u/7"})
def test_create_dispatch(mock_create):
    with patch("src.agent.tools.rouvy._resolve_user", return_value=_connected_user()):
        out = json.loads(rouvy_workout.invoke(
            {"action": "create", "content": "<x/>", "name": "Ride"}))
    assert out["success"] is True and out["workout_url"] == "u/7"
    mock_create.assert_called_once()

def test_unknown_action():
    with patch("src.agent.tools.rouvy._resolve_user", return_value=_connected_user()):
        out = json.loads(rouvy_workout.invoke({"action": "frobnicate"}))
    assert out["success"] is False
```

(Provide `_connected_user`/`_disconnected_user` helpers building a `User` with/without `rouvy_session`. Use the same user-resolution seam the other tools use — check how `garmin_connect` obtains the current user, e.g. a `get_conversation_context`/contextvar; mirror it and name the seam `_resolve_user`.)

Also add to `tests/unit/test_tools.py::TestGetToolsForRequest.test_sports_mode_keeps_create_file`-style assertions:

```python
    def test_sports_mode_keeps_rouvy_workout(self):
        names = {t.name for t in get_tools_for_request(is_sports=True)}
        # Only present when browser (Playwright) is available; assert it is not
        # excluded by the sports filter set.
        from src.agent.tools import _SPORTS_EXCLUDED_TOOLS
        assert "rouvy_workout" not in _SPORTS_EXCLUDED_TOOLS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/test_rouvy_tool.py -v` → FAIL (tool not defined).

- [ ] **Step 3: Add the tool + availability to `src/agent/tools/rouvy.py`**

```python
from langchain_core.tools import tool

from src.agent.tools.browser import is_browser_available


def is_rouvy_available() -> bool:
    """Rouvy needs Chromium for (re)login."""
    return Config.BROWSER_ENABLED and is_browser_available()


def _resolve_user() -> User | None:
    """Resolve the current request's user (same seam garmin.py uses)."""
    from src.agent.tools.context import get_conversation_context

    _, user_id = get_conversation_context()
    if not user_id:
        return None
    return db.get_user_by_id(user_id)


@tool
def rouvy_workout(
    action: str,
    workout_id: int | None = None,
    content: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> str:
    """Manage the user's Rouvy cycling workouts (Rouvy = indoor cycling app).

    Actions:
    - "list": list the user's created Rouvy workouts.
    - "get": fetch one workout's details (needs workout_id).
    - "create": upload a workout you authored (needs content = full ZWO XML, and
      name; optional description). Returns the Rouvy workout URL.
    - "update": REPLACE a workout (needs workout_id, content, name). Implemented
      as delete + create, so the workout's id and URL CHANGE — always give the
      user the new URL from the result.
    - "delete": remove a workout (needs workout_id).

    The user must have connected Rouvy in Settings first.
    """
    user = _resolve_user()
    if user is None or not user.rouvy_session:
        return json.dumps({
            "success": False,
            "error": "Rouvy is not connected. Ask the user to connect Rouvy in Settings first.",
            "retriable": False,
        })
    try:
        if action == "list":
            return json.dumps({"success": True, "workouts": rouvy_list(user)})
        if action == "get":
            return json.dumps({"success": True, "workout": rouvy_get(user, int(workout_id))})
        if action == "create":
            if not content or not name:
                return json.dumps({"success": False, "error": "create needs content and name."})
            return json.dumps({"success": True, **rouvy_create(user, content, name, description)})
        if action == "update":
            if not workout_id or not content or not name:
                return json.dumps({"success": False, "error": "update needs workout_id, content, name."})
            res = rouvy_update(user, int(workout_id), content, name, description)
            return json.dumps({"success": True, "note": "workout id/URL changed", **res})
        if action == "delete":
            return json.dumps({"success": True, **rouvy_delete(user, int(workout_id))})
        return json.dumps({"success": False, "error": f"Unknown action: {action}"})
    except RouvyNotConnected:
        return json.dumps({"success": False, "error": "Rouvy is not connected.", "retriable": False})
    except RouvySessionExpired:
        return json.dumps({
            "success": False,
            "error": "Rouvy session expired and automatic refresh failed. Please reconnect in Settings.",
            "retriable": False,
        })
    except Exception as e:  # noqa: BLE001
        logger.error("rouvy_workout failed", extra={"action": action, "error": str(e)})
        return json.dumps({"success": False, "error": f"Rouvy request failed: {e}", "retriable": True})
```

Implement `_resolve_user` by copying the exact user-resolution mechanism `garmin_connect` uses (read `src/agent/tools/garmin.py` — likely `get_conversation_context()` or a contextvar). Do not invent a new mechanism.

- [ ] **Step 4: Register in `src/agent/tools/__init__.py`**

```python
from src.agent.tools.rouvy import is_rouvy_available, rouvy_workout
```
In `get_available_tools()`, after the Garmin block:
```python
    if is_rouvy_available():
        tools.append(rouvy_workout)
        logger.debug("rouvy_workout tool added to available tools")
```
Add `"rouvy_workout": rouvy_workout` to `_TOOL_MAP`, add `"rouvy_workout"` to `__all__`, and — critically — do NOT add it to `_SPORTS_EXCLUDED_TOOLS` or `_LANGUAGE_EXCLUDED_TOOLS`. In the autonomous-agent `get_tools_for_agent` None-branch and permission list, add availability handling mirroring `garmin` (append when `is_rouvy_available()`; skip in the permission loop when unavailable).

- [ ] **Step 5: Run tests, verify pass**

Run: `python -m pytest tests/unit/test_rouvy_tool.py tests/unit/test_tools.py -q` → PASS

- [ ] **Step 6: Commit**

```bash
git add src/agent/tools/rouvy.py src/agent/tools/__init__.py tests/unit/test_rouvy_tool.py tests/unit/test_tools.py
git commit -m "feat(rouvy): rouvy_workout tool + registration (sports-enabled)"
```

---

### Task 7: Connect API — routes + schemas + blueprint registration

**Files:**
- Modify: `src/api/schemas.py` (add Rouvy request/response schemas near the Garmin ones ~:96-114, 413-428)
- Create: `src/api/routes/rouvy.py`
- Modify: `src/api/routes/__init__.py` (import `rouvy` ~:37; `app.register_blueprint(rouvy.auth)` ~:69; docstring count ~:9)
- Test: `tests/integration/test_routes_rouvy.py`

**Interfaces:**
- Consumes: `rouvy_auth.login`, `db.update_user_rouvy_credentials`.
- Produces: `POST /auth/rouvy/connect {email,password} -> {connected}`; `POST /auth/rouvy/disconnect -> {status}`; `GET /auth/rouvy/status -> {connected, connected_at, needs_reconnect}`.

- [ ] **Step 1: Add schemas**

```python
class RouvyConnectRequest(BaseModel):
    """Schema for POST /auth/rouvy/connect."""
    email: str = Field(..., min_length=1, description="Rouvy account email")
    password: str = Field(..., min_length=1, description="Rouvy account password (encrypted at rest)")

class RouvyConnectResponse(BaseModel):
    connected: bool = Field(..., description="Whether connection succeeded")

class RouvyStatusResponse(BaseModel):
    connected: bool = Field(..., description="Whether Rouvy is connected")
    connected_at: str | None = Field(None, description="ISO timestamp when connected")
    needs_reconnect: bool = Field(False, description="True if the stored session looks unusable")
```

- [ ] **Step 2: Write failing route tests (login mocked)**

```python
# tests/integration/test_routes_rouvy.py
from unittest.mock import patch

def test_connect_stores_credentials(client, auth_headers, test_user):
    with patch("src.api.routes.rouvy.login", return_value="[]") as login:
        r = client.post("/auth/rouvy/connect",
                        json={"email": "e@x.com", "password": "pw"}, headers=auth_headers)
    assert r.status_code == 200 and r.json["connected"] is True
    assert login.called
    from src.db.models import db
    u = db.get_user_by_id(test_user.id)
    assert u.rouvy_email == "e@x.com" and u.rouvy_session == "[]"

def test_connect_bad_credentials_returns_400(client, auth_headers):
    from src.auth.rouvy_auth import RouvyAuthError
    with patch("src.api.routes.rouvy.login", side_effect=RouvyAuthError("wrong")):
        r = client.post("/auth/rouvy/connect",
                        json={"email": "e@x.com", "password": "bad"}, headers=auth_headers)
    assert r.status_code == 400

def test_disconnect_clears(client, auth_headers, test_user):
    from src.db.models import db
    db.update_user_rouvy_credentials(test_user.id, "e@x.com", "pw", "[]")
    r = client.post("/auth/rouvy/disconnect", headers=auth_headers)
    assert r.status_code == 200
    assert db.get_user_by_id(test_user.id).rouvy_session is None

def test_status_reports_connected(client, auth_headers, test_user):
    from src.db.models import db
    db.update_user_rouvy_credentials(test_user.id, "e@x.com", "pw", "[]")
    r = client.get("/auth/rouvy/status", headers=auth_headers)
    assert r.status_code == 200 and r.json["connected"] is True
```

(Use the same client/auth fixtures as `tests/integration/test_routes_*`.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/integration/test_routes_rouvy.py -v` → FAIL (route not registered).

- [ ] **Step 4: Implement `src/api/routes/rouvy.py`**

```python
"""Rouvy integration routes: connect (email/password), status, disconnect.

Rouvy has no OAuth/API; connect drives a headless login and stores the session
cookie plus the credentials (encrypted) so the session can be auto-refreshed.
No MFA (Rouvy's flow has none).
"""

from typing import Any

from apiflask import APIBlueprint

from src.api.errors import raise_not_found_error, raise_validation_error
from src.api.schemas import (
    RouvyConnectRequest,
    RouvyConnectResponse,
    RouvyStatusResponse,
    StatusResponse,
)
from src.api.validation import validate_request
from src.auth.jwt_auth import require_auth
from src.auth.rouvy_auth import RouvyAuthError, cookies_to_jar, login
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)

auth = APIBlueprint("rouvy", __name__, url_prefix="/auth", tag="Rouvy")


@auth.route("/rouvy/connect", methods=["POST"])
@auth.output(RouvyConnectResponse)
@auth.doc(responses=[400, 401])
@require_auth
@validate_request(RouvyConnectRequest)
def connect_rouvy(user: User, data: RouvyConnectRequest) -> dict[str, Any]:
    """Connect Rouvy: headless login, then store session + encrypted credentials."""
    logger.info("Rouvy connection attempt", extra={"user_id": user.id})
    try:
        session = login(data.email, data.password)
    except RouvyAuthError as e:
        logger.warning("Rouvy connection failed", extra={"user_id": user.id, "error": str(e)})
        raise_validation_error(str(e))
    db.update_user_rouvy_credentials(user.id, data.email, data.password, session)
    logger.info("Rouvy connected", extra={"user_id": user.id})
    return {"connected": True}


@auth.route("/rouvy/disconnect", methods=["POST"])
@auth.output(StatusResponse)
@auth.doc(responses=[401])
@require_auth
def disconnect_rouvy(user: User) -> dict[str, str]:
    """Disconnect Rouvy by clearing stored credentials + session."""
    db.update_user_rouvy_credentials(user.id, None, None, None)
    logger.info("Rouvy disconnected", extra={"user_id": user.id})
    return {"status": "disconnected"}


@auth.route("/rouvy/status", methods=["GET"])
@auth.output(RouvyStatusResponse)
@auth.doc(responses=[401])
@require_auth
def get_rouvy_status(user: User) -> dict[str, Any]:
    """Report Rouvy connection status."""
    current = db.get_user_by_id(user.id)
    if not current:
        raise_not_found_error("User")
    connected = bool(current.rouvy_session)
    needs_reconnect = connected and not cookies_to_jar(current.rouvy_session or "")
    connected_at = (
        current.rouvy_connected_at.isoformat()
        if connected and current.rouvy_connected_at else None
    )
    return {"connected": connected, "connected_at": connected_at, "needs_reconnect": needs_reconnect}
```

- [ ] **Step 5: Register the blueprint**

In `src/api/routes/__init__.py`: add `rouvy` to the `from src.api.routes import (...)` block and `app.register_blueprint(rouvy.auth)` next to `garmin.auth`.

- [ ] **Step 6: Run tests, verify pass**

Run: `python -m pytest tests/integration/test_routes_rouvy.py -v` → PASS
Run: `make openapi` (schemas changed → regenerate the OpenAPI spec) then `make types` (regenerate TS types).

- [ ] **Step 7: Commit**

```bash
git add src/api/schemas.py src/api/routes/rouvy.py src/api/routes/__init__.py tests/integration/test_routes_rouvy.py static/openapi.json web/src/types/generated-api.ts
git commit -m "feat(api): Rouvy connect/status/disconnect routes"
```

---

### Task 8: Frontend — Settings "Rouvy" section

**Files:**
- Modify: `web/src/api/client.ts` (add a `rouvy` client group mirroring the `garmin` group ~:822-853)
- Modify: `web/src/components/SettingsPopup.ts` (add `renderRouvySection()` mirroring `renderGarminSection()` ~:359; wire a `data-section="rouvy"` block, email/password inputs, connect/disconnect handlers)
- Test: mirror existing Garmin frontend tests if present under `web/tests/`; otherwise a light unit test of the client group.

**Interfaces:**
- Consumes: `POST /auth/rouvy/connect`, `GET /auth/rouvy/status`, `POST /auth/rouvy/disconnect`.
- Produces: a Settings UI section to connect/disconnect Rouvy.

- [ ] **Step 1: Add the client group in `web/src/api/client.ts`**

Mirror the `garmin` object (same file, ~:822-853). Rouvy has no MFA, so only `connect`, `getStatus`, `disconnect`:

```ts
  rouvy: {
    connect: (email: string, password: string) =>
      request<{ connected: boolean }>("/auth/rouvy/connect", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }),
    getStatus: () =>
      request<{ connected: boolean; connected_at: string | null; needs_reconnect: boolean }>(
        "/auth/rouvy/status",
      ),
    disconnect: () =>
      request<{ status: string }>("/auth/rouvy/disconnect", { method: "POST" }),
  },
```
(Match the exact `request` helper signature already used by the `garmin` group in this file.)

- [ ] **Step 2: Add `renderRouvySection()` in `SettingsPopup.ts`**

Read `renderGarminSection()` (~:359) and its handler `handleGarminConnect()` (~:988) and clone them as `renderRouvySection()` / `handleRouvyConnect()`, dropping the MFA sub-form. Use CSS classes prefixed `settings-rouvy-email` / `settings-rouvy-password` (component-prefixed to avoid collisions). Add a `data-section="rouvy"` entry to the same sections list the Garmin section is registered in. Copy tone: "Connect your Rouvy account so the coach can upload workouts directly." On connect, call `apiClient.rouvy.connect(...)`, show connected/disconnected state from `getStatus()`.

- [ ] **Step 3: Build + verify the section renders**

Run: `make build` (E2E serves the built bundle). Load Settings and confirm the Rouvy section renders on desktop and mobile (768px breakpoint), inputs accept text, and Connect calls the endpoint (network tab).

- [ ] **Step 4: Run frontend checks**

Run: `cd web && npm run typecheck && npm run lint` → PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/api/client.ts web/src/components/SettingsPopup.ts
git commit -m "feat(web): Rouvy connect/disconnect in Settings"
```

---

### Task 9: Docs, agent prompt, and manual end-to-end verification

**Files:**
- Modify: `.env.example` (document the optional `ROUVY_*` overrides)
- Create: `docs/features/rouvy.md` (feature doc) and link it from `docs/README.md`
- Modify: `src/agent/prompts.py` (add a short "Rouvy workouts" note to the sports trainer prompt so the agent knows the tool exists and that `update` changes the URL)
- Modify: `docs/features/agents.md` (add `rouvy_workout` to the tool table)

**Interfaces:** none (docs + prompt copy).

- [ ] **Step 1: Document env + feature**

Add to `.env.example` under a Rouvy heading: the four `ROUVY_*` overrides with defaults and a one-line note that no secret is required (reuses `TOKEN_ENCRYPTION_KEY`). Write `docs/features/rouvy.md` covering: what it does, the auth model (headless Playwright login, stored encrypted password, cookie auto-refresh, manual-reconnect fallback on captcha), the CRUD actions, and the `update = delete+create` caveat.

- [ ] **Step 2: Add the sports-prompt note**

In the sports trainer prompt, add a short bullet: the `rouvy_workout` tool can list/get/create/update/delete the user's Rouvy workouts; `create` takes the ZWO you authored; `update` replaces a workout and CHANGES its URL, so always give the user the new link; if Rouvy isn't connected, tell the user to connect it in Settings.

- [ ] **Step 3: Add tool-table row in `docs/features/agents.md`**

`| \`rouvy_workout\` | CRUD over the user's Rouvy cycling workouts (upload ZWO, list, delete; update = delete+create) | Requires browser + user Rouvy connect |`

- [ ] **Step 4: Manual end-to-end verification (local, real account)**

Using the local `.tmp.rouvy.txt` creds while they exist: connect Rouvy in Settings, then drive the sports agent to `create` a workout, `list` it, `get` it, `update` it (confirm the URL changes), and `delete` it. Confirm the Created collection is clean afterward. This is the real proof the shipped code path works end-to-end (the recon proved the endpoints; this proves the integration).

- [ ] **Step 5: Commit**

```bash
git add .env.example docs/features/rouvy.md docs/README.md docs/features/agents.md src/agent/prompts.py
git commit -m "docs(rouvy): feature doc, env, agent prompt, tool table"
```

---

## Pre-merge

- [ ] `make lint` → exit 0 (ruff, mypy, eslint, tsc).
- [ ] `make test` → all backend pass.
- [ ] Manual E2E (Task 9 Step 4) done.
- [ ] Confirm `.tmp.rouvy.txt` is NOT staged in any commit (`git log -p | grep -i rouvy_password` finds nothing).
