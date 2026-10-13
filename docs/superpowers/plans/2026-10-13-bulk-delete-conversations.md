# Bulk Delete Conversations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Select many chats in the main sidebar list and move them to the trash in one action, without a confirm, with one Undo.

**Architecture:** Two new POST endpoints (`bulk-trash`, `bulk-restore`) backed by single-transaction `BEGIN IMMEDIATE` updates on `ConversationTrashMixin`. "Select all" is resolved server-side (`all` + `exclude_ids` + `created_before`). On the client a `selection` store slice holds the selection; `SidebarSelection.ts` owns the selection chrome; `Sidebar.ts` only renders a checkbox per row through one hook.

**Tech Stack:** Flask + APIFlask + Pydantic, SQLite (yoyo), vanilla TypeScript + Zustand, Vitest, Playwright.

**Spec:** [docs/superpowers/specs/2026-10-13-bulk-delete-conversations-design.md](../specs/2026-10-13-bulk-delete-conversations-design.md)

## Global Constraints

- Work on branch `feat/bulk-delete`; main stays deployable. Merge only after `make lint` and `make test-all` pass in-session (exit codes checked directly, never through a pipe).
- Run heavy jobs as `nice -n 10 caffeinate -i make test-all > /tmp/claude-…/test-all.log 2>&1; echo $?`.
- Conventional Commits, scope `conversations` (backend) / `sidebar` (UI); commit trailers per the session's attribution reminder.
- Never write infrastructure details into tracked files or commit messages.
- New env var `CONVERSATIONS_BULK_MAX_IDS` (default `500`): `src/config.py`, `.env.example` (next to `TRASH_RETENTION_DAYS`), `docs/features/ui-features.md`; mirrored in `web/src/config.ts`.
- Do not hand-edit `static/openapi.json` or `web/src/types/generated-api.ts` - `make openapi && make types`.
- Copy: user-menu entry "Select chats"; bar "Cancel" / "N selected" / "Select all" / "Deselect all"; footer "Move N to trash"; toast "Moved N chats to trash." (1 → "Moved 1 chat to trash.") with "Undo"; error "Failed to move chats to trash. Please try again."; restore "Restored N chats." / "Failed to restore chats.".
- No confirm modal on bulk delete.
- Test UI on desktop and mobile (375px wide; breakpoint 768px).

### Spec amendments (applied in Task 3, Step 1)

Found while planning against the code; record them in the spec in the same commit as the API:

1. **Not optimistic.** Single delete removes rows only after the server confirms (`deleteConversation`, `conversation-actions.ts`); bulk delete matches it. The footer button shows "Moving…" and is disabled while the request runs. On failure nothing was removed, so the selection is naturally intact.
2. **`ids` is allowed with `all`.** A pinned chat ticked by hand in select-all mode has to ride in the same request, so in `all` mode `ids` means "also these". Body: `all` (bool, default false), `ids`, `exclude_ids`, `created_before`. Without `all`: `ids` non-empty, no `exclude_ids` / `created_before`. With `all`: `created_before` required.
3. **Undo restores in chunks.** A select-all batch can exceed `CONVERSATIONS_BULK_MAX_IDS`; the client sends `bulk-restore` in chunks of that size, in order.
4. **List `total_count` excludes sports and language chats** (bug: it counted them though the list never shows them). The select-all counter is `total_count - pinned loaded`.
5. **Streaming chat in the batch:** single delete does nothing special for a streaming chat; bulk delete matches it.

## Review Focus

1. **Clock skew on `created_before`.** The client sends `new Date().toISOString()` (UTC); the server stores naive local time. The server must convert an aware timestamp to naive local before comparing, or "select all" trashes nothing (or everything) depending on the server's timezone. Pinned by `test_trash_all_accepts_utc_created_before` (Task 3).
2. **Infinite scroll during select-all.** Rows loaded after "Select all" must render ticked (unless excluded). Pinned by `selection: rows loaded later are selected in all mode` (Task 4) and the E2E select-all case (Task 7).
3. **Undo after an all-mode delete of unloaded chats.** Restored chats not in the local snapshot must come back via sync. Pinned by `restoreConversations: unknown ids trigger an incremental sync` (Task 5).
4. **Double tap on "Move N to trash".** A second click while the request runs must not send a second request. Pinned by `bulkDeleteConversations: ignores a second call while one is running` (Task 5).
5. **The open chat is in the batch.** It must be cleared (welcome screen, hash cleared), as single delete does. Pinned by `bulkDeleteConversations: clears the open chat when it was trashed` (Task 5).

---

### Task 0: Branch

- [ ] **Step 1:** `git switch -c feat/bulk-delete`

---

### Task 1: DB - bulk trash and restore

**Files:**
- Modify: `src/db/models/conversation_trash.py` (add after `restore_conversation`)
- Test: `tests/integration/test_db_conversation_trash.py`

