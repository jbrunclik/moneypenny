# Inline Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The agent creates and revises sandboxed HTML/JS artifacts rendered inline below its reply, styled by a light/dark design system, with a small bridge to send messages and keep per-artifact state.

**Architecture:** Three tools (`create_artifact`, `update_artifact`, `read_artifact`) write versions into new `artifacts` / `artifact_versions` tables; the save path copies `{id, version, title}` from the turn's tool results into `messages.artifacts`, and the stream emits an `artifact` event. The client embeds one static, sandboxed, opaque-origin frame page (`/artifact-frame`, its own CSP, no network) per artifact and posts it the HTML, theme and state; a `postMessage` bridge (`mp.send`, `mp.state`, height, errors, links) connects it back.

**Tech Stack:** Python 3.14, Flask/APIFlask + Pydantic, LangChain tools, SQLite + yoyo (triggers), TypeScript + Vite (second entry) + Zustand, Vitest, Playwright.

**Spec:** [docs/superpowers/specs/2026-10-11-inline-artifacts-design.md](../specs/2026-10-11-inline-artifacts-design.md)

## Global Constraints

- Work on branch `feat/inline-artifacts`; merge to main only with `make lint` and `make test-all` green in-session.
- Everything behind `ARTIFACTS_ENABLED` (default `true` in `src/config.py` and `.env.example`; tests set it explicitly where it matters).
- Frame CSP (verbatim): `sandbox allow-scripts; default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'` (dev mode adds `http://localhost:5173` to script/style-src and `ws://localhost:5173` to connect-src).
- The iframe attribute is exactly `sandbox="allow-scripts"` - never `allow-same-origin`, `allow-popups`, `allow-top-navigation` or `allow-forms`.
- Limits: `ARTIFACT_MAX_BYTES` 200 000, `ARTIFACT_STATE_MAX_BYTES` 50 000, `ARTIFACT_MAX_PER_CONVERSATION` 30 (config.py); `ARTIFACT_MAX_HEIGHT_VH` 80, `ARTIFACT_READY_TIMEOUT_MS` 5000, `ARTIFACT_STATE_SAVE_DEBOUNCE_MS` 400 (web config.ts).
- Nothing about an artifact's size is stored server-side; layouts are fluid; container queries stack below 480px of frame width.
- Tools bound in regular chats (anonymous included), not in sports/language programs, never for autonomous agents (`get_tools_for_agent`, the `agent_tool_permissions` branch).
- `update_artifact` edits: each `find` must match exactly once.
- UI strings in English. Component-prefixed CSS class names (`.artifact-*` in the app, `.mp-*` inside the frame).
- Every new env var: `src/config.py` default, `.env.example`, `docs/features/artifacts.md`.
- Hard rules from `CLAUDE.md`: check exit codes directly (redirect to a log, branch on `$?`), E2E runs the last `make build`, desktop + mobile (768px), Conventional Commits, no infra hostnames, never hand-edit generated API files (`make openapi && make types`).

## Review Focus

1. **Agent HTML that fights the loader** - a full `<!doctype html><html><head>…` document, a `<script>` that throws, an inline script using an earlier external `<script src>`, code waiting for `DOMContentLoaded`: content renders, scripts run in order, a throw shows the error badge and the rest of the artifact keeps working. Tests in Task 6 (`loader.test.ts`).
2. **A frame trying to escape** - `fetch('https://…')`, `new Image().src='https://…'`, `window.top.location=…`, `window.open`, posting a fake `send` without a click, a message from a frame the parent did not create: each is blocked, nothing is sent. Tests in Task 6 (gesture gate), Task 7 (source check) and Task 8 (E2E `fetch` + `top` navigation).
3. **Regenerate / edit-and-resend / delete a conversation after artifacts were made and revised** - no orphan rows, `latest_version` right, older messages' frames keep working, no dead "newer below" link. Tests in Task 1 (triggers) and Task 7 (badge from store).
4. **The same artifact on a phone and a laptop** - per-device height, reflow below 480px, rotation re-measures, no jolt of the auto-scroll while the frame reports its height. Tests in Task 7 (height cache keyed by width bucket) and Task 8 (mobile E2E + visual).
5. **A reload or a resumed stream mid-turn after `create_artifact` finished** - the frame appears once (not twice) and stays live through `done`. Tests in Task 4 (journal replay) and Task 7 (`decorateArtifacts` idempotent by `id@version`).

---

### Task 1: Config, tables, triggers and the DB mixin

**Files:**
- Create: `migrations/0065_add_artifacts.py`, `src/db/models/artifacts.py`
- Modify: `src/db/models/__init__.py` (add `ArtifactMixin` to `Database`), `src/db/models/dataclasses.py` (`Artifact`, `ArtifactVersion`), `src/config.py`, `.env.example`
- Test: `tests/unit/test_artifacts_storage.py`

**Interfaces:**
- Produces:
  - `Artifact(id: str, conversation_id: str, user_id: str, title: str, latest_version: int, state: dict[str, Any] | None, created_at: datetime, updated_at: datetime)`
  - `ArtifactVersion(artifact_id: str, version: int, html: str, created_by_message_id: str | None, created_at: datetime)`
  - `db.create_artifact(conversation_id: str, user_id: str, title: str, html: str) -> tuple[Artifact, ArtifactVersion]`
  - `db.add_artifact_version(artifact_id: str, html: str, title: str | None = None) -> ArtifactVersion` (version = latest + 1, updates `latest_version`, `updated_at`, and `title` when given)
  - `db.get_artifact(artifact_id: str) -> Artifact | None`
  - `db.get_artifact_version(artifact_id: str, version: int) -> ArtifactVersion | None`
  - `db.count_conversation_artifacts(conversation_id: str) -> int`
  - `db.set_artifact_state(artifact_id: str, state: dict[str, Any] | None) -> None`
  - `db.link_artifact_versions(message_id: str, refs: list[tuple[str, int]]) -> None` (sets `created_by_message_id`)
  - `db.get_artifact_for_user(artifact_id: str, user_id: str) -> Artifact | None` (joins `conversations` on `user_id`)
- Config: `ARTIFACTS_ENABLED` (true), `ARTIFACT_MAX_BYTES` (200000), `ARTIFACT_STATE_MAX_BYTES` (50000), `ARTIFACT_MAX_PER_CONVERSATION` (30).

- [ ] **Step 1: Failing tests**

