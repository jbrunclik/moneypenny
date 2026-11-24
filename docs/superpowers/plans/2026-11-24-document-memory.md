# Document Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A per-user library of saved documents (file copy + title, summary, "use for", optional end date) that the agent sees in every chat, opens on demand, and that expires nightly into Recently deleted.

**Architecture:** New `user_documents` table + a `DocumentMixin` on `db`; bytes copied into the existing blob store under `doc/{id}`. Two agent tools (`manage_documents`, `open_document`) mirror `manage_memory`'s guards; a per-turn list sits next to the memory list. The nightly defrag script expires and purges. A Documents section on the Data page uses four new endpoints.

**Tech Stack:** Flask/APIFlask + Pydantic, LangChain `@tool`, SQLite (yoyo migration), vanilla TS + Vite, Vitest, Playwright, the eval harness.

**Spec:** `docs/superpowers/specs/2026-11-24-document-memory-design.md`

## Global Constraints

- Config (all in `src/config.py` with defaults, in `.env.example`, and in the docs page): `DOCUMENTS_MAX_ENTRIES=50`, `DOCUMENTS_MAX_TOTAL_BYTES=200 MB` (`200 * BYTES_PER_MB`), `DOCUMENTS_SOFT_DELETE_RETENTION_DAYS=30`, `DOCUMENT_TITLE_MAX_CHARS=80`, `DOCUMENT_SUMMARY_MAX_CHARS=300`, `DOCUMENT_USE_FOR_MAX_CHARS=200`, `DOCUMENTS_MAX_OPS_PER_CALL=5`.
- Soft-deleted documents do not count toward `DOCUMENTS_MAX_ENTRIES` but do count toward `DOCUMENTS_MAX_TOTAL_BYTES`.
- `valid_until` is a local date and the last day the document holds. It is hidden from the list and from `open_document` from the next day on. Restoring a document clears a past end date. The semantics are identical to memories (`Memory.expired(today)`).
- Saves only from files in the **current** conversation (`load_conversation_file`).
- Injection scan (`find_injection`) on title, summary and use_for. Not bound in anonymous mode. Autonomous runs only with a grant (binding + `check_autonomous_permission`). Never in `EXTRACT_ONLY_TOOL_NAMES`. Both tools in `_ANONYMOUS_EXCLUDED_TOOLS`. `manage_documents` in `SIDE_EFFECT_TOOLS`.
- Logs: user ids and document ids only, never titles, summaries or file names.
- Migration number: `0103_user_documents`. Re-check the highest number on `main` before committing.
- Stage explicit paths only. Conventional Commits. `make lint` + `make test` before each backend commit; `make test-all` before the UI and final commits.

## Review Focus

1. **Replacing at the cap.** A `save` with `replaces` when the library has 50 live documents must succeed (net zero). A plain save at 50 is rejected. → Task 3 test `test_save_with_replaces_at_cap_succeeds`.
2. **Replacing someone else's id or a missing one.** `replaces` naming another user's document, a deleted one or an unknown id rejects the whole save; nothing is written and no blob is left behind. → Task 1 `test_add_document_replacing_foreign_id_writes_nothing`, Task 3 `test_save_replaces_unknown_rejected_no_blob`.
3. **An attachment already swept by retention.** Saving it returns "the file was cleaned up, ask the user to send it again". → Task 3 `test_save_expired_attachment_says_send_again`.
4. **The end-date boundary.** A document with `valid_until == today` is listed and opens today and is gone tomorrow; `expire_documents(tomorrow)` soft-deletes it. → Task 1 `test_expire_boundary`, Task 4 `test_list_hides_expired_from_next_day`.
5. **Opening a deleted or expired document, or another user's id.** `open_document` returns a tool error saying it is no longer in the library (or not found) and never returns bytes. → Task 3 `test_open_deleted_or_foreign_errors`.

---

### Task 1: Storage: migration, dataclass, DocumentMixin, config

**Files:**
- Create: `migrations/0103_user_documents.py`, `src/db/models/documents.py`, `tests/integration/test_db_documents.py`
- Modify: `src/db/models/dataclasses.py` (add `Document`), `src/db/models/__init__.py` (mixin into `db`, export `Document`), `src/db/models/helpers.py` (`make_document_blob_key`), `src/config.py`, `.env.example`

