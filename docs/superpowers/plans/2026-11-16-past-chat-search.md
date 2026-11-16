# Past-Chat Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Past-chat search finds Czech chats with an inflected or wrong word, ranks keyword and meaning hits together, filters and lists by date, and drops embeddings of deleted messages.

**Architecture:** `db.search` keeps its AND query and falls back to an OR query with trimmed Czech endings when it finds fewer than 3 hits; both take optional UTC bounds. A migration purges orphan embeddings and adds a delete trigger; scoring moves to `math.sumprod`. The tool fuses both lists by reciprocal rank and gains `after`/`before` and an empty-query listing.

**Tech Stack:** Python, SQLite FTS5, yoyo, LangChain tools.

**Spec:** docs/superpowers/specs/2026-11-16-past-chat-search-design.md

## Global Constraints

- Migration `0095_message_embedding_cleanup` (check the highest number on main right before committing).
- `CONVERSATION_SEARCH_FALLBACK_MIN_RESULTS = 3` (Config constant, no `.env` change); RRF constant `60` (module constant `_RRF_K`).
- Ending trim: words of 6+ characters lose their last 2 characters, as a prefix, in the `any` mode only.
- A query whose words all match ranks exactly as today (AND hits first, in bm25 order).
- No new dependency; no new tool; static prompt changes need `make prompt-snapshots` in the same commit.
- Gate per task: `make lint` + `make test`; TDD; commit by explicit paths. Evals: `make eval-ab` and report the cost.

## Review Focus

- A query of short or stop words in the `any` mode ("a je to") would match nearly everything: words under 3 characters are dropped in that mode unless none remain (Task 1 test).
- FTS syntax characters in a query (`"10.80"`, `pull-ups`, `C++`, `(x)`) never raise, in either mode (Task 1 test).
- `after` later than `before`, or a malformed date, is a retriable tool error, not an empty list (Task 3 test).
- A conversation purge from the trash deletes its messages' embeddings through the trigger (Task 2 test via the trash purge path).
- The listing never shows another user's or a trashed conversation (Task 1 test).

---

### Task 1: Search fallback, date bounds and the listing (db)

**Files:**
- Modify: `src/db/models/search.py`, `src/db/models/dataclasses.py` (`SearchResult.match_mode: str = "all"`; new `RecentConversation`), `src/config.py`
- Test: `tests/unit/test_search.py`

**Interfaces:**
- Produces: `Database.search(user_id, query, limit=20, offset=0, after: datetime | None = None, before: datetime | None = None) -> tuple[list[SearchResult], int]` - bounds are UTC instants on the message time (`after` inclusive, `before` exclusive); title matches pass the bounds by the conversation's `updated_at`. `any`-mode hits carry `match_mode="any"` and come after all AND hits, deduplicated.
- Produces: `Database.recent_conversations(user_id: str, after: datetime | None, before: datetime | None, limit: int) -> list[RecentConversation]`; `RecentConversation(conversation_id: str, title: str | None, last_message_at: datetime, first_user_message: str)`, newest activity first, a conversation listed when any of its messages falls in the bounds; excludes trashed conversations.
- Produces: `_fts_query(query: str, any_words: bool = False) -> str`.

- [ ] Step 1: tests -
  - `_fts_query("Matematická olympiáda", any_words=True) == '"Matematic"* OR "olympiá"*'`; `_fts_query("a je kolo", any_words=True) == '"kolo"*'`; `_fts_query("a je", any_words=True) == '"a"* OR "je"*'`; the default mode is unchanged.
  - a message "Matematické olympiády se letos účastní" is found by "Matematická olympiáda" with `match_mode == "any"`; "Rybníček Regál Hornbach" finds a message containing "regál" and "Rybníček" though "Hornbach" is absent.
  - with 3+ AND hits no `any` hit is added; AND hits keep their order ahead of `any` hits.
  - queries `'"10.80"'`, `"pull-ups"`, `"C++"`, `"(x)"`, `"a:b"` return without raising in both modes.
  - bounds: a hit from Nov 10 is excluded by `after=Nov 12`, included by `before=Nov 11`.
  - `recent_conversations`: newest first, bounds respected, another user's and a trashed conversation absent, `first_user_message` is the first user message cut to 200 chars.
