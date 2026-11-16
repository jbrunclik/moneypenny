# Files the agent can work with (Nov 16 2026)

Short design. Approved in chat ("OK, let's go for it").

## Why

The agent can't point at what it made itself: the history lists uploads' ids,
not its own code outputs or generated images, so "make that image darker" or
"add a column to the xlsx you made" goes wrong. And two everyday kinds of file
are refused at upload: Office documents (xlsx, docx, pptx) and audio (voice
memos).

## Goals

1. **The agent's own files are listed in the history**, with the same
   `message_id:file_index` ids uploads have. The tools already open them by id.
2. **Audio uploads**: m4a (iPhone voice memos), mp3, wav, ogg, flac, aac. Gemini
   hears them natively.
3. **Office uploads**: docx, xlsx, pptx. The agent sees their text in the
   message. The original still goes to the sandbox for edits.

**Non-goals:** legacy .doc/.xls/.ppt; inline audio playback in the chat (an
attachment chip with download, as for other files); YouTube, weather and tool
depth (they stay in TODO).

**Anti-goals:** an uploaded document that crashes or stalls a turn (a corrupt,
password-protected or zip-bomb file must come back as "could not read").
Changing history bytes on every turn (it would break prefix caching).

## Approaches (Office)

- **A. Convert to text on the way to the model** (chosen). Word gets its
  paragraphs and tables, Excel each sheet as a table (values, not formulas),
  PowerPoint each slide's text and notes. "Summarise this" needs no extra step,
  and it works without the sandbox. Cost: python-docx, openpyxl and python-pptx
  in the server's dependencies, plus a length cap.
- **B. Sandbox only.** The message just names the file and says "open it with
  execute_code". Nothing new on the server, but every question costs a code
  run, and nothing works when the sandbox is down.

Chosen A for answering in one step and for not depending on the sandbox.
Layout (merged cells, charts, slide visuals) is lost in the text; the sandbox
still has the original.

## Design

- **History** (`src/agent/history.py`): assistant messages get `files` the same
  way user messages do. The ids are stable, so prefix caching is unaffected.
  Tool docstrings and prompt wording that say "user messages with files" now
  cover replies too.
- **Audio**: allowed types, magic-byte aliases, sent through the Gemini Files
  API like video (`attach_gemini_file_uris`, `retrieve_file`) with a `media`
  block. The ordinary 20 MB limit and 30-day retention (about 40 minutes of a
  voice memo); no special case. *(My call.)*
- **Office**: `src/utils/office_text.py` turns the bytes into Markdown-ish text.
  It is used for the message's file block (`message_content._file_block`) and
  by `retrieve_file`.
  - **Cap:** a new `OFFICE_TEXT_MAX_CHARS` (100 000). Truncation says so and
    points to `execute_code(files=[id])`.
  - **Zip-bomb guard:** the archive's total uncompressed size is checked before
    parsing (`OFFICE_MAX_UNCOMPRESSED_BYTES`, 100 MB).
  - **XML safety:** defusedxml is installed (openpyxl uses it).
  - **Failure:** any failure becomes a text block saying the file could not be
    read, with the id for the sandbox.
- **Validation**: Office files read as zip containers to libmagic; the aliases
  accept the specific type, `application/zip` and `application/octet-stream`.
- **Frontend**: the default allowed-types list, and file chips labelled by type.
- **Config**: `DEFAULT_ALLOWED_FILE_TYPES` gains the new types. Both `.env`
  files set `ALLOWED_FILE_TYPES` explicitly, so that line changes in
  `.env.example` and in both `.env` files (needs the user's OK).
- **Instrument** (A8):
  - an "office text extracted" log line: type, chars, truncated, ms, error;
  - a `role` field on the conversation-file load log, so own-output reuse is
    countable;
  - a regular-review check, and a re-measure in TODO (~Nov 30).
- **Announcement**: Czech and English, covering audio, Office and "make that
  image darker".

## Left to the builder

Exact Markdown shape of the converted text; which audio MIME variants browsers
send (e.g. `audio/x-m4a` vs `audio/mp4`), checked against real files.