**Interfaces:**
- Produces:
  - `@dataclass Document`: `id, user_id, title, summary, use_for, filename, mime_type, size_bytes: int, created_at, updated_at, valid_until: date|None, source_conversation_id: str|None, source_message_id: str|None, deleted_at: datetime|None, last_opened_at: datetime|None`, method `expired(today: date) -> bool`.
  - `make_document_blob_key(document_id: str) -> str` → `"doc/{id}"`.
  - `DocumentMixin` methods on `db`:
    - `add_document(user_id, *, title, summary, use_for, filename, mime_type, data: bytes, valid_until: date|None, source_conversation_id, source_message_id, replaces: str|None = None) -> Document`. It writes the blob, then in one transaction inserts the row and soft-deletes `replaces`. It raises `DocumentWriteError(reason)` when `replaces` is not a live document of this user, and deletes the blob it wrote.
    - `get_document(document_id, user_id) -> Document|None` (live or deleted)
    - `list_documents(user_id) -> list[Document]` (live, newest first, includes expired-but-not-yet-swept; callers filter with `expired(today)`)
    - `list_deleted_documents(user_id) -> list[Document]`
    - `update_document(document_id, user_id, *, title=None, summary=None, use_for=None, valid_until: date|None|_Unset=UNSET) -> Document|None`
    - `delete_document(document_id, user_id) -> bool` (soft)
    - `restore_document(document_id, user_id, today: date) -> bool` (clears `valid_until` when `< today`)
    - `document_usage(user_id) -> tuple[int, int]` → (live count, bytes of live + soft-deleted)
    - `touch_document_opened(document_id) -> None`
    - `expire_documents(today: date) -> int`
    - `purge_deleted_documents(retention_days: int) -> int` (deletes rows and their blobs)

- [ ] **Step 1: Write failing tests** in `tests/integration/test_db_documents.py`:
  - `test_add_and_get_roundtrip`: the blob at `doc/{id}` equals the data; `size_bytes == len(data)`.
  - `test_add_document_replacing_foreign_id_writes_nothing`: `replaces=<other user's doc id>` raises `DocumentWriteError`; `list_documents` is unchanged; no `doc/` blob exists for a new id (check `get_blob_store()` key count before/after).
  - `test_replaces_soft_deletes_old`: the old document is in `list_deleted_documents`.
  - `test_expire_boundary`: `valid_until=date(2026,12,1)`; `expire_documents(date(2026,12,1)) == 0`; `expire_documents(date(2026,12,2)) == 1`.
  - `test_purge_deletes_blob`: soft-delete, back-date `deleted_at` 31 days, `purge_deleted_documents(30) == 1`; the blob is gone.
  - `test_restore_clears_past_end_date`.
  - `test_usage_counts_deleted_bytes_not_entries`.
- [ ] **Step 2:** `pytest tests/integration/test_db_documents.py -q`. Expected: FAIL (import error).
- [ ] **Step 3: Implement.** Columns per the spec table; index `(user_id, deleted_at)`; FK `user_id` → users `ON DELETE CASCADE`; no FK on source ids. The rollback step drops the table. Config values per Global Constraints, plus `.env.example` lines.
- [ ] **Step 4:** `pytest tests/integration/test_db_documents.py -q`. Expected: PASS. Then `make lint && make test`, with exit codes checked.
- [ ] **Step 5:** Commit `feat(documents): user_documents table and storage`.

### Task 2: Generalize the file content builder

**Files:**
- Modify: `src/agent/gemini_files.py`, `src/agent/tools/file_retrieval.py`
- Test: `tests/unit/test_file_retrieval.py` (existing), `tests/unit/test_gemini_files.py` (existing, if present; else add the case to the retrieval test)

**Interfaces:**
- Produces:
  - `ensure_gemini_file_uri_for_key(cache_key: str, data: bytes, mime_type: str) -> str`. The cache key is used verbatim in the `gemini_files` kv namespace. `ensure_gemini_file_uri(message_id, file_index, ...)` becomes a wrapper passing `f"{message_id}:{file_index}"` (the same key as today: existing cache entries stay valid).
  - `build_file_content(*, display_id: str, cache_key: str, file_name: str, mime_type: str, data: bytes) -> str | list[dict[str, Any]]` (public, in `file_retrieval.py`). `retrieve_file` calls it with `display_id=f"message {message_id}"` and `cache_key=f"{message_id}:{file_index}"`. The header text and the Office `file_id` keep their current values for messages.

