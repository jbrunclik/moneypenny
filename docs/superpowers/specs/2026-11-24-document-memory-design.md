# Document memory - design

Nov 24 2026. Part (1) of the TODO item "Knowledge base, then Projects".

## Intent

Users want a lasting library of their important documents that the agent knows
about in every chat. Jiri's examples: an equity-value waterfall (equity value at
different company valuations) that the agent should bring up when exit scenarios
come up, and key contracts that it can reference later. Each document is stored
with a short summary of **what it contains** and **what to use it for**. When a chat
touches on that, the agent opens the full original and analyses it.

Chat attachments can't do this today. They are deleted after 30 days
(`FILE_RETENTION_DAYS`), `retrieve_file` only reaches the current conversation,
and nothing tells a later chat that the document exists.

## Goals

- The agent saves a document from a chat into a per-user library: a permanent copy
  of the file, plus a title, a summary, a "use for" note and an optional end date.
- Every chat turn carries a short list of the user's documents, so the agent knows
  what exists and when each is relevant without being asked.
- The agent opens a library document on demand and gets the full original: PDFs and
  images natively, Office files as extracted text, the same way as `retrieve_file`.
- Cleanup: documents past their end date are soft-deleted by the nightly job, sit in
  Recently deleted for a recovery window, and are then purged (row and blob). A newer
  version of a document replaces the old one the same way.
- Users can view, download, delete and restore their documents on the Data page.

## Non-goals (v1)

- Chunked passage search / RAG over document text (approach B below). Revisit if a
  user's library approaches the cap.
- Embedding search over the summaries. The full list is injected (bounded by the
  cap), so there is nothing hidden to search for. Add `search_documents` and
  tiered injection, like memories, only once libraries get big.
- Projects (part 2 of the TODO item).
- Uploading documents directly on the Data page. Saving goes through chat, where the
  agent writes the summary. (Builder call, open to revisit.)