```python
"""Artifact storage and its cleanup triggers (src/db/models/artifacts.py)."""

from typing import Any

from src.db.models.dataclasses import MessageRole


def test_create_then_add_version(test_database: Any, test_conversation: Any) -> None:
    art, v1 = test_database.create_artifact(
        test_conversation.id, test_conversation.user_id, "Tip calculator", "<p>1</p>"
    )
    assert (v1.version, art.latest_version) == (1, 1)
    v2 = test_database.add_artifact_version(art.id, "<p>2</p>", title="Tips")
    assert v2.version == 2
    stored = test_database.get_artifact(art.id)
    assert stored is not None and (stored.latest_version, stored.title) == (2, "Tips")
    assert test_database.get_artifact_version(art.id, 1).html == "<p>1</p>"


def test_state_round_trip(test_database: Any, test_conversation: Any) -> None:
    art, _ = test_database.create_artifact(test_conversation.id, test_conversation.user_id, "T", "x")
    test_database.set_artifact_state(art.id, {"checked": [1, 3]})
    assert test_database.get_artifact(art.id).state == {"checked": [1, 3]}


def test_ownership_lookup(test_database: Any, test_conversation: Any) -> None:
    art, _ = test_database.create_artifact(test_conversation.id, test_conversation.user_id, "T", "x")
    assert test_database.get_artifact_for_user(art.id, test_conversation.user_id) is not None
    assert test_database.get_artifact_for_user(art.id, "someone-else") is None


def test_deleting_the_message_removes_its_versions(test_database: Any, test_conversation: Any) -> None:
    art, _ = test_database.create_artifact(test_conversation.id, test_conversation.user_id, "T", "v1")
    m1 = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "made it")
    test_database.link_artifact_versions(m1.id, [(art.id, 1)])
    test_database.add_artifact_version(art.id, "v2")
    m2 = test_database.add_message(test_conversation.id, MessageRole.ASSISTANT, "revised")
    test_database.link_artifact_versions(m2.id, [(art.id, 2)])

    test_database.delete_messages_after(test_conversation.id, test_conversation.user_id, m2.id, inclusive=True)

    assert test_database.get_artifact_version(art.id, 2) is None
    assert test_database.get_artifact(art.id).latest_version == 1

    test_database.delete_messages_after(test_conversation.id, test_conversation.user_id, m1.id, inclusive=True)
    assert test_database.get_artifact(art.id) is None


def test_deleting_the_conversation_removes_its_artifacts(test_database: Any, test_conversation: Any) -> None:
    art, _ = test_database.create_artifact(test_conversation.id, test_conversation.user_id, "T", "x")
    test_database.delete_conversation(test_conversation.id, test_conversation.user_id)
    assert test_database.get_artifact(art.id) is None
    assert test_database.get_artifact_version(art.id, 1) is None
```

(Check `delete_conversation`'s exact name/signature in `src/db/models/conversation.py:~200` and `add_message`'s positional order in `src/db/models/message.py:~185` before running; adjust the calls, not the assertions.)

- [ ] **Step 2: Run** `.venv/bin/pytest tests/unit/test_artifacts_storage.py -q > /tmp/a1.log 2>&1; echo $?` → non-zero (`create_artifact` missing).

- [ ] **Step 3: Implement**

Migration `migrations/0065_add_artifacts.py`:

```python
"""Add artifacts: agent-made HTML/JS shown inline in a sandboxed frame.

Spec: docs/superpowers/specs/2026-10-11-inline-artifacts-design.md. Foreign keys
are not enforced and messages are deleted from many places, so cleanup is by
trigger: a message's versions go with it, an artifact goes with its last version
and with its conversation.
"""

from yoyo import step

__depends__ = {"0064_purge_stale_interjections"}

steps = [
    step(
        """CREATE TABLE artifacts (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            latest_version INTEGER NOT NULL DEFAULT 1,
            state TEXT,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL
        )""",
        "DROP TABLE artifacts",
    ),
    step(
        "CREATE INDEX idx_artifacts_conversation ON artifacts(conversation_id)",
        "DROP INDEX IF EXISTS idx_artifacts_conversation",
    ),
    step(
        """CREATE TABLE artifact_versions (
            artifact_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            html TEXT NOT NULL,
            created_by_message_id TEXT,
            created_at TIMESTAMP NOT NULL,
            PRIMARY KEY (artifact_id, version)
        )""",
        "DROP TABLE artifact_versions",
    ),
    step(
        "CREATE INDEX idx_artifact_versions_message ON artifact_versions(created_by_message_id)",
        "DROP INDEX IF EXISTS idx_artifact_versions_message",
    ),
    step(
        "ALTER TABLE messages ADD COLUMN artifacts TEXT",
        "ALTER TABLE messages DROP COLUMN artifacts",
    ),
    step(
        """CREATE TRIGGER artifact_versions_message_delete AFTER DELETE ON messages
        BEGIN
            DELETE FROM artifact_versions WHERE created_by_message_id = OLD.id;
        END""",
        "DROP TRIGGER IF EXISTS artifact_versions_message_delete",
    ),
    step(
        """CREATE TRIGGER artifacts_version_delete AFTER DELETE ON artifact_versions
        BEGIN
            DELETE FROM artifacts WHERE id = OLD.artifact_id
              AND NOT EXISTS (SELECT 1 FROM artifact_versions WHERE artifact_id = OLD.artifact_id);
            UPDATE artifacts
            SET latest_version = (SELECT MAX(version) FROM artifact_versions WHERE artifact_id = OLD.artifact_id)
            WHERE id = OLD.artifact_id;
        END""",
        "DROP TRIGGER IF EXISTS artifacts_version_delete",
    ),
    step(
        """CREATE TRIGGER artifacts_conversation_delete AFTER DELETE ON conversations
        BEGIN
            DELETE FROM artifact_versions
            WHERE artifact_id IN (SELECT id FROM artifacts WHERE conversation_id = OLD.id);
            DELETE FROM artifacts WHERE conversation_id = OLD.id;
        END""",
        "DROP TRIGGER IF EXISTS artifacts_conversation_delete",
    ),
]
```

`src/db/models/artifacts.py`: `ArtifactMixin` in the `KVStoreMixin` style (`_pool`, `_execute_with_timing` stub), ids from `secrets.token_urlsafe(9)`, timestamps from `utcnow_naive()`, `state` as `json.dumps`/`json.loads`, a `_row_to_artifact` / `_row_to_version` pair. `create_artifact` inserts both rows in one connection and commits once. `add_artifact_version` computes `MAX(version) + 1` inside the same connection. Keep every method under 30 lines.