- [ ] **Step 1: Failing test** `test_build_file_content_uses_given_cache_key`: patch `ensure_gemini_file_uri_for_key`; a 9 MB PDF with `cache_key="doc:abc"` calls it with `"doc:abc"`.
- [ ] **Step 2:** Run it. Expected: FAIL.
- [ ] **Step 3:** Implement. The existing retrieval tests must pass unchanged (behaviour preserved).
- [ ] **Step 4:** `pytest tests/unit/test_file_retrieval.py tests/unit -k "gemini_file or retrieve" -q`. Expected: PASS.
- [ ] **Step 5:** Commit `refactor(files): content builder takes a cache key`.

### Task 3: Agent tools `manage_documents` and `open_document`, registered

**Files:**
- Create: `src/agent/tools/documents.py`, `tests/unit/test_documents_tool.py`
- Modify: `src/agent/tools/__init__.py` (`get_available_tools`, `_TOOL_MAP`, `_ANONYMOUS_EXCLUDED_TOOLS`, the grantable names list near line 497; NOT in `tools_for_grants`' default list or the unrestricted-agent default), `src/agent/tool_display.py` (metadata + `extract_tool_detail` branches: "Saved <n> document(s)" / "Opened <title>"), `src/api/helpers/lost_actions.py` (`manage_documents` → `SIDE_EFFECT_TOOLS`), `src/api/routes/agent_assist.py` (`_PROMPT_TOOL_DESCRIPTIONS`), `web/src/components/JobEditor.ts` (`BASE_TOOLS`; `manage_documents` `writable: true` if it joins `WRITE_LEVEL_TOOLS`, as `manage_memory` does), `tests/fixtures/prompt_snapshots/*` (via `make prompt-snapshots`)

**Interfaces:**
- Consumes: Task 1 `db` methods, `DocumentWriteError`, `make_document_blob_key`; Task 2 `build_file_content`; `load_conversation_file`, `parse_file_id`, `get_conversation_context`, `check_autonomous_permission`, `find_injection`, `matching_memory_ids` (the generic prefix matcher; reuse, don't copy), `tool_error`.
- Produces:
  - `manage_documents(operations: list[DocumentOp]) -> str`. `DocumentOp` is a Pydantic model with `action: Literal["save","update","delete"]`, `file_id: str = ""`, `id: str = ""`, `title: str = ""`, `summary: str = ""`, `use_for: str = ""`, `valid_until: str = ""` (`""` = none / on update, clears), `replaces: str = ""`. All concrete types (schema guard). Returns one line per op: `SAVED <short id> "<title>"`, `UPDATED <short id>`, `DELETED <short id>`, or `REJECTED (<action>): <reason>`.
  - `open_document(id: str) -> str | list[dict]`. Returns `build_file_content(display_id=f"saved document {short id}", cache_key=f"doc:{id}", ...)` and calls `touch_document_opened`.
  - The docstrings carry the save rules: save only on request or after a yes; state any end date or replacement and wait for a yes; no end date on auto-renewing contracts; an amendment is its own document; summary = contents and key figures/parties; use_for = when it is relevant.

- [ ] **Step 1: Failing tests** (`tests/unit/test_documents_tool.py`, with the conversation context set as in `test_memory_tool.py`):
  - `test_save_from_current_message`: the blob is copied; the result contains `SAVED`; the row has `source_conversation_id` set.
  - `test_save_from_other_conversation_rejected`.
  - `test_save_expired_attachment_says_send_again`: the result contains "send it again".
  - `test_save_with_replaces_at_cap_succeeds` (50 live + replaces → SAVED; live count stays 50).
  - `test_save_at_cap_rejected` (it mentions replace or delete).
  - `test_save_over_byte_cap_rejected`.
  - `test_save_replaces_unknown_rejected_no_blob`.
  - `test_injection_in_summary_rejected`.
  - `test_past_valid_until_rejected`; `test_update_clears_valid_until_with_empty_string`.
  - `test_overlong_fields_rejected` (title 81, summary 301, use_for 201 chars).
  - `test_more_than_max_ops_rejected_whole`.
  - `test_ambiguous_short_id_rejected_names_both`.
  - `test_open_returns_pdf_inline_and_touches_opened`.
  - `test_open_deleted_or_foreign_errors` (deleted, expired-yesterday, another user's id).
  - `test_autonomous_without_grant_refused`.
  - `TestToolSchema`: every parameter has a concrete type (copy the `test_garmin_workout_tool.py` pattern).
  - In `tests/unit/test_tools_registry*.py` / `test_tool_display.py` (existing): anonymous excludes both; not in `EXTRACT_ONLY_TOOL_NAMES`.
- [ ] **Step 2:** `pytest tests/unit/test_documents_tool.py -q`. Expected: FAIL.
- [ ] **Step 3:** Implement and register. Validate the whole batch before writing anything (as `manage_memory` does), then apply in order. Log "Document saved" / "Document save rejected" / "Document opened" with ids, mime, size and `has_end_date` only.
- [ ] **Step 4:** `make prompt-snapshots`, then `pytest tests/unit -q -k "document or tool_display or prompt_snapshots or tools"`. Expected: PASS. Then `make lint && make test`.
- [ ] **Step 5:** Commit `feat(documents): manage_documents and open_document tools` (including the snapshot files).

### Task 4: Prompt: static guidance and the per-turn list

**Files:**
- Create: `src/agent/prompt_texts/documents.py` (`DOCUMENTS_SYSTEM_PROMPT`), `src/agent/prompt_documents.py`, `tests/unit/test_prompt_documents.py`
- Modify: `src/agent/prompts.py` (`get_static_prompt_for_profile`: append when `profile != "anonymous"`, next to the memory instructions; `get_dynamic_prompt_parts` AND `get_system_prompt`: append the list wherever the memory list is appended, under the same `include_memories` condition), `tests/fixtures/prompt_snapshots/*`

**Interfaces:**
- Produces: `get_user_documents_list_prompt(user_id: str) -> str`. It returns `""` when there are no live, unexpired documents (the caller skips empty parts). Otherwise it returns a header `## Saved documents (<n>/<max>)` and one line per document:
  `- <short id> | <title> | <filename>, saved <YYYY-MM-DD>[, until <YYYY-MM-DD>] | <summary> | Use for: <use_for>` (whitespace-folded).

- [ ] **Step 1: Failing tests:** `test_empty_library_adds_nothing`; `test_line_format` (exact string for one fixed document); `test_list_hides_expired_from_next_day`; `test_anonymous_profile_has_no_document_guidance`; `test_system_prompt_and_dynamic_parts_both_include_list`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. The guidance text covers the spec's Prompt bullets. Keep it under ~250 words: it sits in the cached prefix, and `sizes.txt` will show it.
- [ ] **Step 4:** `make prompt-snapshots`; `pytest tests/unit/test_prompt_documents.py tests/unit/test_prompt_snapshots.py tests/unit/test_prompts.py -q`. Expected: PASS. Add a seeded document to the pinned example user in the dynamic snapshot, so the line format is snapshotted.
- [ ] **Step 5:** Commit `feat(documents): document list in the chat context`.

### Task 5: Nightly expiry and purge

**Files:**
- Modify: `scripts/defragment_memories.py` (right after the memory expire/purge block, same `not args.dry_run` guard, for all users), `tests/unit/test_defragment_memories.py`

- [ ] **Step 1: Failing test** `test_main_expires_and_purges_documents`. Patch `db.expire_documents` / `db.purge_deleted_documents` and assert they are called with `local_today()` and `Config.DOCUMENTS_SOFT_DELETE_RETENTION_DAYS`, and not in `--dry-run`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Log lines "Documents expired" `{expired}` and "Documents purged" `{purged, retention_days}`.
- [ ] **Step 4:** `pytest tests/unit/test_defragment_memories.py -q`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(documents): nightly expiry and purge`.

### Task 6: API endpoints and TS client

**Files:**
- Create: `src/api/schemas/documents.py`, `src/api/routes/documents.py`, `web/src/api/documents.ts`, `tests/integration/test_routes_documents.py`
- Modify: blueprint registration (where `memory.api` is registered), `static/openapi.json` + `web/src/types/generated-api.ts` (via `make openapi && make types`, never by hand), `web/src/types/api.ts` (re-export `SavedDocument`, `DocumentsResponse` like `Memory`), `tests/integration/test_route_auth_coverage.py` if it lists routes

**Interfaces:**
- Produces:
  - `GET /api/documents` → `DocumentsResponse{documents: SavedDocumentResponse[], deleted: SavedDocumentResponse[], limit: int, bytes_used: int, bytes_limit: int}`. `SavedDocumentResponse` = `id, title, summary, use_for, filename, mime_type, size_bytes, created_at, valid_until|null, deleted_at|null, last_opened_at|null, source_conversation_id|null`. Expired-but-unswept documents are listed in `documents` with their past `valid_until` (the UI shows "expired").
  - `GET /api/documents/<id>/file` → the bytes, `Content-Disposition: attachment; filename=...` (live or deleted, owner only, 404 otherwise).
  - `DELETE /api/documents/<id>` → `StatusResponse`; `POST /api/documents/<id>/restore` → `StatusResponse`, or a 409 with a message when over either cap.
  - TS: `documents.list(): Promise<DocumentsResponse>`, `documents.delete(id)`, `documents.restore(id)`, `documents.downloadUrl(id)` / a download helper following `web/src/api/files.ts`'s authenticated-download pattern (JWT is header-only).
- [ ] **Step 1: Failing tests:** list, with deleted documents separated; download sets the attachment header; another user's id → 404 on all four; restore over cap → 409; delete then restore roundtrip.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement; `make openapi && make types`.
- [ ] **Step 4:** `pytest tests/integration/test_routes_documents.py tests/integration/test_route_auth_coverage.py -q`; `make lint`. Expected: PASS.
- [ ] **Step 5:** Commit `feat(documents): documents API`.

### Task 7: Data page Documents section

**Files:**
- Modify: `web/src/components/KVStorePage.ts` (a Documents section between Memories and K/V, plus its Recently deleted list; extract it to `web/src/components/kv-documents.ts` if `KVStorePage.ts` would pass ~700 lines), `web/src/core/kv-store.ts` (fetch `documents.list()` alongside memories; callbacks `onDeleteDocument`, `onRestoreDocument`, `onDownloadDocument`), the Data page stylesheet (`kv-doc-*` classes), `tests/e2e_server/fixture_routes.py` (`POST /test/seed-document` inserting through `db.add_document`) and `control_routes.py` reset (`DELETE FROM user_documents`)
- Test: `web/tests/component/kv-store-page.test.ts`, new `web/tests/e2e/documents.spec.ts`, `web/tests/visual/kv-store.visual.ts` (a seeded document in "storage page with data")

**Interfaces:**
- Consumes: Task 6 TS client and types.
- Row content: the title; `filename · size` (human-readable, e.g. "1.2 MB"); the summary; "Use for: …"; "Saved <date>" and "Until <date>" or "Expired <date>"; buttons Download (`btn btn-secondary-sm`) and Delete (`btn btn-danger-sm` or the pattern the memory rows use). Empty: `createEmptyState({ title: 'No documents yet', ... })` with one line: "Ask Moneypenny to keep a document you share in a chat." The count label is `n/limit`, like memories.

- [ ] **Step 1: Failing component tests:** it renders rows with title, summary and use-for; the empty state; delete calls the callback; the deleted list's restore calls the callback; expired shows "Expired".
- [ ] **Step 2:** `cd web && npx vitest run tests/component/kv-store-page.test.ts`. Expected: FAIL.
- [ ] **Step 3:** Implement, reusing the memory row structure and existing button/surface classes.
- [ ] **Step 4:** Vitest passes. `make build`. Write the E2E `documents.spec.ts`: seed → open `#/storage` → see the row → Delete → appears under Recently deleted → Restore → back. Run on desktop and mobile projects with `E2E_PORT=8011 make test-fe-e2e` (or the scoped Playwright command the Makefile documents). Look at desktop and 375px screenshots for vertical rhythm. Update the visual baselines per `/regen-baselines` if the storage visual changed.
- [ ] **Step 5:** Commit `feat(documents): documents on the Data page` (including any baselines).

### Task 8: Evals

**Files:**
- Modify: `evals/run.py` (a case field `documents: [{title, summary, use_for, file, valid_until?}]` seeded through `db.add_document` with bytes read from `evals/fixtures/`, soft-deleted in cleanup like memories)
- Create: `evals/fixtures/lease_fixed_term.pdf`, `evals/fixtures/insurance_auto_renew.pdf`, `evals/fixtures/equity_waterfall.pdf` (small generated PDFs: a lease with "Term: 2026-12-01 to 2027-11-30"; a policy with "renews automatically each year"; a table of equity value per exit valuation, e.g. 50/100/200/400 M EUR rows), plus a waterfall v2 and a lease amendment PDF. Cases: `evals/cases/documents_save_fixed_term.yaml`, `documents_save_auto_renew.yaml`, `documents_offer_not_save.yaml`, `documents_open_for_exit.yaml`, `documents_replace_new_version.yaml`, `documents_amendment_separate.yaml`
- Test: `tests/unit/test_eval_*` (whichever covers case parsing) gains `documents` parsing.

Expected behaviour per case (rubric + tools):
- fixed term + "keep this" → the reply proposes 2027-11-30 as the end date and asks; `forbidden_tools: [manage_documents]` on that turn. A second case with history containing the yes → `required_tools: [manage_documents]`, rubric checks `valid_until` 2027-11-30.
- auto-renew + "keep this" → `required_tools: [manage_documents]`, no `valid_until`.
- shares a PDF and asks a question about it, no request to keep → `forbidden_tools: [manage_documents]`; the rubric allows an offer.
- seeded waterfall, "what would I get if we exit at 200 M?" → `required_tools: [open_document]`, the rubric checks the 200 M row value.
- seeded waterfall + a new version shared with "here's the updated waterfall, keep it" → names the old document and asks (no save on that turn).
- amendment to the seeded lease + "keep this too" → saved without `replaces` (or asks only about an end date).

- [ ] **Step 1:** Parsing test fails → implement `documents` seeding → passes.
- [ ] **Step 2:** Run the new cases: `make eval -- --only documents_` (or the harness's equivalent filter) 2× each, plus `make eval-smoke`. Report the USD cost. Fix the prompt or docstring on failures (steering goes in tool results where possible), rerun, and report the cost again.
- [ ] **Step 3:** Commit `test(evals): document memory cases` (plus any prompt tweaks as `fix(documents): ...`).

### Task 9: Docs, announcement, review check, TODO

Run the `docs-updater` agent with this scope:
- `docs/features/memory-and-context.md`: a new "Document Memory" section (design decisions, bounds table, tools, cleanup, key files, tests); `docs/features/agent-tools.md` tools table; `docs/features/file-handling.md` (library copies are outside retention); the `docs/README.md` index if needed.
- `docs/regular-review.md`: a check covering documents saved vs opened per user (from "Document saved"/"Document opened" logs and `last_opened_at`), documents never opened 30 days after saving, rejected saves by reason, total stored bytes.
- `TODO.md`: remove part (1) from "Knowledge base, then Projects" (leave Projects, noting that per-project pinned documents build on `user_documents`); add "Document memory re-measure (~Dec 15 2026)", covering whether anything was saved, whether saved documents are opened in later chats, and the per-turn list size.
- `announcements/2026-11-24-document-memory.md`: Czech + English, for the family, in the format of `announcements/2026-11-20-artifacts-more-often.md`. You can ask Moneypenny to keep important documents (contracts, financial overviews) and it brings them up in later chats; they're on the Data page; it asks about an end date for fixed-term contracts and clears them away after it.

- [ ] **Step 1:** docs-updater + announcement written; review the diff (no hostnames).
- [ ] **Step 2:** Final gate: `make lint` and `make test-all` (under `nice -n 10` and `caffeinate`), exit codes checked.
- [ ] **Step 3:** Commit `docs(documents): document memory docs and announcement`.