- Editing summaries by hand in the UI (memories can't be edited by hand either).

## Anti-goals

- **Silent saving.** Contracts and financials are sensitive, so a document is kept
  only on purpose. The agent saves when the user asks, or offers to save and waits
  for a yes. The background memory review never saves documents.
- **AI judging something "stale" and deleting it.** Cleanup is date-based and
  replacement-based only. Deleting a contract by mistake costs far more than keeping
  one too long.
- **Unbounded per-turn cost.** The injected list must stay small (short summaries,
  an entry cap).

## Approaches considered

- **A. Summary list injected every turn + `open_document` tool (chosen).** It mirrors
  memories: a line per document in the per-turn context, and a tool that returns the
  original. The agent sees the whole document, which is what a waterfall or a
  contract needs, where the answer depends on the whole table or on how clauses
  interact. It costs about one line per document per turn.
- **B. Chunk + embed + passage search (RAG).** It scales to hundreds of long documents
  but gives the agent fragments, which is bad for tables and cross-referenced clauses.
  It's much more code, and family libraries won't be that big. It can be layered
  under A later.
- **C. Store documents as memories with a file attached.** It's the smallest build,
  but it squeezes summaries into memory's 1,000-character entries and defrag, and
  mixes two kinds of thing in one list.

Jiri picked A.

## Decided with Jiri

- Approach A.
- Saving: the agent saves on request, or offers and waits for a yes. Never silently.
- Cleanup = expiry. An optional end date (`valid_until`, a local date, the last day
  the document holds, the same semantics as memories). For contracts the agent takes
  it from the document (term end); otherwise the user gives one, or there is none.
  The nightly job soft-deletes expired documents into Recently deleted, restorable
  until the purge.
- A newer version replaces the old one (the old one is soft-deleted the same way).
- **End dates and replacements are confirmed.** Whenever a save sets `valid_until`
  or `replaces`, the agent states the date and/or the document being replaced
  ("Saving your lease - it ends 2027-06-30 and I'll clear it away after that. OK?")
  and saves only after a yes. Contracts that renew automatically (insurance,
  leases, subscriptions) get no end date. An amendment or annex is its own document,
  never a replacement for the original. A save with neither field goes through on
  the single "keep it".
- **No notification on expiry or purge.** Jiri trusts the agent to set end dates
  carefully; Recently deleted on the Data page is the only safety net. (Push or
  in-chat warnings were considered and declined.)

## Design

### Storage

New table `user_documents` (migration `0103_user_documents`; re-check the highest
number on `main` before committing):

| column | notes |
|---|---|
| `id` | UUID; 8-char short id in prompts, like memories (`memory_ids.py` logic reused) |
| `user_id` | FK users, cascade |
| `title` | short, model-written (<= `DOCUMENT_TITLE_MAX_CHARS`, 80) |
| `summary` | what it contains (<= `DOCUMENT_SUMMARY_MAX_CHARS`, 300) |
| `use_for` | when to use it (<= `DOCUMENT_USE_FOR_MAX_CHARS`, 200) |
| `filename`, `mime_type`, `size_bytes` | from the source attachment |
| `valid_until` | nullable local date |
| `source_conversation_id`, `source_message_id` | provenance; no FK (the conversation may be deleted, the document stays) |
| `created_at`, `updated_at`, `deleted_at` | soft delete like memories |
| `last_opened_at` | instrumentation (see below) |

The file bytes are copied into the existing blob store under the key
`doc/{document_id}`. The message-file retention sweep only touches message keys, so
library copies are not swept. A purge deletes the blob together with the row.

Bounds (all in `src/config.py`, `.env.example`, docs):

- `DOCUMENTS_MAX_ENTRIES` (50, Jiri's call): the cap on live documents per user; a save past it is
  rejected with a message telling the agent to replace or delete one.
- `DOCUMENTS_MAX_TOTAL_BYTES` (200 MB): per-user storage cap.
- A single document is limited by `MAX_FILE_SIZE_BYTES` (already enforced on upload).
- `DOCUMENTS_SOFT_DELETE_RETENTION_DAYS` (30): longer than memories' 7, because a
  wrongly expired contract should be recoverable for a while.

### Agent tools

**`manage_documents(operations)`**: writes inline and reports per-operation results
like `manage_memory` (new ids, or `REJECTED` with a reason). Max ops per call: 5.

- `save`: `file_id` (the `message_id:file_index` id from history metadata, including
  the current message's files), `title`, `summary`, `use_for`, optional
  `valid_until`, optional `replaces` (id of an older version; it is soft-deleted in
  the same transaction). **The file must be in the current conversation** (reuse
  `load_conversation_file` in `conversation_files.py` and its ownership check);
  a document from an older chat is sent again. It must not have expired. The tool
  copies the bytes into the blob store.
- `update`: change `title` / `summary` / `use_for` / `valid_until` of an existing
  document (`""` clears the end date; a past date is rejected, as for memories).
- `delete`: soft delete.

Guards, copied from memory:
- injection scan (`find_injection`) on title, summary and use_for, which are injected
  into every later turn;
- anonymous mode: tool not bound, list not injected;
- autonomous agent runs: only if in `tool_permissions` (both at binding and at call
  time, `check_autonomous_permission`), since an unattended agent reading the web
  must not plant documents. `open_document` is read-only but still exposes private
  files; it follows the same permission rule.
- never in `EXTRACT_ONLY_TOOL_NAMES`.

**`open_document(id)`**: returns the original through the same content builder as
`retrieve_file` (`_build_file_content`): images downscaled, PDFs inline or via the
Gemini Files API above `GEMINI_INLINE_FILE_MAX_BYTES`, Office files through
`office_text_for_model`, text truncated at `RETRIEVE_FILE_TEXT_MAX_CHARS`. The builder
is currently keyed on `message_id`/`file_index` (the Files-API URI cache key and the
file id in Office output). Generalize it to take a cache key / display id so library
documents cache as `doc:{id}`. Sets `last_opened_at`.

### Builder calls (settled in review, Jiri may override)

- Current conversation only for `save` (see above).
- Soft-deleted documents do not count toward `DOCUMENTS_MAX_ENTRIES` but do count
  toward `DOCUMENTS_MAX_TOTAL_BYTES` until purged (the bytes are still stored).
  A restore that would exceed either cap is refused with a message telling the user
  to delete something first.
- Summaries and use_for are written in the language of the document or chat, whichever
  the agent is speaking; no translation.
- The list is injected wherever the memory list is (every non-anonymous chat that
  gets memories, including Sports, Language and agent chats); the tools follow the
  memory tool's binding rules.

### Prompt

- Static instructions (cached prefix, only when the tool is bound): what the library
  is for; offer to save documents that look lasting (contracts, financial models,
  policies, statements) and save only after a yes or an explicit request; write the
  summary for recall ("what is in it", key figures and parties) and `use_for` for
  triggering ("exit scenarios, liquidity planning"); take `valid_until` from a
  contract's term; when a chat matches a document's use, open it before answering
  rather than answering from the summary; on a newer version, save with `replaces`;
  state any end date or replacement and wait for a yes before saving; no end date
  on auto-renewing contracts; an amendment is a separate document.
- Per-turn dynamic context (next to the memory list): one line per live, unexpired
  document:
  `- <short id> | <title> | <filename>, saved <date>[, until <date>] | <summary> | Use for: <use_for>`.
  It is omitted entirely when the user has none. Add a prompt snapshot case in
  `tests/fixtures/prompt_snapshots/`.

### Cleanup

In the nightly job (`scripts/defragment_memories.py`, next to `expire_memories`,
before any LLM work, for all users regardless of the defrag threshold):

1. `expire_documents(today)`: soft-delete documents whose `valid_until < today`.
   Log "Documents expired" with a count.
2. `purge_deleted_documents(DOCUMENTS_SOFT_DELETE_RETENTION_DAYS)`: delete rows and
   their blobs. Log "Documents purged".

An expired document leaves the injected list from the day after its end date, even
before the job runs (filtered by date at read time, like memories). Restoring an
expired document clears its past end date.

### API + Data page

Endpoints (`src/api/routes/documents.py`, Pydantic schemas, OpenAPI, generated TS
types, `web/src/api/documents.ts`):

- `GET /api/documents`: live documents + recently deleted (and the cap)
- `GET /api/documents/<id>/file`: download (owner only)
- `DELETE /api/documents/<id>`: soft delete
- `POST /api/documents/<id>/restore`

Data page (`KVStorePage.ts`): a **Documents** section between Memories and K/V
storage. Each row shows the title, filename and size, summary, "Use for", saved date
and end date, with Download and Delete. There's a Recently deleted list with
Restore, and an EmptyState ("No documents yet", with one line saying to ask the
assistant to save a document from a chat). Reuse the existing memory row patterns,
`btn btn-*-sm` and the raised surfaces; component-prefixed CSS classes
(`kv-doc-*`). Test on desktop and mobile.

### Instrumentation (A8)

- Log lines: "Document saved" (user id, doc id, mime, size, has end date, replaced
  id), "Document opened" (doc id, conversation id), "Document save rejected"
  (reason), "Documents expired" / "Documents purged" (counts). No titles or summaries
  in logs.
- `last_opened_at` column: shows whether saved documents are ever used.
- `docs/regular-review.md` check: documents saved vs opened per user, documents never
  opened after 30 days, rejected saves by reason, total stored bytes.
- TODO.md: re-measure ~Dec 15 2026. Is anything saved, are saved documents opened in
  later chats, and what does the injected list cost per turn.

### Evals

New cases (run with `make eval-smoke` plus these, and report the cost):
- the user shares a fixed-term contract and says "keep this": the agent proposes the
  term end as the end date and asks before saving; after a yes it saves with a
  sensible summary, use_for and valid_until;
- the user shares an auto-renewing contract and says "keep this": saved with no end
  date, no extra question;
- the user shares a document without asking: the agent offers and does not save;
- a seeded library with a waterfall, and the user asks about an exit at a valuation:
  the agent calls `open_document` on it before answering;
- a new version of a saved document: the agent names the replaced document and asks;
  after a yes, saved with `replaces`;
- an amendment to a saved contract: saved as its own document, nothing replaced.

The E2E fake server needs the new tools wired if the E2E fake mirrors tool
signatures (check `tests/e2e_server/`).

### Announcement

`announcements/2026-11-24-document-memory.md` (Czech + English, for the family): you
can ask Moneypenny to keep important documents (contracts, financial overviews) and
it will remember them in later chats; they are on the Data page, and documents with
an end date clear themselves away.

## Left to the builder

- Exact prompt wording (keep the per-turn line short; measure its size in the
  snapshot).
- How the content builder is generalized (cache-key parameter vs a small wrapper).
- Whether `save` on a message file that has already expired gives a specific error.
  It should: "the file was cleaned up, ask the user to send it again".
- Visual details of the Data page section within the existing patterns.