- [ ] Step 2: run `pytest tests/unit/test_search.py -q`, expect FAIL.
- [ ] Step 3: implement; the `any` query is a second `MATCH` run only when the AND hits number fewer than `Config.CONVERSATION_SEARCH_FALLBACK_MIN_RESULTS`; total = AND + new `any` hits.
- [ ] Step 4: tests pass; lint, test.
- [ ] Step 5: commit `feat(search): past-chat search falls back to any word with Czech endings trimmed`.

### Task 2: Orphan embeddings and faster scoring

**Files:**
- Create: `migrations/0095_message_embedding_cleanup.py`
- Modify: `src/utils/embeddings.py` (`top_k_similar`), `src/db/models/embeddings.py` (`get_message_rows_for_ids(user_id, message_ids, after=None, before=None)`)
- Test: `tests/unit/test_embeddings_util.py`, `tests/unit/test_embeddings_db.py`

- [ ] Step 1: tests -
  - after the migration, a message embedding whose message is gone is deleted; one of a live message and one of a trashed conversation's message stay; memory embeddings untouched.
  - deleting a message (`delete_message`), truncating after a message, deleting a conversation and purging the trash each remove the embeddings of the deleted messages.
  - `top_k_similar` gives the same order and scores (to 1e-5) as the old `cosine_similarity` for random vectors; a zero vector scores 0.0; a blob of another dimension scores 0.0.
  - `get_message_rows_for_ids` with `after`/`before` drops rows outside the bounds.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement; trigger `AFTER DELETE ON messages BEGIN DELETE FROM embeddings WHERE kind = 'message' AND ref_id = OLD.id; END` (the `UNIQUE(kind, ref_id)` index serves it); the purge deletes `kind = 'message' AND ref_id NOT IN (SELECT id FROM messages)`; rollback drops the trigger. Scoring: `array("f").frombytes`, `math.sumprod`, query norm once.
- [ ] Step 4: tests pass; lint, test.
- [ ] Step 5: commit `feat(search): embeddings go with their message, scored with sumprod`.

### Task 3: The tool - fusion, dates, listing

**Files:**
- Modify: `src/agent/tools/conversation_search.py`, `src/agent/prompt_texts/core.py` (example lines), prompt snapshots
- Test: `tests/unit/test_conversation_search_tool.py`

**Interfaces:**
- Consumes: Task 1 `search(..., after, before)`, `recent_conversations`, `SearchResult.match_mode`; Task 2 `get_message_rows_for_ids(..., after, before)`.
- Produces: `search_conversations(query: str = "", limit: int = 10, after: str | None = None, before: str | None = None) -> str` - dates `YYYY-MM-DD`, both inclusive in the app's timezone (`local_date_start`; `before` becomes the next day's start).

- [ ] Step 1: tests -
  - fusion: a conversation hit by both passes is listed once, first, tagged `(words + meaning)`; keyword-only `(words)`, meaning-only `(meaning)`; one line per conversation; scheduled agents still last.
  - `after="2026-11-12"` hides a Nov 10 hit in both passes; `before="2026-11-11"` keeps it.
  - empty query with `after` lists conversations in range (date, title, ids, first user message); empty query without dates lists the most recent `limit`; the current conversation is not listed.
  - `after="2026-11-14", before="2026-11-12"` and `after="yesterday"` return a tool error with `retriable` true (replaces `test_empty_query_is_rejected`).
  - the log line carries `mode` (`all` / `any` / `list`), `after`, `before`, `ms`.
- [ ] Step 2: run, expect FAIL.
- [ ] Step 3: implement; RRF score `1/(_RRF_K + rank)` per list (rank from 1 within each list after the per-conversation collapse); the docstring names the dates, the listing and "no query + dates for 'what did we talk about yesterday'"; `core.py` example adds `search_conversations(after="2026-11-15")`; `make prompt-snapshots`.
- [ ] Step 4: tests pass; lint, test.
- [ ] Step 5: evals - `make eval-ab BASE=4780fc1a ONLY='cz_episodic_recall,cz_compaction_recall,cz_compaction_user_details,facts_retention_mixed_topics'`; a case passing on BASE and failing on HEAD blocks the commit; report the cost.
- [ ] Step 6: docs - `docs/features/search.md` (fallback, fusion, dates, trigger), `docs/regular-review.md` (zero-keyword-hit share, median `ms`), TODO: remove the two shipped lines, add "Re-measure past-chat search (~Nov 30 2026)"; commit `feat(search): one ranked past-chat list with dates and a recent-chats listing`.