**Interfaces:**
- Produces:
  - `Database.trash_conversations(user_id: str, ids: list[str]) -> list[str]`
  - `Database.trash_all_conversations(user_id: str, exclude_ids: list[str], created_before: datetime, extra_ids: list[str]) -> list[str]`
  - `Database.restore_conversations(user_id: str, ids: list[str]) -> list[str]`
  - All return the ids actually changed (order unspecified). `created_before` is a naive local datetime (conversion is the route's job).

- [ ] **Step 1: Write the failing tests** (append to `tests/integration/test_db_conversation_trash.py`)

```python
def _set_column(db: Database, conv_id: str, column: str, value: object) -> None:
    with db._pool.get_connection() as conn:
        conn.execute(f"UPDATE conversations SET {column} = ? WHERE id = ?", (value, conv_id))
        conn.commit()


class TestBulkTrash:
    def test_trash_conversations_trashes_only_eligible_own_rows(
        self, test_database: Database, test_user: User
    ) -> None:
        other = test_database.get_or_create_user("other@example.com", "Other")
        a = test_database.create_conversation(test_user.id, "A")
        b = test_database.create_conversation(test_user.id, "B")
        agent = test_database.create_conversation(test_user.id, "Agent")
        _set_column(test_database, agent.id, "is_agent", 1)
        foreign = test_database.create_conversation(other.id, "Foreign")

        trashed = test_database.trash_conversations(
            test_user.id, [a.id, b.id, agent.id, foreign.id, "missing"]
        )

        assert sorted(trashed) == sorted([a.id, b.id])
        assert test_database.get_conversation(agent.id, test_user.id) is not None
        assert test_database.get_conversation(foreign.id, other.id) is not None

    def test_trash_conversations_skips_already_trashed(
        self, test_database: Database, test_user: User
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "Once")
        earlier = datetime.now() - timedelta(days=3)
        test_database.trash_conversation(conv.id, test_user.id)
        _set_deleted_at(test_database, conv.id, earlier)

        assert test_database.trash_conversations(test_user.id, [conv.id]) == []
        rows, _, _, _ = test_database.list_trashed_conversations_paginated(test_user.id)
        assert rows[0][0].deleted_at == earlier

    def test_trash_conversations_empty_list_is_noop(
        self, test_database: Database, test_user: User
    ) -> None:
        assert test_database.trash_conversations(test_user.id, []) == []

    def test_trash_all_skips_pinned_archived_excluded_special_and_new(
        self, test_database: Database, test_user: User
    ) -> None:
        cutoff = datetime.now()
        plain = test_database.create_conversation(test_user.id, "Plain")
        excluded = test_database.create_conversation(test_user.id, "Excluded")
        pinned = test_database.create_conversation(test_user.id, "Pinned")
        test_database.set_conversation_pinned(pinned.id, test_user.id, True)
        archived = test_database.create_conversation(test_user.id, "Archived")
        test_database.archive_conversation(archived.id, test_user.id)
        sports = test_database.create_conversation(test_user.id, "Sports")
        _set_column(test_database, sports.id, "is_sports", 1)
        newer = test_database.create_conversation(test_user.id, "Newer")
        for conv in (plain, excluded, pinned, archived, sports):
            _set_column(
                test_database, conv.id, "created_at", (cutoff - timedelta(hours=1)).isoformat()
            )
        _set_column(test_database, newer.id, "created_at", (cutoff + timedelta(hours=1)).isoformat())

        trashed = test_database.trash_all_conversations(
            test_user.id, exclude_ids=[excluded.id], created_before=cutoff, extra_ids=[]
        )

        assert trashed == [plain.id]

    def test_trash_all_includes_hand_picked_pinned(
        self, test_database: Database, test_user: User
    ) -> None:
        cutoff = datetime.now() + timedelta(seconds=1)
        pinned = test_database.create_conversation(test_user.id, "Pinned")
        test_database.set_conversation_pinned(pinned.id, test_user.id, True)

        trashed = test_database.trash_all_conversations(
            test_user.id, exclude_ids=[], created_before=cutoff, extra_ids=[pinned.id]
        )

        assert trashed == [pinned.id]

    def test_trash_all_is_scoped_to_user(self, test_database: Database, test_user: User) -> None:
        other = test_database.get_or_create_user("other@example.com", "Other")
        foreign = test_database.create_conversation(other.id, "Foreign")
        cutoff = datetime.now() + timedelta(seconds=1)

        assert (
            test_database.trash_all_conversations(
                test_user.id, exclude_ids=[], created_before=cutoff, extra_ids=[foreign.id]
            )
            == []
        )


class TestBulkRestore:
    def test_restore_conversations_returns_only_trashed_own_rows(
        self, test_database: Database, test_user: User
    ) -> None:
        other = test_database.get_or_create_user("other@example.com", "Other")
        trashed = test_database.create_conversation(test_user.id, "Trashed")
        live = test_database.create_conversation(test_user.id, "Live")
        foreign = test_database.create_conversation(other.id, "Foreign")
        test_database.trash_conversation(trashed.id, test_user.id)
        test_database.trash_conversation(foreign.id, other.id)

        restored = test_database.restore_conversations(
            test_user.id, [trashed.id, live.id, foreign.id]
        )

        assert restored == [trashed.id]
        assert test_database.get_conversation(trashed.id, test_user.id) is not None
        assert test_database.get_conversation(foreign.id, other.id) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/integration/test_db_conversation_trash.py -k "Bulk" -v > $SCRATCH/t1.log 2>&1; echo $?`
Expected: non-zero; `AttributeError: 'Database' object has no attribute 'trash_conversations'`.

- [ ] **Step 3: Implement** (in `conversation_trash.py`; add the constant near `_TRASH_LIST_SELECT`, methods after `restore_conversation`)

```python
# Rows the chat list shows and bulk delete may trash: regular, live chats.
# Agent / planner / sports / language chats are owned by their feature.
_TRASHABLE_WHERE = """user_id = ? AND deleted_at IS NULL
    AND (is_agent = 0 OR is_agent IS NULL)
    AND (is_planning = 0 OR is_planning IS NULL)
    AND (is_sports = 0 OR is_sports IS NULL)
    AND (is_language = 0 OR is_language IS NULL)"""


def _placeholders(values: list[str]) -> str:
    return ",".join("?" * len(values))
```

```python
    def trash_conversations(self, user_id: str, ids: list[str]) -> list[str]:
        """Move the eligible rows among ids to the trash; returns the ids trashed."""
        if not ids:
            return []
        where = f"{_TRASHABLE_WHERE} AND id IN ({_placeholders(ids)})"
        return self._trash_where(where, (user_id, *ids))

    def trash_all_conversations(
        self,
        user_id: str,
        exclude_ids: list[str],
        created_before: datetime,
        extra_ids: list[str],
    ) -> list[str]:
        """Trash every unpinned main-list chat created before created_before,
        except exclude_ids, plus the eligible extra_ids (pinned chats picked by
        hand). created_before stops a chat started on another device after the
        user pressed Select all from being swept up."""
        all_set = f"""(pinned = 0 OR pinned IS NULL) AND (archived = 0 OR archived IS NULL)
            AND created_at < ? AND id NOT IN ({_placeholders(exclude_ids)})"""
        where = f"{_TRASHABLE_WHERE} AND (({all_set}) OR id IN ({_placeholders(extra_ids)}))"
        params = (user_id, created_before.isoformat(), *exclude_ids, *extra_ids)
        return self._trash_where(where, params)

    def restore_conversations(self, user_id: str, ids: list[str]) -> list[str]:
        """Take the user's trashed rows among ids out of the trash; returns them."""
        if not ids:
            return []
        now = datetime.now().isoformat()
        where = f"user_id = ? AND deleted_at IS NOT NULL AND id IN ({_placeholders(ids)})"
        return self._update_where(
            where, (user_id, *ids), "deleted_at = NULL, updated_at = ?", (now,)
        )

    def _trash_where(self, where: str, params: tuple[Any, ...]) -> list[str]:
        now = datetime.now().isoformat()
        return self._update_where(where, params, "deleted_at = ?, updated_at = ?", (now, now))

    def _update_where(
        self,
        where: str,
        params: tuple[Any, ...],
        set_clause: str,
        set_params: tuple[Any, ...],
    ) -> list[str]:
        """SELECT the matching ids, then UPDATE the same rows, under one write
        lock (BEGIN IMMEDIATE) so a concurrent change cannot slip between."""
        with self._pool.get_connection() as conn:
            self._execute_with_timing(conn, "BEGIN IMMEDIATE")
            try:
                rows = self._execute_with_timing(
                    conn, f"SELECT id FROM conversations WHERE {where}", params
                ).fetchall()
                if rows:
                    self._execute_with_timing(
                        conn,
                        f"UPDATE conversations SET {set_clause} WHERE {where}",
                        (*set_params, *params),
                    )
            except BaseException:
                conn.rollback()
                raise
            conn.commit()
        return [row["id"] for row in rows]
```

Note: `id NOT IN ()` / `id IN ()` with an empty list is valid SQLite (false / true for NOT IN), so empty `exclude_ids` / `extra_ids` need no special case. The new sync change log is row-trigger fed, so these updates reach other devices.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/integration/test_db_conversation_trash.py tests/integration/test_db_sync_changes.py -v > $SCRATCH/t1.log 2>&1; echo $?` → `0`.

- [ ] **Step 5: Add a sync test** (append to `tests/integration/test_db_sync_changes.py`, following that file's existing helpers for reading changes since a cursor) asserting that after `trash_conversations(user, [a, b])` both ids appear in the change feed with `trashed=True`, and after `restore_conversations` with `trashed=False`. Run it; expected pass (triggers already exist). If it fails, stop and report - the spec's "no sync changes" assumption is wrong.

- [ ] **Step 6: Commit**

```bash
git add src/db/models/conversation_trash.py tests/integration/test_db_conversation_trash.py tests/integration/test_db_sync_changes.py
git commit -m "feat(conversations): bulk trash and restore in the DB layer"
```

---

### Task 2: Fix - list `total_count` counts sports and language chats

**Files:**
- Modify: `src/db/models/conversation_listing.py` (both `SELECT COUNT(*)` total queries, ~lines 60 and 140)
- Test: `tests/integration/test_routes_pagination.py`

- [ ] **Step 1: Write the failing test**

```python
def test_total_count_excludes_sports_and_language(
    client: FlaskClient, auth_headers: dict[str, str], test_database: Database, test_user: User
) -> None:
    test_database.create_conversation(test_user.id, "Plain")
    for column in ("is_sports", "is_language"):
        conv = test_database.create_conversation(test_user.id, column)
        with test_database._pool.get_connection() as conn:
            conn.execute(f"UPDATE conversations SET {column} = 1 WHERE id = ?", (conv.id,))
            conn.commit()

    data = client.get("/api/conversations", headers=auth_headers).get_json()

    assert [c["title"] for c in data["conversations"]] == ["Plain"]
    assert data["pagination"]["total_count"] == 1
```

(Match the file's existing import block and fixture names; put it in the class that tests `/api/conversations` pagination if there is one.)

- [ ] **Step 2:** Run `.venv/bin/pytest tests/integration/test_routes_pagination.py -k total_count_excludes -v > $SCRATCH/t2.log 2>&1; echo $?` → non-zero, `assert 3 == 1`.

- [ ] **Step 3: Fix** - add to both total-count queries in `conversation_listing.py`:

```sql
                     AND (is_sports = 0 OR is_sports IS NULL)
                     AND (is_language = 0 OR is_language IS NULL)
```

and update both docstring lines to "Total number of conversations the list shows".

- [ ] **Step 4:** Re-run `tests/integration/test_routes_pagination.py tests/integration/test_routes_conversations.py` → exit `0`.

- [ ] **Step 5: Commit** `fix(conversations): list total_count no longer counts sports and language chats`

---

### Task 3: API - schemas, routes, config

**Files:**
- Modify: `docs/superpowers/specs/2026-10-13-bulk-delete-conversations-design.md` (amendments)
- Modify: `src/config.py` (next to `TRASH_RETENTION_DAYS`, line ~270), `.env.example` (after `TRASH_RETENTION_DAYS=14`)
- Modify: `src/api/schemas/conversations.py` (after `EmptyTrashResponse`)
- Modify: `src/api/routes/conversation_trash.py`
- Regenerate: `static/openapi.json`, `web/src/types/generated-api.ts`
- Test: `tests/integration/test_routes_conversation_trash.py`, `tests/integration/test_openapi.py`

**Interfaces:**
- Consumes: Task 1 DB methods.
- Produces (HTTP):
  - `POST /api/conversations/bulk-trash` body `BulkTrashRequest` → `{"trashed_ids": [...]}`
  - `POST /api/conversations/bulk-restore` body `{"ids": [...]}` → `{"restored_ids": [...]}`

- [ ] **Step 1: Amend the spec.** In the spec: under *Status* add "Amended Oct 13 2026 during planning: see Amendments."; add an `## Amendments` section copying the five items from this plan's "Spec amendments"; update the `bulk-trash` request bodies and the *Deleting* / *Failure* UX paragraphs to match (not optimistic; `ids` allowed with `all`).

- [ ] **Step 2: Config**

```python
    # Most ids one bulk trash / restore request may carry (bulk delete in the sidebar)
    CONVERSATIONS_BULK_MAX_IDS: int = int(os.getenv("CONVERSATIONS_BULK_MAX_IDS", "500"))
```

`.env.example`:

```
# Most conversation ids one bulk trash / restore request may carry
CONVERSATIONS_BULK_MAX_IDS=500
```

- [ ] **Step 3: Write the failing route tests** (append to `tests/integration/test_routes_conversation_trash.py`)

```python
class TestBulkTrashRoutes:
    def test_bulk_trash_ids(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        a = test_database.create_conversation(test_user.id, "A")
        b = test_database.create_conversation(test_user.id, "B")
        keep = test_database.create_conversation(test_user.id, "Keep")

        response = client.post(
            "/api/conversations/bulk-trash", json={"ids": [a.id, b.id]}, headers=auth_headers
        )

        assert response.status_code == 200
        assert sorted(response.get_json()["trashed_ids"]) == sorted([a.id, b.id])
        listed = client.get("/api/conversations", headers=auth_headers).get_json()
        assert [c["id"] for c in listed["conversations"]] == [keep.id]

    def test_bulk_trash_all_with_exclusions(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        a = test_database.create_conversation(test_user.id, "A")
        keep = test_database.create_conversation(test_user.id, "Keep")
        body = {
            "all": True,
            "exclude_ids": [keep.id],
            "created_before": (datetime.now() + timedelta(seconds=5)).isoformat(),
        }

        response = client.post("/api/conversations/bulk-trash", json=body, headers=auth_headers)

        assert response.get_json() == {"trashed_ids": [a.id]}

    def test_trash_all_accepts_utc_created_before(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        # The browser sends toISOString() (UTC, "Z"); the DB stores naive local time
        conv = test_database.create_conversation(test_user.id, "A")
        utc_now = datetime.now(UTC) + timedelta(seconds=5)
        body = {"all": True, "created_before": utc_now.isoformat().replace("+00:00", "Z")}

        response = client.post("/api/conversations/bulk-trash", json=body, headers=auth_headers)

        assert response.get_json() == {"trashed_ids": [conv.id]}

    def test_bulk_trash_rejects_bad_shapes(
        self, client: FlaskClient, auth_headers: dict[str, str]
    ) -> None:
        url = "/api/conversations/bulk-trash"
        too_many = [f"id-{i}" for i in range(Config.CONVERSATIONS_BULK_MAX_IDS + 1)]
        for body in (
            {},
            {"ids": []},
            {"all": True},
            {"ids": ["a"], "exclude_ids": ["b"]},
            {"ids": ["a"], "created_before": "2026-01-01T00:00:00"},
            {"ids": too_many},
        ):
            response = client.post(url, json=body, headers=auth_headers)
            assert response.status_code == 400, body

    def test_bulk_restore(
        self,
        client: FlaskClient,
        auth_headers: dict[str, str],
        test_database: Database,
        test_user: User,
    ) -> None:
        conv = test_database.create_conversation(test_user.id, "A")
        test_database.trash_conversation(conv.id, test_user.id)

        response = client.post(
            "/api/conversations/bulk-restore", json={"ids": [conv.id]}, headers=auth_headers
        )

        assert response.get_json() == {"restored_ids": [conv.id]}
        assert client.get(f"/api/conversations/{conv.id}", headers=auth_headers).status_code == 200

    def test_bulk_routes_require_auth(self, client: FlaskClient) -> None:
        assert client.post("/api/conversations/bulk-trash", json={"ids": ["a"]}).status_code == 401
        assert client.post("/api/conversations/bulk-restore", json={"ids": ["a"]}).status_code == 401
```

Add to the file's imports: `from datetime import UTC, datetime, timedelta` and `from src.config import Config`. Add to `test_spec_has_all_paths` in `tests/integration/test_openapi.py`:

```python
        assert "/api/conversations/bulk-trash" in paths
        assert "/api/conversations/bulk-restore" in paths
```

- [ ] **Step 4:** Run `.venv/bin/pytest tests/integration/test_routes_conversation_trash.py tests/integration/test_openapi.py -v > $SCRATCH/t3.log 2>&1; echo $?` → non-zero (404s on the new routes).

- [ ] **Step 5: Schemas** (`src/api/schemas/conversations.py`; add `datetime` and `model_validator` imports, `from __future__ import annotations` already? - follow the file; import `Config` from `src.config` if not present)

```python
class BulkTrashRequest(BaseModel):
    """Move many conversations to the trash: hand-picked ids, or every
    unpinned main-list chat (all) minus exclude_ids plus ids."""

    all: bool = Field(default=False, description="Every unpinned main-list chat")
    ids: list[str] = Field(
        default_factory=list,
        max_length=Config.CONVERSATIONS_BULK_MAX_IDS,
        description="Chats to trash; with all, extra chats (pinned ones picked by hand)",
    )
    exclude_ids: list[str] = Field(
        default_factory=list,
        max_length=Config.CONVERSATIONS_BULK_MAX_IDS,
        description="With all: chats to keep",
    )
    created_before: datetime | None = Field(
        default=None, description="With all: only chats created before this moment"
    )

    @model_validator(mode="after")
    def validate_shape(self) -> BulkTrashRequest:
        """ids alone, or all with created_before."""
        if self.all:
            if self.created_before is None:
                raise ValueError("created_before is required with all")
            return self
        if not self.ids:
            raise ValueError("ids or all is required")
        if self.exclude_ids or self.created_before is not None:
            raise ValueError("exclude_ids and created_before need all")
        return self


class BulkTrashResponse(BaseModel):
    """Result of a bulk trash."""

    trashed_ids: list[str] = Field(..., description="Conversations this call moved to the trash")


class BulkRestoreRequest(BaseModel):
    """Restore many conversations from the trash (Undo of a bulk delete)."""

    ids: list[str] = Field(..., min_length=1, max_length=Config.CONVERSATIONS_BULK_MAX_IDS)


class BulkRestoreResponse(BaseModel):
    """Result of a bulk restore."""

    restored_ids: list[str] = Field(..., description="Conversations this call restored")
```

- [ ] **Step 6: Routes** (`src/api/routes/conversation_trash.py`; import the four schemas and `validate_request` from `src.api.validation`; update the module docstring's first line to "Conversation trash routes: list, restore, permanent delete, empty, bulk trash/restore.")

```python
def _naive_local(moment: datetime) -> datetime:
    """Conversation timestamps are stored as naive local time (datetime.now());
    the browser sends UTC. Compare like with like."""
    if moment.tzinfo is None:
        return moment
    return moment.astimezone().replace(tzinfo=None)


@api.route("/conversations/bulk-trash", methods=["POST"])
@api.output(BulkTrashResponse)
@api.doc(responses=[400, 429])
@rate_limit_conversations
@require_auth
@validate_request(BulkTrashRequest)
def bulk_trash_conversations(user: User, data: BulkTrashRequest) -> dict[str, list[str]]:
    """Move many conversations to the trash in one transaction (bulk delete)."""
    # The schema guarantees created_before with all; the check narrows the type
    if data.all and data.created_before is not None:
        trashed = db.trash_all_conversations(
            user.id,
            exclude_ids=data.exclude_ids,
            created_before=_naive_local(data.created_before),
            extra_ids=data.ids,
        )
    else:
        trashed = db.trash_conversations(user.id, data.ids)
    logger.info(
        "Conversations bulk trashed",
        extra={"user_id": user.id, "count": len(trashed), "mode": "all" if data.all else "ids"},
    )
    return {"trashed_ids": trashed}


@api.route("/conversations/bulk-restore", methods=["POST"])
@api.output(BulkRestoreResponse)
@api.doc(responses=[400, 429])
@rate_limit_conversations
@require_auth
@validate_request(BulkRestoreRequest)
def bulk_restore_conversations(user: User, data: BulkRestoreRequest) -> dict[str, list[str]]:
    """Restore many conversations from the trash (Undo of a bulk delete)."""
    restored = db.restore_conversations(user.id, data.ids)
    logger.info(
        "Conversations bulk restored",
        extra={"user_id": user.id, "count": len(restored), "mode": "restore"},
    )
    return {"restored_ids": restored}
```

Check: the static `/conversations/bulk-trash` path must not be captured by a `<conv_id>` route. Both are POST and no `POST /conversations/<conv_id>` exists, so it can't be; the test in Step 3 confirms it.

- [ ] **Step 7:** Re-run Step 4's command → `0`. Then `make openapi > $SCRATCH/oa.log 2>&1; echo $?` and `make types > $SCRATCH/ty.log 2>&1; echo $?` → both `0`; `git diff --stat static/openapi.json web/src/types/generated-api.ts` shows the new paths.

- [ ] **Step 8: Commit** spec, config, `.env.example`, schemas, routes, tests, generated files: `feat(conversations): bulk trash and restore endpoints`

---

### Task 4: Frontend - API client and selection slice

**Files:**
- Modify: `web/src/config.ts` (after `TRASH_RETENTION_DAYS`)
- Modify: `web/src/api/conversations.ts` (after `emptyTrash`)
- Modify: `web/src/types/api.ts` (hand-written request type, next to other `*Request` interfaces)
- Create: `web/src/state/slices/selection.ts`
- Modify: `web/src/state/store.ts`, `web/src/state/slices/auth.ts` (logout reset)
- Test: `web/tests/unit/selection.test.ts`

**Interfaces:**
- Produces:
  - `CONVERSATIONS_BULK_MAX_IDS: number` (config.ts)
  - `interface BulkTrashRequest { all?: boolean; ids?: string[]; exclude_ids?: string[]; created_before?: string }` (types/api.ts)
  - `conversations.bulkTrash(body: BulkTrashRequest): Promise<string[]>` and `conversations.bulkRestore(ids: string[]): Promise<string[]>`
  - Slice state: `isSelecting: boolean`, `selectionMode: 'ids' | 'all'`, `selectedIds: Set<string>`, `excludedIds: Set<string>`, `selectAllCreatedBefore: string | null`, `isBulkDeleting: boolean`
  - Slice actions: `startSelection(): void`, `endSelection(): void`, `toggleSelected(conv: Pick<Conversation, 'id' | 'pinned'>): void`, `selectAll(createdBefore: string): void`, `deselectAll(): void`, `setBulkDeleting(busy: boolean): void`
  - Pure selectors (exported from `selection.ts`): `isConversationSelected(state: AppState, conv: Pick<Conversation, 'id' | 'pinned'>): boolean`, `selectedCount(state: AppState): number`, `buildBulkTrashRequest(state: AppState): BulkTrashRequest | null` (null when nothing on the server is selected), `selectedLoadedIds(state: AppState): string[]`

- [ ] **Step 1: Write the failing tests** (`web/tests/unit/selection.test.ts`)

```ts
/**
 * Selection slice: picking chats for bulk delete, select-all with
 * exclusions, the counter, and the request it builds.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '@/state/store';
import {
  buildBulkTrashRequest,
  isConversationSelected,
  selectedCount,
  selectedLoadedIds,
} from '@/state/slices/selection';
import type { Conversation } from '@/types/api';

function conv(id: string, extra: Partial<Conversation> = {}): Conversation {
  return { id, title: id, model: 'm', created_at: '', updated_at: '2026-01-01T00:00:00Z', ...extra };
}

const s = () => useStore.getState();

beforeEach(() => {
  useStore.setState({
    conversations: [conv('p', { pinned: true }), conv('a'), conv('b'), conv('temp-1')],
    conversationsPagination: { nextCursor: 'x', hasMore: true, totalCount: 10, isLoadingMore: false },
  });
  s().endSelection();
});

describe('selection', () => {
  it('toggles hand-picked rows and counts them', () => {
    s().startSelection();
    s().toggleSelected(conv('a'));
    s().toggleSelected(conv('b'));
    s().toggleSelected(conv('b'));

    expect(isConversationSelected(s(), conv('a'))).toBe(true);
    expect(isConversationSelected(s(), conv('b'))).toBe(false);
    expect(selectedCount(s())).toBe(1);
    expect(buildBulkTrashRequest(s())).toEqual({ ids: ['a'] });
  });

  it('leaves temp chats out of the request', () => {
    s().startSelection();
    s().toggleSelected(conv('temp-1'));

    expect(buildBulkTrashRequest(s())).toBeNull();
    expect(selectedLoadedIds(s())).toEqual(['temp-1']);
  });

  it('select all covers unpinned chats, counts the server total, and honours exclusions', () => {
    s().startSelection();
    s().selectAll('2026-10-13T10:00:00.000Z');
    s().toggleSelected(conv('a'));

    expect(isConversationSelected(s(), conv('p', { pinned: true }))).toBe(false);
    expect(isConversationSelected(s(), conv('a'))).toBe(false);
    expect(isConversationSelected(s(), conv('b'))).toBe(true);
    // 10 total - 1 pinned - 1 excluded
    expect(selectedCount(s())).toBe(8);
    expect(buildBulkTrashRequest(s())).toEqual({
      all: true,
      ids: [],
      exclude_ids: ['a'],
      created_before: '2026-10-13T10:00:00.000Z',
    });
  });

  it('a pinned chat ticked in select-all mode rides along in ids', () => {
    s().startSelection();
    s().selectAll('2026-10-13T10:00:00.000Z');
    s().toggleSelected(conv('p', { pinned: true }));

    expect(selectedCount(s())).toBe(10);
    expect(buildBulkTrashRequest(s())?.ids).toEqual(['p']);
  });

  it('rows loaded later are selected in all mode', () => {
    s().startSelection();
    s().selectAll('2026-10-13T10:00:00.000Z');
    useStore.setState({ conversations: [...s().conversations, conv('late')] });

    expect(isConversationSelected(s(), conv('late'))).toBe(true);
  });

  it('deselect all and end clear everything', () => {
    s().startSelection();
    s().selectAll('2026-10-13T10:00:00.000Z');
    s().deselectAll();
    expect(selectedCount(s())).toBe(0);
    expect(s().selectionMode).toBe('ids');

    s().toggleSelected(conv('a'));
    s().endSelection();
    expect(s().isSelecting).toBe(false);
    expect(s().selectedIds.size).toBe(0);
  });
});
```

- [ ] **Step 2:** `cd web && npx vitest run tests/unit/selection.test.ts > $SCRATCH/t4.log 2>&1; echo $?` → non-zero (module not found).

- [ ] **Step 3: Implement**

`web/src/config.ts`:

```ts
/** Most ids one bulk trash / restore request may carry (mirrors the server's CONVERSATIONS_BULK_MAX_IDS default) */
export const CONVERSATIONS_BULK_MAX_IDS = 500;
```

`web/src/types/api.ts`:

```ts
/** POST /api/conversations/bulk-trash: hand-picked ids, or all (minus exclude_ids, plus ids) */
export interface BulkTrashRequest {
  all?: boolean;
  ids?: string[];
  exclude_ids?: string[];
  created_before?: string;
}
```

`web/src/api/conversations.ts` (import `type BulkTrashRequest`):

```ts
  async bulkTrash(body: BulkTrashRequest): Promise<string[]> {
    // Idempotent server-side (already-trashed rows are skipped), safe to retry
    const data = await request<{ trashed_ids: string[] }>('/api/conversations/bulk-trash', {
      method: 'POST',
      body: JSON.stringify(body),
      retry: true,
    });
    return data.trashed_ids;
  },

  async bulkRestore(ids: string[]): Promise<string[]> {
    // Idempotent server-side (live rows are skipped), safe to retry
    const data = await request<{ restored_ids: string[] }>('/api/conversations/bulk-restore', {
      method: 'POST',
      body: JSON.stringify({ ids }),
      retry: true,
    });
    return data.restored_ids;
  },
```

Note on retry: a retried `bulkTrash` after a lost response returns `[]` for already-trashed rows. Acceptable - the rows are trashed; Task 5 handles an empty result by reloading the list (see its Step 3).

`web/src/state/slices/selection.ts`:

```ts
import type { BulkTrashRequest, Conversation } from '../../types/api';
import type { AppSlice, AppState } from '../store';
import { isTempConversation } from '../../core/conversation';

export type SelectionMode = 'ids' | 'all';

/**
 * Sidebar selection for bulk delete. In 'ids' mode selectedIds are the
 * picked chats. In 'all' mode every unpinned chat counts as selected
 * (also pages not loaded yet) except excludedIds, and selectedIds holds
 * pinned chats picked by hand.
 */
export interface SelectionData {
  isSelecting: boolean;
  selectionMode: SelectionMode;
  selectedIds: Set<string>;
  excludedIds: Set<string>;
  selectAllCreatedBefore: string | null;
  isBulkDeleting: boolean;
}

export interface SelectionSlice extends SelectionData {
  startSelection: () => void;
  endSelection: () => void;
  toggleSelected: (conv: Pick<Conversation, 'id' | 'pinned'>) => void;
  selectAll: (createdBefore: string) => void;
  deselectAll: () => void;
  setBulkDeleting: (busy: boolean) => void;
}

/** Initial selection state; also what logout resets to. */
export function initialSelectionData(): SelectionData {
  return {
    isSelecting: false,
    selectionMode: 'ids',
    selectedIds: new Set(),
    excludedIds: new Set(),
    selectAllCreatedBefore: null,
    isBulkDeleting: false,
  };
}

function toggled(set: Set<string>, id: string): Set<string> {
  const next = new Set(set);
  if (!next.delete(id)) next.add(id);
  return next;
}

export const createSelectionSlice: AppSlice<SelectionSlice> = (set) => ({
  ...initialSelectionData(),

  startSelection: () => set({ ...initialSelectionData(), isSelecting: true }),
  endSelection: () => set(initialSelectionData()),
  toggleSelected: (conv) =>
    set((state) =>
      state.selectionMode === 'all' && !conv.pinned
        ? { excludedIds: toggled(state.excludedIds, conv.id) }
        : { selectedIds: toggled(state.selectedIds, conv.id) }
    ),
  selectAll: (createdBefore) =>
    set({
      selectionMode: 'all',
      selectedIds: new Set(),
      excludedIds: new Set(),
      selectAllCreatedBefore: createdBefore,
    }),
  deselectAll: () =>
    set({ selectionMode: 'ids', selectedIds: new Set(), excludedIds: new Set(), selectAllCreatedBefore: null }),
  setBulkDeleting: (isBulkDeleting) => set({ isBulkDeleting }),
});

export function isConversationSelected(
  state: AppState,
  conv: Pick<Conversation, 'id' | 'pinned'>
): boolean {
  if (state.selectionMode === 'all' && !conv.pinned) return !state.excludedIds.has(conv.id);
  return state.selectedIds.has(conv.id);
}

/** "N selected": in 'all' mode the server's list total (pinned included) minus pinned, exclusions. */
export function selectedCount(state: AppState): number {
  if (state.selectionMode === 'ids') return state.selectedIds.size;
  const pinned = state.conversations.filter((c) => c.pinned).length;
  const unpinnedTotal = Math.max(0, state.conversationsPagination.totalCount - pinned);
  return Math.max(0, unpinnedTotal - state.excludedIds.size) + state.selectedIds.size;
}

/** Selected chats among the loaded rows (for local removal and noteLocalChange). */
export function selectedLoadedIds(state: AppState): string[] {
  return state.conversations.filter((c) => isConversationSelected(state, c)).map((c) => c.id);
}

/** The bulk-trash body, or null when nothing on the server is selected. */
export function buildBulkTrashRequest(state: AppState): BulkTrashRequest | null {
  const serverIds = (ids: Set<string>) => [...ids].filter((id) => !isTempConversation(id));
  if (state.selectionMode === 'all' && state.selectAllCreatedBefore) {
    return {
      all: true,
      ids: serverIds(state.selectedIds),
      exclude_ids: serverIds(state.excludedIds),
      created_before: state.selectAllCreatedBefore,
    };
  }
  const ids = serverIds(state.selectedIds);
  return ids.length ? { ids } : null;
}
```

If importing `isTempConversation` from `core/conversation` creates an import cycle the linter or tests flag (slices normally don't import from core), move the one-liner `id.startsWith('temp-')` check into `selection.ts` with a comment pointing at `isTempConversation`, rather than restructuring.

`web/src/state/store.ts`: import `createSelectionSlice, type SelectionSlice`, add `SelectionSlice &` to `AppState`, `...createSelectionSlice(...a),` to the creator list. `web/src/state/slices/auth.ts`: import `initialSelectionData` and add `...initialSelectionData(),` to the logout reset.

- [ ] **Step 4:** Re-run Step 2 → `0`. Run `cd web && npx tsc --noEmit > $SCRATCH/tsc.log 2>&1; echo $?` → `0`.

- [ ] **Step 5: Commit** `feat(sidebar): selection state and bulk trash API client`

---

### Task 5: Frontend - bulk delete and bulk restore actions

**Files:**
- Modify: `web/src/core/conversation-actions.ts`
- Modify: `web/src/core/trash.ts`
- Test: `web/tests/unit/bulk-delete.test.ts`

**Interfaces:**
- Consumes: Task 4 slice, selectors, `conversations.bulkTrash` / `bulkRestore`, `CONVERSATIONS_BULK_MAX_IDS`.
- Produces:
  - `removeConversationsFromUI(ids: string[]): void` (conversation-actions.ts; `removeConversationFromUI(id)` becomes `removeConversationsFromUI([id])`)
  - `bulkDeleteConversations(): Promise<void>` (conversation-actions.ts) - reads the selection from the store, ends selection mode on success
  - `restoreConversations(ids: string[], snapshot: Conversation[]): Promise<void>` (trash.ts)
  - Calls `renderSelectionChrome()` from `components/SidebarSelection` (created in Task 6). In this task, create `web/src/components/SidebarSelection.ts` with only `export function renderSelectionChrome(): void {}` and a header comment; Task 6 fills it in.

- [ ] **Step 1: Write the failing tests** (`web/tests/unit/bulk-delete.test.ts`; mock setup copied from `trash-actions.test.ts`)

```ts
/**
 * Bulk delete: one request, rows leave after the server confirms, one Undo.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import type { Conversation } from '@/types/api';

const api = vi.hoisted(() => ({
  bulkTrash: vi.fn(),
  bulkRestore: vi.fn(),
  listTrash: vi.fn(),
}));
const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
const syncMock = vi.hoisted(() => ({ noteLocalChange: vi.fn(), incrementalSync: vi.fn() }));

vi.mock('@/api/conversations', () => ({ conversations: api, messages: {} }));
vi.mock('@/components/Toast', () => ({ toast: toastMock }));
vi.mock('@/components/Modal', () => ({ showConfirm: vi.fn(), showPrompt: vi.fn() }));
vi.mock('@/sync/SyncManager', () => ({ getSyncManager: () => syncMock }));
vi.mock('@/components/Sidebar', () => ({
  renderConversationsList: vi.fn(),
  loadArchivedConversations: vi.fn(),
  cleanupArchiveInfiniteScroll: vi.fn(),
}));
vi.mock('@/components/SidebarSelection', () => ({ renderSelectionChrome: vi.fn() }));
vi.mock('@/components/messages', () => ({ renderMessages: vi.fn(), updateChatTitle: vi.fn() }));
vi.mock('@/components/ChatHeader', () => ({ renderChatHeader: vi.fn() }));
vi.mock('@/core/toolbar', () => ({ updateConversationCost: vi.fn() }));
vi.mock('@/router/deeplink', () => ({
  clearConversationHash: vi.fn(),
  setTrashHash: vi.fn(),
  setConversationHash: vi.fn(),
  setArchiveHash: vi.fn(),
}));

import { bulkDeleteConversations } from '@/core/conversation-actions';
import { restoreConversations } from '@/core/trash';
import { clearConversationHash } from '@/router/deeplink';

function conv(id: string, extra: Partial<Conversation> = {}): Conversation {
  return { id, title: id, model: 'm', created_at: '', updated_at: '2026-01-01T00:00:00Z', ...extra };
}
const emptyPagination = { nextCursor: null, hasMore: false, totalCount: 0, isLoadingMore: false };
const s = () => useStore.getState();

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({
    conversations: [conv('a'), conv('b'), conv('c')],
    conversationsPagination: { ...emptyPagination, totalCount: 3 },
    trashedConversations: [],
    trashPagination: { ...emptyPagination },
    currentConversation: null,
  });
  s().endSelection();
  api.listTrash.mockResolvedValue({ conversations: [], pagination: { next_cursor: null, has_more: false, total_count: 0 } });
});

function pick(...ids: string[]): void {
  s().startSelection();
  ids.forEach((id) => s().toggleSelected(conv(id)));
}

describe('bulkDeleteConversations', () => {
  it('trashes the picked rows with one request, no confirm, and offers one Undo', async () => {
    api.bulkTrash.mockResolvedValue(['a', 'b']);
    pick('a', 'b');

    await bulkDeleteConversations();

    expect(api.bulkTrash).toHaveBeenCalledTimes(1);
    expect(api.bulkTrash).toHaveBeenCalledWith({ ids: ['a', 'b'] });
    expect(s().conversations.map((c) => c.id)).toEqual(['c']);
    expect(s().isSelecting).toBe(false);
    expect(syncMock.noteLocalChange).toHaveBeenCalledWith('a');
    expect(toastMock.success).toHaveBeenCalledWith(
      'Moved 2 chats to trash.',
      expect.objectContaining({ action: expect.objectContaining({ label: 'Undo' }) })
    );
  });

  it('keeps rows and selection on failure', async () => {
    api.bulkTrash.mockRejectedValue(new Error('boom'));
    pick('a');

    await bulkDeleteConversations();

    expect(s().conversations).toHaveLength(3);
    expect(s().isSelecting).toBe(true);
    expect(s().selectedIds.has('a')).toBe(true);
    expect(s().isBulkDeleting).toBe(false);
    expect(toastMock.error).toHaveBeenCalledWith('Failed to move chats to trash. Please try again.');
  });

  it('ignores a second call while one is running', async () => {
    let resolve: (ids: string[]) => void = () => {};
    api.bulkTrash.mockReturnValue(new Promise<string[]>((r) => (resolve = r)));
    pick('a');

    const first = bulkDeleteConversations();
    await bulkDeleteConversations();
    resolve(['a']);
    await first;

    expect(api.bulkTrash).toHaveBeenCalledTimes(1);
  });

  it('clears the open chat when it was trashed', async () => {
    api.bulkTrash.mockResolvedValue(['a']);
    useStore.setState({ currentConversation: conv('a') });
    pick('a');

    await bulkDeleteConversations();

    expect(s().currentConversation).toBeNull();
    expect(clearConversationHash).toHaveBeenCalled();
  });

  it('removes temp chats locally without a request', async () => {
    useStore.setState({ conversations: [conv('temp-1'), conv('a')] });
    pick('temp-1');

    await bulkDeleteConversations();

    expect(api.bulkTrash).not.toHaveBeenCalled();
    expect(s().conversations.map((c) => c.id)).toEqual(['a']);
    expect(s().isSelecting).toBe(false);
  });

  it('says "1 chat" for one', async () => {
    api.bulkTrash.mockResolvedValue(['a']);
    pick('a');

    await bulkDeleteConversations();

    expect(toastMock.success).toHaveBeenCalledWith('Moved 1 chat to trash.', expect.anything());
  });
});

describe('restoreConversations', () => {
  it('restores in one call and puts the rows back', async () => {
    api.bulkRestore.mockResolvedValue(['a', 'b']);

    await restoreConversations(['a', 'b'], [conv('a'), conv('b')]);

    expect(api.bulkRestore).toHaveBeenCalledWith(['a', 'b']);
    expect(s().conversations.map((c) => c.id).sort()).toEqual(['a', 'b', 'c']);
    expect(toastMock.success).toHaveBeenCalledWith('Restored 2 chats.');
  });

  it('chunks to the bulk cap', async () => {
    const ids = Array.from({ length: 501 }, (_, i) => `x${i}`);
    api.bulkRestore.mockImplementation(async (chunk: string[]) => chunk);

    await restoreConversations(ids, []);

    expect(api.bulkRestore).toHaveBeenCalledTimes(2);
    expect(api.bulkRestore.mock.calls[0][0]).toHaveLength(500);
    expect(api.bulkRestore.mock.calls[1][0]).toEqual(['x500']);
  });

  it('unknown ids trigger an incremental sync', async () => {
    api.bulkRestore.mockResolvedValue(['unloaded']);

    await restoreConversations(['unloaded'], []);

    expect(syncMock.incrementalSync).toHaveBeenCalled();
  });

  it('reports failure', async () => {
    api.bulkRestore.mockRejectedValue(new Error('boom'));

    await restoreConversations(['a'], [conv('a')]);

    expect(toastMock.error).toHaveBeenCalledWith('Failed to restore chats.');
  });
});
```

- [ ] **Step 2:** `cd web && npx vitest run tests/unit/bulk-delete.test.ts > $SCRATCH/t5.log 2>&1; echo $?` → non-zero.

- [ ] **Step 3: Implement**

`conversation-actions.ts` - replace `removeConversationFromUI` with:

```ts
/**
 * Remove conversations from the UI; clears the open chat if it was one of them.
 */
export function removeConversationsFromUI(ids: string[]): void {
  const store = useStore.getState();
  ids.forEach((id) => store.removeConversation(id));
  renderConversationsList();

  const currentId = store.currentConversation?.id;
  if (currentId && ids.includes(currentId)) {
    store.setCurrentConversation(null);
    renderMessages([]);
    updateChatTitle(APP_NAME);
    renderChatHeader(null);
    // The mobile cost chip lives in the persistent mobile header (not the
    // re-rendered chat header) - clear it or the deleted conversation's
    // cost lingers on the welcome screen
    void updateConversationCost(null);
    // Clear the hash since conversation no longer exists
    clearConversationHash();
  }
}

/** Remove one conversation from the UI (see removeConversationsFromUI). */
export function removeConversationFromUI(convId: string): void {
  removeConversationsFromUI([convId]);
}
```

(`removeConversationFromUI` keeps its existing callers; check with `grep -rn removeConversationFromUI web/src`.)

Add, after `deleteConversation` (imports: `buildBulkTrashRequest`, `selectedLoadedIds` from `../state/slices/selection`; `renderSelectionChrome` from `../components/SidebarSelection`; `loadTrashedConversations`, `restoreConversations` from `./trash`):

```ts
const chatsLabel = (n: number): string => (n === 1 ? '1 chat' : `${n} chats`);

/**
 * Bulk delete: move the sidebar selection to the trash in one request, no
 * confirm (it is restorable), one Undo for the batch. Like single delete,
 * rows leave only once the server confirms; on failure the selection stays.
 */
export async function bulkDeleteConversations(): Promise<void> {
  const store = useStore.getState();
  if (store.isBulkDeleting) return;

  const body = buildBulkTrashRequest(store);
  const loadedIds = selectedLoadedIds(store);
  const tempIds = loadedIds.filter((id) => isTempConversation(id));
  const snapshot = store.conversations.filter((c) => loadedIds.includes(c.id) && !isTempConversation(c.id));
  const sync = getSyncManager();

  store.setBulkDeleting(true);
  renderSelectionChrome();
  try {
    let trashedIds: string[] = [];
    if (body) {
      loadedIds.forEach((id) => sync?.noteLocalChange(id));
      trashedIds = await conversations.bulkTrash(body);
      // Again once it's committed (see deleteConversation)
      trashedIds.forEach((id) => sync?.noteLocalChange(id));
    }
    store.endSelection();
    removeConversationsFromUI([...trashedIds, ...tempIds]);
    if (body) void loadTrashedConversations();

    const count = trashedIds.length + tempIds.length;
    if (count === 0) return;
    const restorable = snapshot.filter((c) => trashedIds.includes(c.id));
    toast.success(`Moved ${chatsLabel(count)} to trash.`, {
      action: trashedIds.length
        ? { label: 'Undo', onClick: () => void restoreConversations(trashedIds, restorable) }
        : undefined,
    });
  } catch (error) {
    log.error('Failed to bulk delete conversations', { error });
    toast.error('Failed to move chats to trash. Please try again.');
  } finally {
    useStore.getState().setBulkDeleting(false);
    renderSelectionChrome();
  }
}
```

(Check `toast.success`'s option type accepts `action: undefined`; if not, build the options object conditionally. If a retried request returned `[]` for rows that are in fact trashed, the next sync tick removes them - no extra handling.)

`trash.ts` (imports: `CONVERSATIONS_BULK_MAX_IDS` from `../config`):

```ts
/**
 * Restore many conversations (Undo of a bulk delete), in chunks of the
 * server's bulk cap. Rows not in the snapshot (unloaded pages of a
 * select-all delete) come back through sync: restore bumped updated_at.
 */
export async function restoreConversations(ids: string[], snapshot: Conversation[]): Promise<void> {
  const store = useStore.getState();
  const sync = getSyncManager();
  const byId = new Map(snapshot.map((c) => [c.id, c]));
  const restored: string[] = [];

  try {
    for (let i = 0; i < ids.length; i += CONVERSATIONS_BULK_MAX_IDS) {
      const chunk = ids.slice(i, i + CONVERSATIONS_BULK_MAX_IDS);
      chunk.forEach((id) => sync?.noteLocalChange(id));
      restored.push(...(await conversations.bulkRestore(chunk)));
    }
  } catch (error) {
    log.error('Failed to bulk restore conversations', { error, count: ids.length });
    toast.error('Failed to restore chats.');
    return;
  }

  restored.forEach((id) => {
    sync?.noteLocalChange(id);
    store.removeTrashedConversation(id);
    const source = byId.get(id);
    if (source) store.addConversation({ ...source, deleted_at: null, purge_at: null });
  });
  if (restored.some((id) => !byId.has(id))) void sync?.incrementalSync();
  renderConversationsList();
  toast.success(restored.length === 1 ? 'Conversation restored.' : `Restored ${restored.length} chats.`);
}
```

Update both files' header comments to mention bulk delete / bulk restore.

- [ ] **Step 4:** Re-run Step 2 plus `npx vitest run tests/unit/trash-actions.test.ts` → `0` (the refactor of `removeConversationFromUI` must not break single delete).

- [ ] **Step 5: Commit** `feat(sidebar): bulk delete and bulk restore actions`

---

### Task 6: Sidebar selection UI

**Files:**
- Modify: `web/src/components/SidebarSelection.ts` (fill in)
- Modify: `web/src/components/Sidebar.ts` (`renderConversationItem` hook + user-menu entry)
- Modify: `web/src/core/init.ts` (`renderAppShell` markup; call `initSidebarSelection()` next to `setupEventListeners()` at line ~566)
- Modify: `web/src/core/events.ts` (user-menu entry; list click branch)
- Modify: `web/src/core/gestures.ts` (no swipe while selecting)
- Modify: `web/src/styles/components/sidebar.css`
- Test: `web/tests/component/SidebarSelection.test.ts`

**Interfaces:**
- Consumes: Task 4 slice + selectors, Task 5 `bulkDeleteConversations`.
- Produces:
  - `enterSelectionMode(): void`, `exitSelectionMode(): void`, `renderSelectionChrome(): void`, `renderSelectionCheckbox(conv: Conversation): string`, `handleSelectionListClick(e: MouseEvent): boolean` (true = handled), `initSidebarSelection(): void`
  - DOM: `#sidebar.selecting`; `#selection-bar` with `#selection-cancel`, `.selection-count`, `#selection-all`; `#selection-footer` with `#selection-trash`; row checkbox `.conversation-select` (`role="checkbox"`, `aria-checked`); wrapper class `selected`; user-menu `#select-chats-btn`.

- [ ] **Step 1: Write the failing component tests** (`web/tests/component/SidebarSelection.test.ts`; follow `Sidebar.test.ts` for DOM setup - it renders the shell into `document.body`)

```ts
/**
 * Selection mode in the sidebar: entering, ticking rows, select all, chrome text.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import { renderConversationsList } from '@/components/Sidebar';
import {
  enterSelectionMode,
  exitSelectionMode,
  handleSelectionListClick,
  renderSelectionChrome,
} from '@/components/SidebarSelection';
import { renderAppShell } from '@/core/init';
import type { Conversation } from '@/types/api';

vi.mock('@/api/costs', () => ({
  costs: { getMonthlyCost: vi.fn().mockResolvedValue({ formatted: '0 CZK' }) },
}));
const bulkDelete = vi.hoisted(() => vi.fn());
vi.mock('@/core/conversation-actions', () => ({ bulkDeleteConversations: bulkDelete }));

function conv(id: string, extra: Partial<Conversation> = {}): Conversation {
  return { id, title: id, model: 'm', created_at: '', updated_at: new Date().toISOString(), ...extra };
}
const s = () => useStore.getState();
const row = (id: string) => document.querySelector<HTMLElement>(`[data-conv-id="${id}"]`)!;
const click = (el: Element) => {
  const e = new MouseEvent('click', { bubbles: true });
  Object.defineProperty(e, 'target', { value: el });
  return handleSelectionListClick(e);
};

beforeEach(() => {
  document.body.innerHTML = renderAppShell();
  useStore.setState({
    conversations: [conv('p', { pinned: true }), conv('a'), conv('b')],
    conversationsPagination: { nextCursor: null, hasMore: false, totalCount: 3, isLoadingMore: false },
    isLoading: false,
  });
  exitSelectionMode();
});

describe('sidebar selection mode', () => {
  it('enter shows the bar, checkboxes and a disabled trash button', () => {
    enterSelectionMode();

    expect(document.getElementById('sidebar')!.classList.contains('selecting')).toBe(true);
    expect(row('a').querySelector('.conversation-select')).not.toBeNull();
    expect(document.querySelector('.selection-count')!.textContent).toBe('0 selected');
    expect(document.querySelector<HTMLButtonElement>('#selection-trash')!.disabled).toBe(true);
  });

  it('clicking a row ticks it instead of opening it', () => {
    enterSelectionMode();

    expect(click(row('a').querySelector('.conversation-item')!)).toBe(true);

    expect(s().selectedIds.has('a')).toBe(true);
    expect(row('a').classList.contains('selected')).toBe(true);
    expect(row('a').querySelector('.conversation-select')!.getAttribute('aria-checked')).toBe('true');
    expect(document.querySelector('#selection-trash')!.textContent).toContain('Move 1 to trash');
    expect(s().currentConversation).toBeNull();
  });

  it('select all ticks unpinned rows and toggles to Deselect all', () => {
    enterSelectionMode();
    click(document.getElementById('selection-all')!);

    expect(row('a').classList.contains('selected')).toBe(true);
    expect(row('p').classList.contains('selected')).toBe(false);
    expect(document.querySelector('.selection-count')!.textContent).toBe('2 selected');
    expect(document.getElementById('selection-all')!.textContent).toBe('Deselect all');
  });

  it('the trash button runs bulk delete; cancel leaves selection mode', () => {
    enterSelectionMode();
    click(row('a').querySelector('.conversation-item')!);
    click(document.getElementById('selection-trash')!);
    expect(bulkDelete).toHaveBeenCalledTimes(1);

    click(document.getElementById('selection-cancel')!);
    expect(s().isSelecting).toBe(false);
    expect(row('a').querySelector('.conversation-select')).toBeNull();
  });

  it('shows Moving… while the request runs', () => {
    enterSelectionMode();
    useStore.setState({ isBulkDeleting: true });
    renderSelectionChrome();

    const btn = document.querySelector<HTMLButtonElement>('#selection-trash')!;
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain('Moving…');
  });

  it('outside selection mode, rows render no checkbox', () => {
    renderConversationsList();
    expect(row('a').querySelector('.conversation-select')).toBeNull();
  });
});
```

(The bar and footer live outside `#conversations-list`, so `handleSelectionListClick` handles clicks on the whole `#sidebar`; Step 3 wires one listener on `#sidebar`.)

- [ ] **Step 2:** `cd web && npx vitest run tests/component/SidebarSelection.test.ts > $SCRATCH/t6.log 2>&1; echo $?` → non-zero.

- [ ] **Step 3: Implement**

`init.ts` `renderAppShell()` - inside `<aside id="sidebar">`, right after the `.sidebar-header` div:

```html
      <div id="selection-bar" class="selection-bar hidden" role="toolbar" aria-label="Select chats">
        <button id="selection-cancel" type="button" class="btn btn-ghost">Cancel</button>
        <span class="selection-count" aria-live="polite">0 selected</span>
        <button id="selection-all" type="button" class="btn btn-ghost">Select all</button>
      </div>
```

and right after the `.sidebar-footer` div:

```html
      <div id="selection-footer" class="selection-footer hidden">
        <button id="selection-trash" type="button" class="btn btn-primary" disabled>${DELETE_ICON} Move 0 to trash</button>
      </div>
```

(import `DELETE_ICON` in init.ts if not already imported; check the existing button classes in `styles/components/buttons.css` - use whatever ghost/secondary class exists instead of `btn-ghost` if that one does not.)

`SidebarSelection.ts`:

```ts
/**
 * Sidebar selection mode for bulk delete: the selection bar and footer,
 * row checkboxes, and select all. Selection state lives in the store
 * (state/slices/selection.ts); Sidebar.ts only asks for each row's checkbox.
 */
import { useStore } from '../state/store';
import { isConversationSelected, selectedCount } from '../state/slices/selection';
import type { Conversation } from '../types/api';
import { CHECK_ICON, DELETE_ICON } from '../utils/icons';
import { renderConversationsList } from './Sidebar';
import { clearSearch } from './SearchInput';
import { isSearchResultsVisible } from './SearchResults';
import { bulkDeleteConversations } from '../core/conversation-actions';

export function enterSelectionMode(): void {
  const store = useStore.getState();
  if (isSearchResultsVisible()) clearSearch();
  store.setIsArchiveView(false);
  store.setIsTrashView(false);
  store.startSelection();
  renderSelectionChrome();
  renderConversationsList();
}

export function exitSelectionMode(): void {
  useStore.getState().endSelection();
  renderSelectionChrome();
  renderConversationsList();
}

/** Bar text, footer button, and the #sidebar.selecting class. */
export function renderSelectionChrome(): void {
  const state = useStore.getState();
  const sidebar = document.getElementById('sidebar');
  sidebar?.classList.toggle('selecting', state.isSelecting);
  document.getElementById('selection-bar')?.classList.toggle('hidden', !state.isSelecting);
  document.getElementById('selection-footer')?.classList.toggle('hidden', !state.isSelecting);
  if (!state.isSelecting) return;

  const count = selectedCount(state);
  const countEl = document.querySelector('#selection-bar .selection-count');
  if (countEl) countEl.textContent = `${count} selected`;
  const allBtn = document.getElementById('selection-all');
  if (allBtn) allBtn.textContent = state.selectionMode === 'all' ? 'Deselect all' : 'Select all';
  const trashBtn = document.getElementById('selection-trash') as HTMLButtonElement | null;
  if (trashBtn) {
    trashBtn.disabled = count === 0 || state.isBulkDeleting;
    trashBtn.innerHTML = `${DELETE_ICON} ${state.isBulkDeleting ? 'Moving…' : `Move ${count} to trash`}`;
  }
}

/** The row's checkbox in selection mode; '' otherwise. */
export function renderSelectionCheckbox(conv: Conversation): string {
  const state = useStore.getState();
  if (!state.isSelecting) return '';
  const checked = isConversationSelected(state, conv);
  return `<span class="conversation-select" role="checkbox" aria-checked="${checked}" aria-label="Select">${checked ? CHECK_ICON : ''}</span>`;
}

/** Sidebar clicks while selecting; returns true when it handled the click. */
export function handleSelectionListClick(e: MouseEvent): boolean {
  const state = useStore.getState();
  if (!state.isSelecting) return false;
  const target = e.target as HTMLElement;

  if (target.closest('#selection-cancel')) {
    exitSelectionMode();
    return true;
  }
  if (target.closest('#selection-all')) {
    if (state.selectionMode === 'all') state.deselectAll();
    else state.selectAll(new Date().toISOString());
    renderSelectionChrome();
    renderConversationsList();
    return true;
  }
  if (target.closest('#selection-trash')) {
    void bulkDeleteConversations();
    return true;
  }
  const wrapper = target.closest<HTMLElement>('#conversations-list [data-conv-id]');
  if (wrapper?.dataset.convId) {
    const conv = state.conversations.find((c) => c.id === wrapper.dataset.convId);
    if (conv) {
      state.toggleSelected(conv);
      renderSelectionChrome();
      renderConversationsList();
    }
    return true;
  }
  return target.closest('#conversations-list') !== null;
}

let initialized = false;

/** Wire the sidebar click and Escape listeners (once). */
export function initSidebarSelection(): void {
  if (initialized) return;
  initialized = true;
  // Capture phase: runs before the list's own row-open / action handlers
  document.getElementById('sidebar')?.addEventListener(
    'click',
    (e) => {
      if (handleSelectionListClick(e)) {
        e.preventDefault();
        e.stopPropagation();
      }
    },
    true
  );
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && useStore.getState().isSelecting) exitSelectionMode();
  });
}
```

Note the capture-phase listener: it pre-empts `events.ts`'s bubble-phase list handler, so `events.ts` needs no selection branch. If the import cycle `SidebarSelection → Sidebar → SidebarSelection` causes a TDZ error at load (Sidebar imports `renderSelectionCheckbox`), move `renderSelectionCheckbox` into `Sidebar.ts` itself (it's the "hook") and keep the rest here. Verify by running the component test.

`Sidebar.ts`:
- import `renderSelectionCheckbox` from `./SidebarSelection`.
- In `renderConversationItem`: add the class `selected` to `.conversation-item-wrapper` when `useStore.getState().isSelecting && isConversationSelected(useStore.getState(), conv)` (import the selector from `../state/slices/selection`), and put `${renderSelectionCheckbox(conv)}` as the first child of `.conversation-item`. The render cache compares HTML strings, so a toggled checkbox re-renders the list by itself.
- In `renderUserInfo`, add after the Trash entry:

```html
      <button id="select-chats-btn" class="user-menu-item" role="menuitem">
        ${CHECK_ICON}<span>Select chats</span>
      </button>
```

(add `CHECK_ICON` to the icons import).

`events.ts` - in the user-menu click handler, after the `.user-menu-trash` branch:

```ts
    if (target.closest('#select-chats-btn')) {
      closeUserMenu();
      enterSelectionMode();
      return;
    }
```

`gestures.ts` - first line of `conversationSwipe`'s `shouldStart`:

```ts
      if (useStore.getState().isSelecting) return false;
```

(import `useStore` if gestures.ts lacks it.)

`init.ts` - call `initSidebarSelection()` right after `setupEventListeners()`.

`sidebar.css` (append; use the variables already used in this file - check `variables.css` for the exact names of accent / border / spacing tokens):

```css
/* Bulk delete selection mode */
.selection-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
}

.selection-count {
    font-weight: 600;
}

.selection-footer {
    padding: var(--space-2) var(--space-3);
    border-top: 1px solid var(--border);
    flex-shrink: 0;
}

.selection-footer .btn {
    width: 100%;
    justify-content: center;
}

.sidebar.selecting .sidebar-header,
.sidebar.selecting #search-container,
.sidebar.selecting .sidebar-footer,
.sidebar.selecting .sidebar-nav-row,
.sidebar.selecting .sidebar-nav-row + .sidebar-divider,
.sidebar.selecting .conversation-actions,
.sidebar.selecting .conversation-actions-swipe {
    display: none;
}

.conversation-select {
    flex-shrink: 0;
    width: 20px;
    height: 20px;
    margin-right: var(--space-2);
    border: 1.5px solid var(--text-muted);
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
}

.conversation-item-wrapper.selected .conversation-select {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--on-accent, #fff);
}

.conversation-select svg {
    width: 14px;
    height: 14px;
}
```

Run `cd web && npx vitest run tests/unit/css-class-collisions.test.ts tests/unit/css-undefined-vars.test.ts` - they catch a colliding class name or an undefined CSS variable; rename (`sidebar-selection-*`) or swap variables until green.

- [ ] **Step 4:** Re-run Step 2 plus `npx vitest run tests/component/Sidebar.test.ts tests/unit/css-class-collisions.test.ts tests/unit/css-undefined-vars.test.ts` → `0`. `make lint > $SCRATCH/lint.log 2>&1; echo $?` → `0`.

- [ ] **Step 5: Look at it.** `make dev`, open http://localhost:5173 in Chrome (claude-in-chrome), seed a few chats, enter selection mode; screenshot desktop and 375px mobile (sidebar drawer open). Check: the bar and footer line up with the header/footer they replace, spacing above and below each divider is even, the checkbox lines up with the title's first line, dark mode reads well. Fix and re-check before committing.

- [ ] **Step 6: Commit** `feat(sidebar): select chats and move them to the trash in bulk`

---

### Task 7: E2E - desktop and mobile

**Files:**
- Create: `web/tests/e2e/bulk-delete.spec.ts`

- [ ] **Step 1: Write the tests**

```ts
/**
 * E2E: bulk delete from the sidebar (select chats -> move to trash -> Undo).
 */
import { test, expect } from '../global-setup';

const rows = (page: import('@playwright/test').Page) =>
  page.locator('#conversations-list .conversation-item-wrapper[data-conv-id]');
const row = (page: import('@playwright/test').Page, title: string) =>
  page.locator('#conversations-list .conversation-item-wrapper', { hasText: title });

async function seed(request: import('@playwright/test').APIRequestContext, titles: string[]): Promise<string[]> {
  const seeded = await request.post('/test/seed', {
    data: {
      conversations: titles.map((title) => ({
        title,
        messages: [{ role: 'user', content: `${title}?` }, { role: 'assistant', content: `${title}!` }],
      })),
    },
  });
  return (await seeded.json()).conversation_ids as string[];
}

async function enterSelection(page: import('@playwright/test').Page): Promise<void> {
  await page.click('#user-menu-btn');
  await page.click('#select-chats-btn');
  await expect(page.locator('#selection-bar')).toBeVisible();
}

for (const viewport of [
  { name: 'desktop', size: { width: 1280, height: 800 } },
  { name: 'mobile', size: { width: 375, height: 812 } },
]) {
  test.describe(`bulk delete (${viewport.name})`, () => {
    test.use({ viewport: viewport.size });

    test.beforeEach(async ({ page }) => {
      await page.goto('/');
      if (viewport.name === 'mobile') await page.click('#menu-btn');
    });

    test('pick three, move to trash, Undo restores them', async ({ page, request }) => {
      await seed(request, ['One', 'Two', 'Three', 'Four']);
      await page.reload();
      if (viewport.name === 'mobile') await page.click('#menu-btn');
      await expect(rows(page)).toHaveCount(4);

      await enterSelection(page);
      for (const title of ['One', 'Two', 'Three']) await row(page, title).click();
      await expect(page.locator('.selection-count')).toHaveText('3 selected');
      await page.click('#selection-trash');

      await expect(rows(page)).toHaveCount(1);
      await expect(row(page, 'Four')).toBeVisible();
      await expect(page.locator('.modal-container:not(.modal-hidden)')).toHaveCount(0);
      await expect(page.locator('#selection-bar')).toBeHidden();
      await page.getByRole('button', { name: 'Undo' }).click();
      await expect(rows(page)).toHaveCount(4);
    });

    test('select all, untick one: only it and pinned chats remain', async ({ page, request }) => {
      const [pinnedId] = await seed(request, ['Pinned', 'Keep', 'Gone 1', 'Gone 2']);
      await request.post(`/api/conversations/${pinnedId}/pin`);
      await page.reload();
      if (viewport.name === 'mobile') await page.click('#menu-btn');
      await expect(rows(page)).toHaveCount(4);

      await enterSelection(page);
      await page.click('#selection-all');
      await row(page, 'Keep').click();
      await expect(page.locator('.selection-count')).toHaveText('2 selected');
      await page.click('#selection-trash');

      await expect(rows(page)).toHaveCount(2);
      await expect(row(page, 'Pinned')).toBeVisible();
      await expect(row(page, 'Keep')).toBeVisible();
    });

    test('Cancel leaves selection mode and rows open again', async ({ page, request }) => {
      await seed(request, ['Solo']);
      await page.reload();
      if (viewport.name === 'mobile') await page.click('#menu-btn');

      await enterSelection(page);
      await page.click('#selection-cancel');
      await expect(page.locator('#selection-bar')).toBeHidden();
      await row(page, 'Solo').click();
      await expect(page.locator('.message.assistant')).toHaveCount(1);
    });
  });
}
```

Adjust to the fixture's reality before running: check whether `/test/seed` resets per test (per-test isolation in `global-setup.ts`), whether the mobile sidebar opens with `#menu-btn`, and whether the pin route is reachable from `request` with the test auth (as `sync-other-device.spec.ts` does for archive). If the user menu is not reachable in the mobile drawer without scrolling, scroll it into view first.

- [ ] **Step 2: Build and run** (E2E runs the last build): `nice -n 10 make build > $SCRATCH/build.log 2>&1; echo $?` → `0`; then `cd web && nice -n 10 npx playwright test tests/e2e/bulk-delete.spec.ts > $SCRATCH/e2e.log 2>&1; echo $?` → `0`. On failure use the `e2e-debugger` agent's method (trace first) - do not add retries or sleeps.

- [ ] **Step 3: Commit** `test(sidebar): bulk delete E2E on desktop and mobile`

---

### Task 8: Visual baselines, docs, full suite, merge

**Files:**
- Modify: `web/tests/visual/chat.visual.ts` (desktop) and `web/tests/visual/mobile.visual.ts` (mobile)
- Modify: `docs/features/ui-features.md`

- [ ] **Step 1: Visual tests.** In `chat.visual.ts` add, after `sidebar with conversations` (same seeding loop):

```ts
  test('sidebar in selection mode', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('#new-chat-btn');
    for (let i = 0; i < 3; i++) {
      await page.click('#new-chat-btn');
      await page.fill('#message-input', `Test message ${i + 1}`);
      await page.click('#send-btn');
      await page.waitForSelector('.message.assistant:not(.streaming)', { timeout: 10000 });
    }
    await expect(page.locator('.conversation-item-wrapper', { hasText: 'New Conversation' })).toHaveCount(0);
    await page.click('#user-menu-btn');
    await page.click('#select-chats-btn');
    await page.locator('#conversations-list .conversation-item').first().click();
    await page.waitForTimeout(500);

    await expect(page.locator('#sidebar')).toHaveScreenshot('sidebar-selection.png');
  });
```

In `mobile.visual.ts` add the same flow using that file's helper for creating conversations and opening the sidebar, screenshot `mobile-sidebar-selection.png`.

- [ ] **Step 2: Linux baselines.** Commit the tests, push the branch, then run `/regen-baselines` (it dispatches the CI workflow and commits the `*-linux.png` files). Inspect both new PNGs before accepting them.

- [ ] **Step 3: Docs.** In `docs/features/ui-features.md`:
  - Under `### Delete` add a `### Bulk delete` subsection: entry point (user menu "Select chats"), selection mode behavior, select all semantics (unpinned, unloaded pages, `created_before`), no confirm, one Undo (chunked restore), failure behavior, desktop Escape.
  - In the Trash **Database** table add `trash_conversations()` / `trash_all_conversations()` / `restore_conversations()`; in the **API** table add `POST /conversations/bulk-trash` and `POST /conversations/bulk-restore`.
  - Document `CONVERSATIONS_BULK_MAX_IDS` (default 500).

- [ ] **Step 4: Full verification.**

```bash
nice -n 10 make lint > $SCRATCH/lint.log 2>&1; echo "lint=$?"
nice -n 10 caffeinate -i make test-all > $SCRATCH/test-all.log 2>&1; echo "test-all=$?"
```

Both must print `0`. On failure read the log, fix, re-run - do not merge red.

- [ ] **Step 5: Commit** `docs(ui): bulk delete` (and the visual tests if not yet committed), then use superpowers:finishing-a-development-branch to merge `feat/bulk-delete` into main. Deploying is the user's call - ask.