Config block in `src/config.py` next to the code-sandbox settings, with one comment line each (what the limit protects).

- [ ] **Step 4: Run** the new tests + `tests/unit/test_migrations*.py` (whatever exists for migration apply/rollback) → 0.
- [ ] **Step 5: Commit** `feat(db): artifacts and versions with cleanup triggers`.

---

### Task 2: `messages.artifacts` through the message layers and API

**Files:**
- Modify: `src/db/models/dataclasses.py` (`Message.artifacts: list[dict[str, Any]] | None = None`), `src/db/models/message_rows.py` (`artifacts=_json_column(row, "artifacts")`), `src/db/models/message.py` (`add_message(..., artifacts=None)` and `update_message_content(..., artifacts=None)`, serialized with `_json_or_none`, added to both SQL statements), `src/api/utils.py` (`add_artifacts(data, msg)` next to `add_research`, called everywhere `add_research` is), `src/api/helpers/stream_resume.py` (done event from a saved message carries `artifacts`), `src/api/schemas/chat.py` (`ArtifactRef` model; `artifacts: list[ArtifactRef] | None` on `MessageResponse`, `ChatBatchResponse` and the done-event schema)
- Regenerate: `make openapi && make types`
- Test: `tests/unit/test_message_artifacts_storage.py`

**Interfaces:**
- Produces: `Message.artifacts` (`[{"id": str, "version": int, "title": str}]`), API field `artifacts` on messages, batch responses and `done` events; TS type `ArtifactRef` in `generated-api.ts`.

- [ ] **Step 1: Failing tests** - round-trip on `add_message` and `update_message_content` (mirror `tests/unit/test_message_research_storage.py`); `serialize_messages_for_response` includes `artifacts` only when set; `build_stream_done_event` includes it when the saved message has it.
- [ ] **Step 2: Run** → TypeError on `artifacts=`.
- [ ] **Step 3: Implement**

```python
def add_artifacts(data: dict[str, Any], msg: Any) -> None:
    """Artifacts shown under the message ([{id, version, title}]), when it has any."""
    artifacts = getattr(msg, "artifacts", None)
    if artifacts:
        data["artifacts"] = artifacts
```

```python
class ArtifactRef(BaseModel):
    """One artifact version shown under a message."""

    id: str = Field(description="Artifact id")
    version: int = Field(description="Version shown in this message")
    title: str = Field(description="Artifact title")
```

- [ ] **Step 4: Run** the new tests + `tests/unit/test_message_research_storage.py` + `tests/integration/test_chat_annotations.py` → 0; `make openapi && make types` → 0.
- [ ] **Step 5: Commit** `feat(api): messages carry the artifacts shown under them`.

---

### Task 3: The three tools and the prompt guide

**Files:**
- Create: `src/agent/tools/artifacts.py`, `src/agent/prompt_texts/artifacts.py`
- Modify: `src/agent/tools/__init__.py` (import; append the three tools in `get_available_tools()` when `Config.ARTIFACTS_ENABLED`; add their names to `_SPORTS_EXCLUDED_TOOLS`; add them to `_TOOL_MAP` is NOT done - they are not grantable to autonomous agents), `src/agent/tool_display.py` (`TOOL_METADATA` entries: `create_artifact` "Building an artifact" / "Built an artifact", icon `sparkles`; `update_artifact` "Updating the artifact" / "Updated the artifact"; `read_artifact` "Reading the artifact" / "Read the artifact", icon `file`), `docs/features/agent-tools.md` (tools table)
- Test: `tests/unit/test_artifact_tools.py`

**Interfaces:**
- Consumes: Task 1 DB methods; `get_conversation_context() -> tuple[conversation_id, user_id]`.
- Produces:
  - `create_artifact(title: str, html: str) -> str`
  - `update_artifact(artifact_id: str, edits: list[dict[str, str]] | None = None, html: str | None = None, title: str | None = None) -> str`
  - `read_artifact(artifact_id: str) -> str`
  - All return JSON; success carries `"artifact": {"id", "version", "title"}` (create/update) - the key Task 4 reads. `read_artifact` returns `{"success": true, "artifact": {...}, "html": "..."}` and is NOT turned into an event or a message ref (Task 4 filters by tool name).
  - `apply_edits(html: str, edits: list[dict[str, str]]) -> str` raising `EditError(message)`; exported for tests.
  - `ARTIFACT_TOOL_NAMES = frozenset({"create_artifact", "update_artifact"})` - the tools whose results produce artifact refs.

- [ ] **Step 1: Failing tests**

```python
"""Artifact tools (src/agent/tools/artifacts.py)."""

import json
from typing import Any

import pytest

from src.agent.tools.artifacts import EditError, apply_edits, create_artifact, read_artifact, update_artifact
from src.agent.tools.context import set_conversation_context
from src.config import Config


@pytest.fixture
def ctx(test_database: Any, test_conversation: Any) -> Any:
    set_conversation_context(test_conversation.id, test_conversation.user_id)
    yield test_conversation
    set_conversation_context(None, None)


def _call(tool: Any, **args: Any) -> dict[str, Any]:
    return json.loads(tool.invoke(args))


def test_create_returns_the_ref(ctx: Any) -> None:
    out = _call(create_artifact, title="Tips", html="<p>hi</p>")
    assert out["success"] is True
    assert out["artifact"]["version"] == 1 and out["artifact"]["title"] == "Tips"


def test_create_rejects_oversized_html(ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "ARTIFACT_MAX_BYTES", 10)
    out = _call(create_artifact, title="T", html="<p>far too long</p>")
    assert out["success"] is False and "limit" in out["error"]


def test_create_rejects_past_the_per_conversation_cap(ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, "ARTIFACT_MAX_PER_CONVERSATION", 1)
    _call(create_artifact, title="A", html="a")
    assert _call(create_artifact, title="B", html="b")["success"] is False


def test_apply_edits_exactly_once() -> None:
    assert apply_edits("<b>1</b><i>2</i>", [{"find": "1", "replace": "one"}]) == "<b>one</b><i>2</i>"
    with pytest.raises(EditError, match="not found"):
        apply_edits("<b>1</b>", [{"find": "9", "replace": "x"}])
    with pytest.raises(EditError, match="2 times"):
        apply_edits("<b>1</b><b>1</b>", [{"find": "<b>1</b>", "replace": "x"}])


def test_update_with_edits_makes_version_two(ctx: Any) -> None:
    art = _call(create_artifact, title="T", html="<p>old</p>")["artifact"]
    out = _call(update_artifact, artifact_id=art["id"], edits=[{"find": "old", "replace": "new"}])
    assert out["artifact"]["version"] == 2
    assert _call(read_artifact, artifact_id=art["id"])["html"] == "<p>new</p>"


def test_failed_edit_shows_an_excerpt_and_writes_nothing(ctx: Any) -> None:
    art = _call(create_artifact, title="T", html="<p>alpha beta</p>")["artifact"]
    out = _call(update_artifact, artifact_id=art["id"], edits=[{"find": "gamma", "replace": "x"}])
    assert out["success"] is False and "alpha beta" in out["error"]
    assert _call(read_artifact, artifact_id=art["id"])["artifact"]["version"] == 1


def test_update_needs_edits_or_html(ctx: Any) -> None:
    art = _call(create_artifact, title="T", html="x")["artifact"]
    assert _call(update_artifact, artifact_id=art["id"])["success"] is False


def test_other_conversations_artifacts_are_invisible(ctx: Any, test_database: Any, test_user: Any) -> None:
    other = test_database.create_conversation(user_id=test_user.id, title="other")
    foreign, _ = test_database.create_artifact(other.id, test_user.id, "F", "x")
    assert _call(read_artifact, artifact_id=foreign.id)["success"] is False
```

