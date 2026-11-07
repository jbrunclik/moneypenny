# Conversation Files in the Code Sandbox + PDF Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `execute_code` can work on the conversation's uploaded files, and the sandbox can read PDFs (text, words with coordinates, vector lines, tables, page renders) and says which pages have no text.

**Architecture:** One shared loader resolves a history file id (`message_id:file_index`) to bytes with the same ownership, conversation and retention checks `retrieve_file` has today; `retrieve_file` moves onto it. `execute_code` gains an optional `files` argument: each listed file is loaded and copied into `/work/attachments/` before the code runs, and the result lists the paths. The sandbox image gains `pypdf` + `pdfplumber` and a preinstalled `pdf_overview()` helper that reports per-page content and names the pages that came back empty (scanned).

**Tech Stack:** Python 3.14, LangChain `@tool`, llm-sandbox (`session.copy_to_runtime`), Docker image `docker/code-sandbox/`, pypdf, pdfplumber (pdfminer.six + pypdfium2 for renders), pytest, the eval harness (`evals/run.py`).

**Spec:** `docs/superpowers/specs/2026-10-25-thorough-turns-and-conversation-facts-design.md` - Part 3 item 2 ("Conversation files in the code sandbox"), plus the empty-page warning folded into that TODO item on Nov 7 2026.

## Global Constraints

- Production daily driver: ordinary turns unchanged - `files` is optional and the tool behaves exactly as today without it.
- The repo is public: no hostnames or infrastructure in docs or commits ("the production host").
- New env vars: `src/config.py` with a default, `.env.example`, and the relevant `docs/features/` page.
- Report the cost of any eval runs.
- Sandbox security unchanged: no network, same limits; files only come from the current user's current conversation.
- Permissive licences only in the image (no AGPL: not PyMuPDF).

## Review Focus

1. A file id from another conversation or another user's message - refused before anything is copied, same message as `retrieve_file`.
2. An expired attachment (30-day retention) - refused with the retention note, code not run.
3. Two attachments with the same name (`plan.pdf` twice) - both copied, distinct paths, and the result says which is which.
4. A file name with path tricks (`../../etc/passwd`, `/abs.pdf`, empty) - lands as a safe basename inside `/work/attachments/`.
5. A PDF whose pages are all scanned images - `pdf_overview` says no page has text and points to rendering pages to look at them, instead of printing nothing.

---

### Task 1: Shared conversation-file loader

**Files:**
- Create: `src/agent/tools/conversation_files.py`
- Modify: `src/agent/tools/file_retrieval.py` (use the loader; behaviour unchanged)
- Test: `tests/unit/test_conversation_files.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class ConversationFile: file_id: str; name: str; mime_type: str; data: bytes`
- Produces: `load_conversation_file(message_id: str, file_index: int) -> ConversationFile | str` - a `str` is a ready `tool_error(...)` JSON, worded exactly as `retrieve_file`'s errors today (no context, conversation not found, message not found, other conversation, index out of range, expired with `retention_note`, data not found).
- Produces: `parse_file_id(file_id: str) -> tuple[str, int] | None` - `"msg-abc:2"` -> `("msg-abc", 2)`; no colon, empty id or non-integer / negative index -> `None`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_conversation_files.py` (use the `test_database`, `test_user` fixtures and `set_conversation_context`, as `tests/unit/test_file_retrieval.py` does; store blobs with `save_file_to_blob_store`):
  - `test_parse_file_id` - `"m1:0"` -> `("m1", 0)`; `"m1"`, `":1"`, `"m1:x"`, `"m1:-1"` -> `None`.
  - `test_loads_a_file_of_the_current_conversation` - bytes, name and mime type round-trip.
  - `test_refuses_a_message_of_another_conversation` - returns a str containing `"does not belong to this conversation"`.
  - `test_refuses_an_expired_attachment` - message `created_at` 31 days back, PDF -> str containing `"cleaned up"`.
  - `test_index_out_of_range_names_the_file_count`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/unit/test_conversation_files.py -n0` - Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the loader by moving the checks and `_load_file_data` out of `retrieve_file`; `retrieve_file` keeps its signature and calls `load_conversation_file`, then `_build_file_content` as before.
- [ ] **Step 4: Run** the new tests plus `tests/unit/test_file_retrieval.py tests/unit/test_retrieve_file_limits.py` - Expected: all PASS (the existing ones prove behaviour is unchanged).
- [ ] **Step 5: Commit** `refactor(files): one loader for conversation files (retrieve_file uses it)`.

### Task 2: `execute_code(files=[...])` copies attachments into `/work/attachments/`

