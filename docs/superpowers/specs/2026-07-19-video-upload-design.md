# Video Upload & Consultation — Design

**Date:** 2026-07-19
**Status:** Approved pending user review

## Goal

Users can upload short videos (< 1 min) from iPhone/Android (record or pick from
library) and consult the AI about their content. Follow-up questions re-access the
video on demand rather than re-sending it every turn. Media attachments are not
permanent storage: videos are retained 7 days, images 30 days.

## Decisions Made

| Question | Decision |
|----------|----------|
| Video length/size | Short clips (< 1 min), up to 100MB per file |
| Follow-up turns | On-demand via `retrieve_file` tool (video never auto-resent in history) |
| Size handling | Raise limit and upload originals as-is; no compression |
| Transport | Reuse existing inline base64-in-JSON chat request (approach A); multipart endpoint (approach B) deferred to TODO.md |
| Retention | Videos 7 days, images 30 days; sweep job + age-derived expiry labeling |

## Architecture Overview

```
Phone → base64 in chat JSON → Flask validation → blob store (files.db)
                                       ↓
                    Gemini Files API upload (ACTIVE poll)
                    file_uri + expiry cached in kv_store
                                       ↓
              current turn: {"type": "media", "file_uri", "mime_type"} block
              later turns:  history metadata only → retrieve_file on demand
```

Server→Gemini must use the Gemini Files API regardless of transport: Gemini's
inline request limit is ~20MB, and even short phone clips exceed it. The
`google-genai` client is already a dependency (image generation).

## 1. Upload Pipeline & Agent Integration

### Frontend

- `UPLOAD_ALLOWED_TYPES` (web/src/config.ts) gains `video/mp4`, `video/quicktime`,
  `video/webm`.
- File input `accept` gains `video/*` — on iOS/Android this offers both camera
  capture and library picker.
- Per-type size limits: videos 100MB (`UPLOAD_MAX_VIDEO_FILE_SIZE_BYTES`), all
  other types stay at 20MB.
- Pending-file preview: chip with video icon, filename, size. No client-side
  thumbnail generation.
- Videos ride the existing base64 chat request (batch mode already has XHR
  upload progress; streaming mode shows indeterminate progress).

### Backend validation & storage

- `MIME_TYPE_ALIASES` (src/utils/files.py) gains the three video types with
  their libmagic detections (`.mov` → `video/quicktime`, `.mp4` → `video/mp4`,
  `.webm` → `video/webm`).
- New `Config.MAX_VIDEO_FILE_SIZE` (default 100MB); per-type limit enforcement
  in file validation. `MAX_REQUEST_SIZE` (250MB) already covers one 100MB video
  base64-encoded (~133MB).
- Video bytes stored in the existing blob store (`files.db`) like images.

### Server → Gemini (Files API bridge)

- Before the agent runs, each video in the *current* message is uploaded to the
  Gemini Files API and polled until `ACTIVE` (video processing takes seconds).
- `file_uri` + expiry (48h) cached in `kv_store`, key derived from
  `message_id:file_index`. Repeat turns within 48h reuse the URI without
  re-uploading.
- `_build_message_content()` (src/agent/agent.py) emits
  `{"type": "media", "file_uri": ..., "mime_type": ...}` for videos in the
  current turn only.

### Follow-up turns (on-demand)

- History messages never include video content blocks. The history formatter
  lists the video in file metadata (`"type": "video"`, `id` =
  `"message_id:file_index"`).
- System prompt: instruct the model to call `retrieve_file` when a follow-up
  needs to look at the video again, and explain the retention policy.
- `retrieve_file` (src/agent/tools/file_retrieval.py) extended for videos:
  fetch blob → reuse cached `file_uri` or re-upload to Files API → return a
  media block in the tool result (same pattern as existing image blocks).

**Risk (spike early):** media blocks with `file_uri` inside ToolMessage content
must serialize correctly through `langchain-google-genai`. Images already work
this way; if `file_uri` blocks don't, fallback is the tool returning a marker
that the graph turns into a content block on the next model call.

## 2. Retention & Cleanup

### Policy

- `VIDEO_RETENTION_DAYS` = 7, `IMAGE_RETENTION_DAYS` = 30 (config).
- Applies to all video/image attachments, including generated images.
  PDF/text attachments are unaffected.

### Sweep job

- Daily sweep: find messages older than the retention window whose `files`
  metadata contains matching MIME types; delete full-size blobs from `files.db`
  and stale Gemini `file_uri` cache entries from `kv_store`.
- **Thumbnails are kept** — small, and old conversations still render a visual
  placeholder.
- Runs on a daemon thread with an hourly tick; a `kv_store` last-run timestamp
  claim ensures only one of the 4 gunicorn workers sweeps per day. Deletes are
  idempotent, so a worker race is harmless. (Multi-worker rule: no module-level
  coordination state.)

### Signaling expiry to the LLM

- No "deleted" flag is written. Expiry is age-based, so the history formatter
  computes it from the message timestamp: expired files get `"expired": true`
  plus a short note ("no longer retrievable — videos are kept 7 days").
- `retrieve_file` checks age + blob existence and returns a clear error
  ("This file has been cleaned up. Videos are retained for 7 days.") — correct
  even before the sweep has physically deleted the blob.

### Signaling expiry to the user

- File endpoint returns **410 Gone** for expired files.
- Attachment chip/lightbox renders an "expired" state (grayed chip; image
  thumbnails remain visible).

## 3. UI/UX, Error Handling, Testing

### Viewing videos

- Sent videos render as `<video controls preload="metadata">` against the
  existing file endpoint.
- The file route gains HTTP **Range request** support (byte-slicing of the blob)
  — iOS Safari requires it for video playback.
- `simplify_mime_type()` (src/agent/history.py) learns `"video"`.

### Upload progress (includes existing mobile layout bug)

- Known bug: the `.upload-progress` strip (input.css:323-377) breaks the input
  box layout on mobile. Reproduce at mobile viewport in Playwright first
  (TDD), then fix the CSS.
- Behavior unchanged otherwise: batch mode shows real percentage (XHR),
  streaming mode indeterminate.
- New "Processing video…" phase after upload completes, covering the Gemini
  Files API upload + ACTIVE poll so the bar doesn't appear stuck.

### Error handling

- Oversized/wrong-type file → existing toast path; message states the 100MB
  video limit.
- Files API upload/processing failure → agent receives tool-context error and
  informs the user; message + video persist, so retry = re-ask.
- Files API 48h expiry mid-conversation → `retrieve_file` re-uploads from blob
  store transparently (until retention expiry → clear "cleaned up" error).

### Testing

- **Unit:** video MIME/size validation; history expiry labeling (both
  windows); sweep selection logic; Range header slicing.
- **Integration:** chat route with small fixture video (mocked `google-genai`
  Files API); `retrieve_file` video + expired paths; 410 endpoint.
- **E2E:** upload tiny fixture video via UI with mock server; upload-progress
  layout assertions at desktop and mobile viewports.
- **TDD:** failing mobile-viewport test for the progress-layout bug before the
  CSS fix.

## Deferred (record in TODO.md)

- Approach B: multipart streaming upload endpoint — if memory pressure from
  base64 JSON bodies or >100MB clips become real problems.
- Video poster-frame thumbnails (needs ffmpeg).