(Check `create_conversation`'s signature in `tests/conftest.py::test_conversation`.)

- [ ] **Step 2: Run** `.venv/bin/pytest tests/unit/test_artifact_tools.py -q > /tmp/a3.log 2>&1; echo $?` → ImportError.

- [ ] **Step 3: Implement**

`src/agent/tools/artifacts.py` (module docstring: what artifacts are, why the result is LLM-visible and small, link to the spec):

```python
ARTIFACT_TOOL_NAMES = frozenset({"create_artifact", "update_artifact"})
_EXCERPT_CHARS = 300


class EditError(ValueError):
    """An update_artifact edit that does not match exactly once."""


def _excerpt(html: str, needle: str) -> str:
    """The document around the needle's first 20 chars, or its start."""
    probe = needle[:20]
    at = html.find(probe) if probe else -1
    start = max(0, at - _EXCERPT_CHARS // 2) if at >= 0 else 0
    return html[start : start + _EXCERPT_CHARS]


def apply_edits(html: str, edits: list[dict[str, str]]) -> str:
    """Apply find/replace edits in order; each find must match exactly once."""
    for i, edit in enumerate(edits):
        find, replace = edit.get("find", ""), edit.get("replace", "")
        count = html.count(find) if find else 0
        if count != 1:
            where = "not found" if count == 0 else f"found {count} times"
            raise EditError(f"edit {i + 1}: find text {where}. Nearby: {_excerpt(html, find)!r}")
        html = html.replace(find, replace, 1)
    return html


def _fail(error: str) -> str:
    return json.dumps({"success": False, "error": error})


def _ok(art_id: str, version: int, title: str, message: str) -> str:
    ref = {"id": art_id, "version": version, "title": title}
    return json.dumps({"success": True, "artifact": ref, "message": message})


def _too_big(html: str) -> str | None:
    size = len(html.encode("utf-8"))
    if size > Config.ARTIFACT_MAX_BYTES:
        return f"html is {size} bytes; the limit is {Config.ARTIFACT_MAX_BYTES}. Simplify it."
    return None


def _own_artifact(artifact_id: str) -> Artifact | None:
    """The artifact when it belongs to the current conversation."""
    conv_id, _ = get_conversation_context()
    art = db.get_artifact(artifact_id)
    return art if art and conv_id and art.conversation_id == conv_id else None
```

`create_artifact` (description = `CREATE_ARTIFACT_DESCRIPTION` from the prompt module, via `@tool(description=...)`): empty title/html → `_fail`; `_too_big`; `db.count_conversation_artifacts(conv_id) >= Config.ARTIFACT_MAX_PER_CONVERSATION` → `_fail("This conversation has N artifacts, the limit. Update an existing one instead.")`; no conversation context → `_fail`; else `db.create_artifact` and `_ok(..., "Shown to the user below your reply. Don't repeat its contents in text; say in one sentence what it is.")`. Log `"Artifact created"` with `artifact_id`, `size`.

`update_artifact`: `_own_artifact` or `_fail("Unknown artifact id.")`; exactly one of `edits` / `html` else `_fail("Pass edits or html.")`; base = `db.get_artifact_version(id, art.latest_version).html`; `apply_edits` (catch `EditError` → `_fail(str(e))`); `_too_big`; `db.add_artifact_version(id, new_html, title)`; `_ok(..., "Version N shown below your reply.")`. Log `"Artifact updated"` with `artifact_id`, `version`, `mode` (`edits`/`html`), `edit_count`.

`read_artifact`: `_own_artifact` → `{"success": True, "artifact": ref, "html": html}`.

`src/agent/prompt_texts/artifacts.py`:

```python
"""create_artifact's description: when to build one and how it should look.

Lives in the tool description, so it is only sent where the tool is bound.
Keep it near 400 tokens; the class list must match web/src/artifact/design-system.css.
"""

CREATE_ARTIFACT_DESCRIPTION = """Show the user a small interactive or visual page (HTML/CSS/JS) inline below your reply: calculators, converters, recipe cards with ingredient checklists, trackers, charts, timelines, small games.

Use it only when interacting or seeing it beats reading - NEVER for plain answers, lists, tables or code the user asked to read. To change an existing artifact use update_artifact (call read_artifact first if it was made in an earlier turn).

It runs sandboxed: no network, no external URLs (images only inline SVG or data: URIs), no localStorage. Write a fragment (no <html>/<head> needed). The app's design system is already loaded:
- Bare elements are styled: h1-h3, p, a, button (add class "secondary"), input, select, input[type=range], table, ul/ol, code/pre.
- Layout: .mp-stack (vertical gap), .mp-row (horizontal, wraps), .mp-grid (auto columns), .mp-divider.
- Components: .mp-card, .mp-hero (title block), .mp-stat (<div class="mp-stat"><span>Label</span><strong>42</strong></div>), .mp-chip, .mp-checklist (ul of <label><input type=checkbox> text</label>), .mp-steps (ol), .mp-tabs (radio-based), .mp-muted, .mp-accent.
- Colours only via var(--mp-text|--mp-muted|--mp-accent|--mp-surface|--mp-border|--mp-success|--mp-warning|--mp-error) or currentColor - never hex. It must look right in light and dark.
- Sizing: fluid only (%, fr, minmax, flex). No fixed widths or heights. SVG: viewBox plus width="100%". It must work from 320px phone width to desktop.

Bridge (global mp):
- mp.send(text): send text as the user's next message (only from a click handler).
- await mp.state.get() / mp.state.set(obj): save small JSON (ticked items, scores); it survives reloads and other devices.
- mp.theme ('light'|'dark') and window 'mp:theme' event.

Example: <div class="mp-card mp-stack"><h2>Tip</h2><input id="b" type="number" placeholder="Bill"><div class="mp-stat"><span>Tip 10%</span><strong id="t">0</strong></div></div><script>b.oninput=()=>t.textContent=(b.value*0.1).toFixed(2)</script>

title: short name in the user's language. html: the complete page."""
```

- [ ] **Step 4: Run** the test file + `tests/unit/test_tool_display.py` + `tests/unit/test_tools*.py` → 0 (the tool-display check fails if a bindable tool has no label).
- [ ] **Step 5: Commit** `feat(agent): create, update and read artifacts`.

---

### Task 4: Saving refs, MSG_CONTEXT, the stream event and batch parity

**Files:**
- Create: `src/agent/artifact_refs.py`
- Modify: `src/api/helpers/chat_save.py` (`artifacts` param on `_persist_assistant_message` → `kwargs`; `save_message_to_db` extracts refs, persists, then `db.link_artifact_versions`; `SaveResult.artifacts`), `src/api/utils.py` (`build_chat_response` / `build_stream_done_event` include `artifacts` from the save result), `src/agent/stream_events.py` (`_tool_message` yields `{"type": "artifact", **ref}` after `tool_end` for `ARTIFACT_TOOL_NAMES`), `src/api/helpers/chat_streaming.py` (`FORWARDED_EVENT_TYPES` += `"artifact"`), `src/api/helpers/stream_resume.py` (`_JOURNALED_EVENT_TYPES` += `"artifact"`), `src/agent/history.py` + `src/agent/message_content.py` (`MSG_CONTEXT` `artifacts`), `src/api/routes/chat.py` (SSE event docs list: `artifact`), `tests/e2e-server.py` (`/test/set-artifact`)
- Test: `tests/unit/test_artifact_refs.py`, `tests/integration/test_chat_artifacts.py`, `tests/unit/test_history.py` (extend), `tests/unit/test_stream_events.py` (extend; find the file that covers `StreamEventProcessor._tool_message`)

**Interfaces:**
- Consumes: `ARTIFACT_TOOL_NAMES`, tool JSON shape (Task 3); `db.link_artifact_versions` (Task 1); `Message.artifacts`, `add_artifacts` (Task 2).
- Produces:
  - `artifact_ref_from_tool_content(tool_name: str | None, content: Any) -> dict[str, Any] | None` - the `artifact` dict from a successful create/update result, else None (malformed JSON → None).
  - `extract_artifact_refs(result_messages: list[Any]) -> list[dict[str, Any]]` - refs from the turn's `ToolMessage`s in order; the same artifact updated twice in one turn keeps only its last version, at the position of its first appearance.
  - SSE event `{"type": "artifact", "id": str, "version": int, "title": str}`.
  - MSG_CONTEXT key `artifacts`: `"<id> v<version> '<title>'; ..."`.
  - E2E hook `POST /test/set-artifact {"title": str, "html": str}`: the next mock streamed turn creates the artifact through the real `create_artifact` tool (with the conversation context set), yields the `artifact` event before its tokens, and puts a matching `ToolMessage(name="create_artifact", content=<tool JSON>, tool_call_id="call-art")` into `final["result_messages"]`.

- [ ] **Step 1: Failing tests**

```python
"""Artifact refs from a turn's tool messages (src/agent/artifact_refs.py)."""

import json

from langchain_core.messages import AIMessage, ToolMessage

from src.agent.artifact_refs import artifact_ref_from_tool_content, extract_artifact_refs


def _result(name: str, art_id: str, version: int, ok: bool = True) -> ToolMessage:
    body = {"success": ok, "artifact": {"id": art_id, "version": version, "title": "T"}}
    return ToolMessage(name=name, content=json.dumps(body), tool_call_id=f"{art_id}{version}")


def test_refs_in_order_with_the_last_version_of_each() -> None:
    msgs = [AIMessage(content=""), _result("create_artifact", "a", 1), _result("create_artifact", "b", 1),
            _result("update_artifact", "a", 2)]
    assert [(r["id"], r["version"]) for r in extract_artifact_refs(msgs)] == [("a", 2), ("b", 1)]


def test_reads_failures_and_other_tools_are_ignored() -> None:
    msgs = [_result("read_artifact", "a", 1), _result("create_artifact", "b", 1, ok=False),
            ToolMessage(name="web_search", content="not json", tool_call_id="x")]
    assert extract_artifact_refs(msgs) == []
    assert artifact_ref_from_tool_content("create_artifact", "{bad") is None
```

  Integration (`tests/integration/test_chat_artifacts.py`, using the existing chat-stream integration fixtures - mirror `tests/integration/test_chat_annotations.py`):
  - a streamed turn whose mocked `stream_chat_events` yields an `artifact` event and a final with the `ToolMessage` → the SSE stream contains `event artifact` and `done.artifacts == [{id, version: 1, title}]`; the saved message has `artifacts`; the version's `created_by_message_id` is the message id;
  - the journal replays the `artifact` event through the resume endpoint;
  - the batch endpoint with the same mocked `chat_batch` result returns `artifacts`;
  - `enrich_history` puts `artifacts: "<id> v1 'T'"` into the message's MSG_CONTEXT.
  - `stream_events`: a `ToolMessage(name="create_artifact", content=<ok JSON>)` with a pending call id yields `tool_end` then `artifact`; a failed result yields only `tool_end`.

- [ ] **Step 2: Run** → ImportError / missing events.
- [ ] **Step 3: Implement** - `artifact_refs.py` (two functions above, each < 25 lines, `json.loads` in try/except `ValueError`/`TypeError`); in `chat_save.save_message_to_db` after `_extract_stream_metadata`: `artifacts = extract_artifact_refs(result_messages)`; pass to `_persist_assistant_message(..., artifacts=artifacts or None)`; after persisting `db.link_artifact_versions(assistant_msg.id, [(r["id"], r["version"]) for r in artifacts])`; `SaveResult.artifacts` feeds `build_chat_response` / `build_stream_done_event`. In `history.py` next to `research`:

```python
            if msg.artifacts:
                metadata["artifacts"] = "; ".join(
                    f"{a['id']} v{a['version']} '{a['title']}'" for a in msg.artifacts
                )
```

  plus the `MessageMetadata` key and the `message_content.py` copy line (mirror `research`).
- [ ] **Step 4: Run** the new tests + `tests/integration/test_chat_annotations.py` + `tests/integration/test_stream_resume*.py` + `tests/unit/test_history.py` → 0.
- [ ] **Step 5: Commit** `feat(chat): artifacts saved on the reply, streamed and in history`.

---

### Task 5: Artifact API and the frame route

**Files:**
- Create: `src/api/routes/artifacts.py`, `src/api/schemas/artifacts.py`, `src/templates/artifact-frame.html`
- Modify: `src/api/routes/__init__.py` (register blueprint), `src/app.py` (`frame-src 'self'` in `_CSP_POLICY`; `/artifact-frame` route; manifest lookup for `src/artifact/frame.ts`), `web/vite.config.ts` (second input `artifact-frame: resolve(__dirname, 'src/artifact/frame.ts')` - `rollupOptions.input` becomes an object with `main` and `artifact-frame`; check `src/app.py` still finds `src/main.ts` in the manifest), `web/vite.config.ts` dev proxy (`/artifact-frame` → 8000)
- Regenerate: `make openapi && make types`
- Test: `tests/integration/test_artifacts_api.py`, `tests/unit/test_artifact_frame_route.py`

**Interfaces:**
- Consumes: Task 1 DB methods.
- Produces:
  - `GET /api/artifacts/<artifact_id>/versions/<int:version>` → `ArtifactVersionResponse {id, version, title, html, state}`; 404 when not owned or missing.
  - `PUT /api/artifacts/<artifact_id>/state` body `ArtifactStateRequest {state: dict | None}` → 204; 413 over `ARTIFACT_STATE_MAX_BYTES` (measured as `len(json.dumps(state).encode())`); 404 when not owned.
  - `GET /artifact-frame` → the shell HTML, `Cache-Control: no-cache`, headers `Content-Security-Policy: <frame CSP>`, `X-Frame-Options: SAMEORIGIN` (set before the app-wide `setdefault`s run, so they win).
  - `build_frame_csp(dev_mode: bool) -> str` in `src/app.py` (or `src/utils/artifact_frame.py` if `app.py` would pass 500 lines).

- [ ] **Step 1: Failing tests**
  - API: owner gets html + state; another user gets 404; unknown version 404; PUT state round-trips into the next GET; PUT over the limit → 413 and the stored state is unchanged; PUT `null` clears it.
  - Frame route: status 200; CSP equals the Global Constraints string exactly in production mode and contains `http://localhost:5173` only in dev mode; `X-Frame-Options == "SAMEORIGIN"`; no `Set-Cookie`; the app index's CSP now contains `frame-src https://accounts.google.com 'self'`.
- [ ] **Step 2: Run** → 404s.
- [ ] **Step 3: Implement** - routes follow `src/api/routes/kv_store.py` (APIFlask blueprint, `@require_auth`, `@bp.output`, `raise_validation_error` / `abort(404)` conventions in that file). Template:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    {% if dev_mode %}
    <script type="module" src="http://localhost:5173/src/artifact/frame.ts"></script>
    {% else %}
    {% for css_file in css_files %}
    <link rel="stylesheet" href="/static/assets/{{ css_file }}">
    {% endfor %}
    <script type="module" src="/static/assets/{{ js_file }}"></script>
    {% endif %}
</head>
<body></body>
</html>
```

- [ ] **Step 4: Run** the new tests + `tests/unit/test_app*.py` + `tests/integration/test_security_headers*.py` (whatever covers CSP) → 0; `make build > /tmp/a5b.log 2>&1; echo $?` → 0 and the manifest has both entries (frame.ts may be an empty module until Task 6: create `web/src/artifact/frame.ts` with `export {};` here).
- [ ] **Step 5: Commit** `feat(api): artifact versions, state, and the sandboxed frame page`.

---

### Task 6: Inside the frame - design system, loader and bridge client

**Files:**
- Create: `web/src/artifact/design-system.css`, `web/src/artifact/loader.ts`, `web/src/artifact/bridge-client.ts`, `web/src/artifact/protocol.ts`
- Modify: `web/src/artifact/frame.ts` (imports the CSS, wires loader + bridge client)
- Test: `web/tests/unit/artifact-loader.test.ts`, `web/tests/unit/artifact-bridge-client.test.ts`, `web/tests/unit/artifact-design-system.test.ts`

**Interfaces:**
- Produces (shared with Task 7 via `protocol.ts`, imported by both sides):

```typescript
/** Parent -> frame */
export type ToFrame =
  | { type: 'mp:init'; html: string; theme: 'light' | 'dark'; state: unknown }
  | { type: 'mp:theme'; theme: 'light' | 'dark' };

/** Frame -> parent */
export type FromFrame =
  | { type: 'mp:ready' }
  | { type: 'mp:rendered' }
  | { type: 'mp:height'; height: number }
  | { type: 'mp:send'; text: string }
  | { type: 'mp:state'; state: unknown }
  | { type: 'mp:link'; href: string }
  | { type: 'mp:error'; message: string };

export function isFromFrame(data: unknown): data is FromFrame;
```

  - `loadArtifact(doc: Document, html: string): Promise<void>` (loader.ts) - parse with `DOMParser`, move `<style>`/`<link rel=stylesheet>` from the parsed head and every body node into `doc.body` (head styles into `doc.head`), then re-create each `<script>` in document order (copy attributes and text; await `load`/`error` for `src` scripts), then `doc.dispatchEvent(new Event('DOMContentLoaded'))` and `window.dispatchEvent(new Event('load'))`.
  - `installBridgeClient(win: Window, post: (msg: FromFrame) => void): void` (bridge-client.ts) - defines `window.mp = { send, state: { get, set }, theme }`; `send` posts only when `navigator.userActivation?.isActive` (fallback: a click/keydown seen within the last 1000ms when `userActivation` is missing); a `ResizeObserver` on `document.documentElement` posts `mp:height` (rounded, deduped); `window.onerror` / `unhandledrejection` / wrapped `console.error` post `mp:error` (message only, max 300 chars); a capturing `click` listener on `a[href]` calls `preventDefault` and posts `mp:link`.
  - `frame.ts` accepts the first `mp:init` only from `window.parent`, ignores any later `mp:init`, applies `mp:theme` (sets `document.documentElement.dataset.theme`, updates `mp.theme`, dispatches `mp:theme` on `window`), posts `mp:ready` on start and `mp:rendered` after `loadArtifact`.
- Design system: tokens aliasing `variables.css` (`--mp-bg: transparent; --mp-surface: var(--color-neutral-850)`… - pick from `variables.css` for both themes), base element styles, the class list from the spec, `container-type: inline-size` on `body` with `@container (max-width: 480px)` rules stacking `.mp-row`/`.mp-grid`.

- [ ] **Step 1: Failing tests**
  - loader: a fragment renders; a full document's `<style>` lands in `head` and its body content in `body`; two inline scripts run in order; `<script src="data:text/javascript,window.__a=1">` then inline `window.__b=window.__a+1` → `__b === 2`; a throwing script does not stop the next one; a `DOMContentLoaded` listener added by agent code fires.
  - bridge client: `mp.send` without activation posts nothing; with activation (stub `navigator.userActivation`) posts `mp:send`; `mp.state.set` posts `mp:state`; `mp.state.get()` resolves to the init state; link click posts `mp:link` and is prevented; `console.error('x')` posts `mp:error`.
  - design system: parse `design-system.css`; every `var(--…)` used in a `--mp-*` definition names a property defined in `web/src/styles/variables.css`; no hex colours outside `variables.css`; every class named in `src/agent/prompt_texts/artifacts.py` exists as a selector.
- [ ] **Step 2: Run** `cd web && npx vitest run tests/unit/artifact-*.test.ts > /tmp/a6.log 2>&1; echo $?` → 1.
- [ ] **Step 3: Implement** the four files; keep each function < 50 lines.
- [ ] **Step 4: Run** → 0; `make lint > /tmp/a6l.log 2>&1; echo $?` → 0.
- [ ] **Step 5: Commit** `feat(web): artifact frame - design system, loader and bridge`.

---

### Task 7: In the chat - frames under messages, bridge host, sizing

**Files:**
- Create: `web/src/components/messages/artifacts.ts` (render + decorate), `web/src/core/artifact-host.ts` (message handling, theme observer, state saves), `web/src/core/artifact-height.ts` (per-device cache), `web/src/api/artifacts.ts`, `web/src/styles/components/artifacts.css` (imported in `main.css`)
- Modify: `web/src/types/api.ts` (`Message.artifacts?: ArtifactRef[]`, done event `artifacts`), `web/src/components/messages/render.ts` (call `decorateArtifacts(messageEl, message)` next to `decorateGrounding`), `web/src/core/stream-done.ts` (same, plus `artifacts` in `assistantMessageFromDone`), `web/src/core/stream-events.ts` (`case 'artifact'` → `addLiveArtifact(messageEl, ref)`), `web/src/core/file-actions.ts` (copied text appends `\n\n[Artifact: <title>]` per artifact), `web/src/config.ts` (`ARTIFACT_MAX_HEIGHT_VH`, `ARTIFACT_READY_TIMEOUT_MS`, `ARTIFACT_STATE_SAVE_DEBOUNCE_MS`)
- Test: `web/tests/component/artifacts.test.ts`, `web/tests/unit/artifact-host.test.ts`, `web/tests/unit/artifact-height.test.ts`

**Interfaces:**
- Consumes: `ToFrame`, `FromFrame`, `isFromFrame` (Task 6); API (Task 5); `sendUiMessage(text)` from `core/messaging.ts`.
- Produces:
  - `decorateArtifacts(messageEl: HTMLElement, message: { id: string; artifacts?: ArtifactRef[] }): void` - ensures one `.artifact-card[data-artifact-key="id@version"]` per ref in a `.artifact-list` after the message content, keeping existing cards (idempotent), removing cards whose key is no longer listed; then `refreshVersionBadges()`.
  - `addLiveArtifact(messageEl: HTMLElement, ref: ArtifactRef): void` - same card during streaming.
  - `refreshVersionBadges(container?: HTMLElement): void` - for each card, when a later card in DOM order has the same id and a higher version, shows "v{n} · newer below" (button; click scrolls to and flashes it with `flashElement` from `action-row.ts`).
  - `fetchArtifactVersion(id: string, version: number): Promise<ArtifactVersion>`, `saveArtifactState(id: string, state: unknown): Promise<void>` (api/artifacts.ts, via the existing API client).
  - `registerFrame(frame: HTMLIFrameElement, ref: ArtifactRef, onReady: () => void): () => void` (artifact-host.ts) - one window `message` listener for all frames (installed once), routes by `event.source === frame.contentWindow`; ignores anything else; handles `mp:height` (applies `min(height, ARTIFACT_MAX_HEIGHT_VH vh)`, stores in the height cache, defers growth while `isUserScrolling()` - reuse the existing scroll-intent helper in `core/response-scroll.ts` or `components/messages/utils.ts`; find it by grepping `userScrolling`/`isUserScrolling`), `mp:send` (`sendUiMessage(text.slice(0, 2000))`), `mp:state` (debounced `saveArtifactState`), `mp:link` (`https:` only → `window.open(href, '_blank', 'noopener')`), `mp:error` (badge "Artifact error" + `log.warn`).
  - `observeTheme()` - one `MutationObserver` on `document.documentElement` `data-theme`, posting `mp:theme` to every registered frame.
  - `heightCacheKey(ref: ArtifactRef, widthPx: number): string` → `` `${id}@${version}:${Math.round(widthPx / 80)}` ``; `getCachedHeight(key): number | null`, `setCachedHeight(key, px)` (`localStorage`, try/catch, capped at 200 entries, oldest dropped).
- Card markup: `.artifact-card` > `.artifact-card-header` (title, badge slot, "View source" button opening the HTML in the existing `Modal` as escaped `<pre>`) + `iframe.artifact-frame[sandbox="allow-scripts"][src="/artifact-frame"][title=<title>][loading="lazy"]`; failure state `.artifact-card--failed` with "Couldn't display", Retry, View source.

- [ ] **Step 1: Failing tests**
  - component: a message with two refs renders two cards with `sandbox="allow-scripts"` exactly; calling `decorateArtifacts` again keeps the same iframe elements; a ref removed from the message removes its card; a v1 card followed by a v2 card of the same id shows the badge on v1 only, and none when the v2 card is absent; copy text includes `[Artifact: T]`.
  - host: a message whose `source` is not a registered frame is ignored; `mp:send` from a registered frame calls `sendUiMessage`; `mp:link` with `javascript:` is ignored and `https:` opens; `mp:state` saves once after the debounce for three quick updates; `mp:height` above the cap is clamped; no `mp:ready` within the timeout → failed state; a `data-theme` change posts `mp:theme` to every frame.
  - height cache: keys differ for 390px vs 1200px widths; a reserved height is applied before `mp:height`; storage throwing is harmless.
- [ ] **Step 2: Run** `cd web && npx vitest run tests/component/artifacts.test.ts tests/unit/artifact-host.test.ts tests/unit/artifact-height.test.ts > /tmp/a7.log 2>&1; echo $?` → 1.
- [ ] **Step 3: Implement.** On `mp:ready` the host fetches the version (once per card; cached in a module `Map` by key) and posts `mp:init {html, theme: current data-theme or 'dark', state}`. CSS: card on `--color-neutral-850`-family surface with the app's radius, header row 44px min hit areas, iframe `width: 100%; border: 0; display: block; background: transparent`, `color-scheme: normal` on the iframe so the frame background stays transparent in both themes.
- [ ] **Step 4: Run** → 0; also `web/tests/component/render*.test.ts`, `web/tests/unit/stream-done*.test.ts`, `web/tests/unit/stream-events*.test.ts` → 0 (update mocks that build full `Message` objects only if the type change requires it).
- [ ] **Step 5: Commit** `feat(web): artifacts render inline under the reply`.

---

### Task 8: E2E and visual

**Files:**
- Create: `web/tests/e2e/chat/artifacts.spec.ts`, `web/tests/visual/artifacts.visual.ts`, `web/tests/fixtures/artifact-kitchen-sink.html` (every design-system class, a checklist, an SVG chart, a button calling `mp.send('Scale to 6')`, a `fetch('https://example.com')` probe writing its outcome into `#net`, a `top.location` probe writing into `#top`)
- Modify: `tests/e2e-server.py` (already has `/test/set-artifact` from Task 4)

- [ ] **Step 1: Specs** (set the canned artifact AFTER the `page` fixture - it resets per-test mock config):
  - the reply shows the card and the frame's content (`frameLocator('.artifact-frame')`);
  - toggling the theme in Settings flips the frame's `html[data-theme]`;
  - clicking the frame's button sends "Scale to 6" as a user message;
  - ticking a checklist item, reloading, and reopening the conversation keeps it ticked;
  - `#net` reads "blocked" and `#top` reads "blocked" (the probes catch and write);
  - a second turn with an updated version shows "v1 · newer below" on the first card, and clicking it scrolls to the second;
  - mobile (390px; open the sidebar via `#menu-btn` first where needed): the card fills the column width, `.mp-row` items stack, no horizontal scroll in the frame (`scrollWidth <= clientWidth`).
  - Visual: kitchen sink in dark and light, desktop and mobile.
- [ ] **Step 2:** `make build > /tmp/a8b.log 2>&1; echo $?` → 0; run chromium + webkit for the new specs; create darwin baselines (`--update-snapshots`, run twice to verify stable).
- [ ] **Step 3: Commit** `test(e2e): inline artifacts`.

---

### Task 9: Evals

**Files:**
- Create: `evals/cases/artifact_calculator.yaml` (user: "Udělej mi kalkulačku spropitného"; `required_tools: [create_artifact]`; rubric: works without network, uses `mp-*` classes or tokens, no hex colours, no fixed px widths), `evals/cases/artifact_recipe.yaml` (user: "Recept na svíčkovou pro 4"; `required_tools: [create_artifact]`; rubric: checklist of ingredients, steps, servings), `evals/cases/artifact_not_for_facts.yaml` (user: "Kolik má Praha obyvatel?"; `forbidden_tools: [create_artifact]`), `evals/cases/artifact_revision.yaml` (two turns: calculator, then "přidej možnost 15 %"; second turn `required_tools: [update_artifact]` or `[read_artifact, update_artifact]`, `forbidden_tools: [create_artifact]`)
- Modify: `evals/` harness only if multi-turn cases need support it lacks (check an existing multi-turn case first); add a deterministic check helper `no_hex_colours(html)` / `no_fixed_widths(html)` if the harness supports code checks on tool args.

- [ ] Steps: run the four cases (3x for the precision/recall ones), **report the USD cost**; tune `CREATE_ARTIFACT_DESCRIPTION` only on evidence from failures. Commit `test(evals): artifact creation, precision and revision`.

---

### Task 10: Docs, TODO, verification, merge

- [ ] `docs-updater` agent: new `docs/features/artifacts.md` (what, flow, frame security model and CSP, bridge protocol, design-system class list, config table, pitfalls: `srcdoc` inherits the parent CSP, the JWT header cannot reach a frame navigation, triggers instead of FKs, `ToolMessage` content is stripped of `_full_result` so refs live in the visible JSON); link from `docs/README.md`, `docs/features/agent-tools.md`, `docs/features/chat-and-streaming.md` (`artifact` event, `artifacts` field), `docs/features/ui-features.md`.
- [ ] `TODO.md`: remove the "Artifacts" item; add (a) agent reads artifact state, (b) web components from observed use, (c) safe remote images, (d) side panel, (e) bundled libraries if SVG proves limiting, (f) conversation images (generated/uploaded) usable in artifacts via parent-resolved `blob:` URLs.
- [ ] `make lint > /tmp/l.log 2>&1; echo $?` → 0; `caffeinate -i make test-all > /tmp/t.log 2>&1; echo $?` → 0.
- [ ] Final review (`superpowers:requesting-code-review`) with the Review Focus list, fix pass.
- [ ] With the user: Linux baselines via `/regen-baselines` after push; prod `.env` gets the new keys (values = defaults); merge, one deploy; try a recipe and a calculator on the phone and the laptop, check scroll stability on iOS with the kbdebug overlay.