**Files:**
- Modify: `src/agent/tools/code_execution.py` (new `files` argument, copy step, result field, tool description)
- Modify: `src/config.py` (+ `.env.example`, `docs/features/agent-tools.md`): `CODE_SANDBOX_MAX_ATTACHMENTS: int` default `5`
- Modify: `tests/fixtures/prompt_snapshots/*` via `make prompt-snapshots`
- Test: `tests/unit/test_code_execution.py`

**Interfaces:**
- Consumes: `parse_file_id`, `load_conversation_file`, `ConversationFile` (Task 1).
- Produces: `execute_code(code: str, files: list[str] | None = None) -> str` - unchanged without `files`.
- Produces: `_attachment_path(name: str, taken: set[str]) -> str` - `/work/attachments/<safe basename>`; strips directories and leading dots, falls back to `file`, and suffixes `-2`, `-3`... before the extension on collision (`plan.pdf`, `plan-2.pdf`).
- Produces: result JSON field `"attachments": [{"file_id": str, "path": str, "name": str, "size": int}]` (present only when `files` was given).

- [ ] **Step 1: Write the failing tests** (mock the pooled session with a `MagicMock` exposing `copy_to_runtime` and `run`; patch `load_conversation_file`):
  - `test_files_are_copied_before_the_code_runs` - `copy_to_runtime` called with a host temp path and `/work/attachments/plan.pdf` before `run`; result `attachments[0] == {"file_id": "m1:0", "path": "/work/attachments/plan.pdf", "name": "plan.pdf", "size": 3}`.
  - `test_a_file_that_cannot_be_loaded_stops_the_run` - loader returns an error str -> that error returned, `run` never called.
  - `test_a_malformed_file_id_is_refused` - `"nonsense"` -> error naming the expected `message_id:file_index` format, `run` not called.
  - `test_more_files_than_the_limit_are_refused` - 6 ids with the default limit 5 -> error naming the limit, nothing copied.
  - `test_attachment_paths_are_safe_and_distinct` (on `_attachment_path`): `"../../etc/passwd"` -> `/work/attachments/passwd`; `".env"` -> `/work/attachments/env`; `""` -> `/work/attachments/file`; `"plan.pdf"` twice -> `plan.pdf`, `plan-2.pdf`.
  - `test_without_files_nothing_changes` - no `copy_to_runtime` call, no `attachments` key.
  - `test_files_over_the_size_limit_are_refused` - `ConversationFile` with `len(data) > Config.MAX_FILE_SIZE_BYTES` -> error, nothing copied.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/unit/test_code_execution.py -n0` - Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Validate ids and the count first, load every file, then (inside the pooled session, before `session.run`) write each to a host temp file and `session.copy_to_runtime(tmp, path)` (llm-sandbox creates the parent directory), deleting the temp file in `finally`. Tool description: a `files` section - "list file ids from the history metadata (`message_id:file_index`); they are copied to `/work/attachments/` (paths in the result's `attachments`) before your code runs; use this to measure, parse or convert an uploaded file - you cannot open conversation files any other way".
- [ ] **Step 4: Run** the tests, then `make prompt-snapshots` and `.venv/bin/python -m pytest tests/unit/test_prompt_snapshots.py tests/unit/test_any_ratchet.py -n0` - Expected: PASS; the snapshot diff shows only `execute_code`.
- [ ] **Step 5: Commit** `feat(sandbox): execute_code can work on the conversation's uploaded files`.

### Task 3: PDF library and `pdf_overview()` in the sandbox image

**Files:**
- Modify: `docker/code-sandbox/Dockerfile` - add `pypdf pdfplumber` to the pip list; `COPY sandbox_helpers.py /opt/helpers/sandbox_helpers.py`; `ENV PYTHONPATH=/opt/helpers`; label `moneypenny.version=1.2`
- Create: `docker/code-sandbox/sandbox_helpers.py`
- Modify: `src/agent/tools/code_execution.py` (library list and a "Reading PDFs" section in the tool description), then `make prompt-snapshots`
- Test: `tests/integration/test_code_sandbox_pdf.py` (Docker-only, skipped like `test_code_sandbox_office_files.py` via `_sandbox_runnable()`)

**Interfaces:**
- Produces (inside the sandbox): `from sandbox_helpers import pdf_overview` - `pdf_overview(path: str) -> str`, also printing what it returns. Per page: number, size in points, characters of text, words, lines + rects (vector drawing count), tables found by pdfplumber. Ends with exactly one of:
  - `"Every page has text."`
  - `"No text on pages 2-3, 7 (scanned or drawn as images): render them with pdfplumber page.to_image(resolution=150).save(...) and look at them."` (ranges compressed; `"No page has text"` variant when all are empty).

- [ ] **Step 1: Write the failing Docker test** `test_pdf_overview_names_the_pages_without_text`: in one `execute_code` call, build a 3-page PDF with reportlab (page 1 text "Living room 4.20 m", page 2 blank, page 3 a drawn rectangle only) at `/work/t.pdf`, then `print(pdf_overview('/work/t.pdf'))` and `import pdfplumber, pypdf`. Assert `success`, `"No text on pages 2-3"` in stdout, `"Living room"` extracted by `pdfplumber.open(...).pages[0].extract_text()`. Second test `test_pdf_overview_on_a_fully_scanned_pdf`: a 2-page PDF with no text at all -> stdout contains `"No page has text"` and the render hint.
- [ ] **Step 2: Run** `make sandbox-image && .venv/bin/python -m pytest tests/integration/test_code_sandbox_pdf.py -n0` - Expected: FAIL (`ModuleNotFoundError: sandbox_helpers`). Quit Docker Desktop afterwards if nothing else needs it.
- [ ] **Step 3: Implement** `sandbox_helpers.pdf_overview` with pdfplumber (`page.chars`, `page.extract_words()`, `page.lines`, `page.rects`, `page.find_tables()`) and a small range-compressing helper; add the Dockerfile lines; update the tool description ("PDF: `pypdf`, `pdfplumber` - start with `from sandbox_helpers import pdf_overview; pdf_overview(path)`; words carry coordinates (`extract_words()`), drawings are `page.lines`/`page.rects`; render a page with `page.to_image(resolution=150)`").
- [ ] **Step 4: Run** `make sandbox-image`, the Docker test, then `make prompt-snapshots` and the snapshot test - Expected: PASS.
- [ ] **Step 5: Commit** `feat(sandbox): PDF reading in the sandbox, with a per-page overview naming empty pages`.

### Task 4: Eval - a PDF from an earlier turn, measured in the sandbox

**Files:**
- Modify: `evals/run.py` - a history entry may carry `files: [<fixture path>]`; when any does, the case's history is stored with `db.add_message(..., files=...)` + `save_file_to_blob_store`, and the history sent to the agent is built with `src.agent.history.enrich_history` over the stored messages (so it carries the `files` metadata ids exactly as production does)
- Create: `evals/fixtures/floor_plan.pdf` (generate once with reportlab: two rooms drawn as rectangles with dimension labels "Room A 4.20 x 3.50 m", "Room B 3.10 x 2.80 m", plus a scale bar) and `evals/cases/sandbox_pdf_floor_plan.yaml`
- Test: `tests/unit/test_eval_harness.py` (a case with a history file loads; the built history carries `files` metadata)

**Interfaces:**
- Consumes: `execute_code(files=...)` (Task 2), `pdf_overview` (Task 3).

- [ ] **Step 1: Write the failing harness test** `test_history_files_are_stored_and_listed` - a case with `history: [{role: user, content: "Here is our flat", files: [fixtures/floor_plan.pdf]}, {role: assistant, content: "Got it."}]` -> the history passed to the agent has a user message whose metadata `files[0]["id"]` matches `"<message_id>:0"`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/unit/test_eval_harness.py -n0` - Expected: FAIL.
- [ ] **Step 3: Implement** the harness change and the case: user (current turn): "From the floor plan I sent earlier, compute the total floor area of both rooms to two decimals." Expect: `required_tools: [execute_code]`; `forbidden_arg_patterns: {}`; rubric: total 23.38 m² (14.70 + 8.68), says it read the plan, no hedged guess; `max_tool_rounds: 4`. `requires: [docker]` if the harness supports `requires` for Docker (it skips otherwise).
- [ ] **Step 4: Run** the harness test, then `PYTHONPATH=. .venv/bin/python evals/run.py --only sandbox_pdf_floor_plan` three times - Expected: PASS 3/3; report the cost. Check in the run that `execute_code` was called with `files`.
- [ ] **Step 5: Commit** `test(evals): a floor plan from an earlier turn is measured in the sandbox`.

### Task 5: Docs, TODO, deploy

**Files:**
- Modify: `docs/features/agent-tools.md` (execute_code: `files`, `/work/attachments/`, PDF libraries, `pdf_overview`), `docs/features/conversation-facts.md` or the spec's rollout notes if they track part (2), `TODO.md` (mark part (2) shipped inside the Thorough turns entry; next is part (3))

- [ ] **Step 1:** Update the docs and TODO as listed.
- [ ] **Step 2:** `make lint` and `make test` green (backend + tool change; no web or API change).
- [ ] **Step 3: Commit** `docs: sandbox files and PDF reading`, push, deploy (`make update` on the production host) **and rebuild the sandbox image there once** (`make sandbox-image` - deploys do not rebuild it), then check `docker images` shows label version 1.2 and one live `execute_code` with a PDF works.
