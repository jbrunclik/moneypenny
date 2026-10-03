# File Handling

Files users attach (paste, compression, upload progress, thumbnails, video) and how the agent reads them back (`retrieve_file`), plus copy-to-clipboard. Files the agent produces are covered in [Image Generation](image-generation.md) and [Code Execution Sandbox](code-execution.md).

## File Retrieval Tool

The `retrieve_file` tool allows the LLM to access any file from the conversation history using IDs from history metadata.

**Tool signature:**
```python
retrieve_file(
    message_id: str,      # Message ID from history metadata (required)
    file_index: int = 0,  # File index within the message
) -> str | list[dict]
```

**File IDs in history metadata:**
Each user message with files includes a `files` array in its metadata:
```json
{"files": [{"name": "photo.jpg", "type": "image", "id": "msg-abc123:0"}]}
```
The `id` format is `"message_id:file_index"` which maps directly to the tool parameters.

**Use cases:**
- Analyze or describe an image from earlier in the conversation
- Compare multiple uploaded files across messages
- Use a historical image as a reference for image generation
- Re-read a document that was uploaded earlier

**Size handling** (everything returned is resent inline on each later model call in the turn, and Gemini's inline request limit is ~20 MB):
- Images are downscaled to `IMAGE_REFERENCE_MAX_EDGE_PX` (2048) before being returned inline.
- Videos always go through the Gemini Files API (`media` block with `file_uri`). Images and PDFs above `GEMINI_INLINE_FILE_MAX_BYTES` (8 MB) do too, since a 20 MB PDF upload is ~27 MB as base64.
- Text files are truncated to `RETRIEVE_FILE_TEXT_MAX_CHARS` (200k chars, ~50k tokens), with a note giving the full length.
- Other binary files return metadata only; base64 text is unreadable to the model and costs tokens in proportion to its size.
- Known gap: files attached to the *current* message are still sent inline at full size (`src/agent/message_content.py`), so many large uploads in one message can still exceed the limit.

**Security:**
- Verifies message belongs to the current conversation
- Verifies conversation belongs to the current user
- Returns error for unauthorized access attempts

## Downloading Files

`downloadFile` and `openFileInNewTab` in [file-actions.ts](../../web/src/core/file-actions.ts) fetch the file as a blob. Desktop gets an `<a download>` click (or a new tab for previews).

**Pitfall - the installed iPhone app (Oct 2026):** it has no download manager, so `<a download>` on a blob URL does nothing, and `window.open(blob)` opens an in-app browser that can't read the app's blob URLs (a blank sheet). Touch devices that can share files (`pointer: coarse` + `navigator.canShare({files})`) therefore get the share sheet ("Save to Files"), and in the installed app a non-PDF file-name tap does the same (PDFs use the inline viewer). iOS only opens the sheet within a tap; when the fetch outlasts that window `navigator.share` throws `NotAllowedError` and an info toast offers **Save** for a fresh tap. `AbortError` (user cancelled) is silent. Tests: [file-download-share.test.ts](../../web/tests/unit/file-download-share.test.ts).

## Clipboard Paste

Users can paste screenshots directly from the clipboard into the message input (Cmd+V / Ctrl+V).

### How it works

1. A `paste` event listener on the textarea detects clipboard content
2. If clipboard contains image files, they're extracted and processed
3. Images are renamed with timestamp-based names (`screenshot-YYYY-MM-DDTHH-MM-SS.png`)
4. Uses the existing `addFilesToPending()` flow for validation and preview
5. Text paste is handled normally by the browser (not intercepted)

### Supported Formats

- PNG, JPEG, GIF, WebP images
- Works with screenshots (Cmd+Shift+4 on Mac, PrtScn on Windows)
- Works with copied images from other applications

### Implementation Details

- `handlePaste()` in [MessageInput.ts](../../web/src/components/MessageInput.ts) handles the paste event
- Only images are processed; non-image files and text are passed through
- `preventDefault()` is only called when images are present (to avoid interfering with text paste)
- `addFilesToPending()` in [FileUpload.ts](../../web/src/components/FileUpload.ts) handles validation and base64 conversion

### Key Files

- [MessageInput.ts](../../web/src/components/MessageInput.ts) - `handlePaste()` function
- [FileUpload.ts](../../web/src/components/FileUpload.ts) - `addFilesToPending()` for file processing

### Testing

- Unit tests: `handlePaste` describe block in [message-input.test.ts](../../web/tests/unit/message-input.test.ts)
- E2E tests: "Chat - Clipboard Paste" describe block in [clipboard.spec.ts](../../web/tests/e2e/chat/clipboard.spec.ts)

## Client-side Image Compression

Images are downscaled and re-encoded at **attach time** (Aug 2026) in [image-compression.ts](../../web/src/utils/image-compression.ts), wired into `addFilesToPending` in [FileUpload.ts](../../web/src/components/FileUpload.ts) — full-resolution phone photos (4–8MB) become a few hundred KB before hitting the server, the blob store, and the LLM.

- Long edge capped at `IMAGE_COMPRESSION_MAX_EDGE_PX` (2048px), JPEG re-encode at `IMAGE_COMPRESSION_JPEG_QUALITY` (0.85). PNG stays PNG when transparency is detected (sampled alpha scan); GIF (animation) and SVG are skipped; files under `IMAGE_COMPRESSION_MIN_BYTES` are sent as-is.
- **Fail-open**: any decode/encode failure (e.g. HEIC in Chrome, where `createImageBitmap` can't decode it) silently sends the original file.
- The compressed version is used only when it saves ≥ `IMAGE_COMPRESSION_MIN_SAVINGS_RATIO` (10%); JPEG re-encodes get a matching `.jpg` filename.
- Compression runs **before** the size-limit check, so an oversized photo that compresses under the limit is accepted.
- Video compression is deferred (see TODO.md) — videos upload unmodified.
- Tests: [image-compression.test.ts](../../web/tests/unit/image-compression.test.ts) (decision logic + jsdom fallback), "Client-side Image Compression" in [attachments.spec.ts](../../web/tests/e2e/chat/attachments.spec.ts) (real-browser end-to-end via request-body inspection).

## Upload Progress

When sending messages with file attachments, upload progress renders as a conic-gradient ring inside the send/stop button. It deliberately does NOT render as an element in the input area's document flow: an earlier strip-above-the-input implementation grew/shrank the input area when it appeared and disappeared, visibly jumping the whole layout twice per send on mobile.

### How it works

1. When files are attached and the user clicks send, `showUploadProgress()` is called
2. In batch mode: Uses XMLHttpRequest with `upload.onprogress` to track actual upload progress (0-100%), shown as a determinate ring sweep
3. In streaming mode: `showUploadProgress(true)` shows the indeterminate spin, since fetch doesn't support upload progress events
4. At 100% the ring switches to the indeterminate spin (`.processing`) while the server processes the upload
5. `hideUploadProgress()` is called in the finally block to ensure cleanup

### UI Behavior

- Ring renders inside the button bounds (`::after` with a mask that punches out the center) - zero layout shift when the upload state toggles
- Button classes: `.uploading` (ring visible, driven by the `--progress` custom property) and `.processing` (indeterminate spin)
- Progress is announced via the button's `aria-label` ("Uploading 75%", "Processing upload")
- The stop icon stays visible inside the ring (uploads remain cancellable); the `stop-pulse` animation is suppressed while uploading
- `--progress` is registered via `@property` so the sweep animates smoothly between updates (snaps in browsers without support)

### Implementation Details

- `requestWithProgress<T>()` in [api/http.ts](../../web/src/api/http.ts) wraps XHR for upload progress tracking
- `chat.sendBatch()` accepts optional `onUploadProgress` callback, uses XHR when files are present
- `showUploadProgress(indeterminate?)`, `hideUploadProgress()`, `updateUploadProgress()` in [MessageInput.ts](../../web/src/components/MessageInput.ts)
- `uploadProgress` state in Zustand store (not currently used for display, but available for future use)
- CSS styles in [buttons.css](../../web/src/styles/components/buttons.css) ("Upload Progress Ring" section)

### Key Files

- [api/http.ts](../../web/src/api/http.ts) - `requestWithProgress()` XHR wrapper
- [MessageInput.ts](../../web/src/components/MessageInput.ts) - Progress UI functions
- [batch-send.ts](../../web/src/core/batch-send.ts) / [stream-send.ts](../../web/src/core/stream-send.ts) - Integration in `sendBatchMessage()` and `sendStreamingMessage()`
- [buttons.css](../../web/src/styles/components/buttons.css) - `.uploading` / `.processing` ring styles

### Testing

- Unit tests: "Upload Progress UI Functions" describe block in [message-input.test.ts](../../web/tests/unit/message-input.test.ts)
- E2E tests: "Chat - Upload Progress" describe block in [attachments.spec.ts](../../web/tests/e2e/chat/attachments.spec.ts)

## Background Thumbnail Generation

Thumbnails are generated in background threads to avoid blocking chat requests.

### How it works

1. User uploads image with message
2. `mark_files_for_thumbnail_generation()` checks each image:
   - Small images (<100KB): Original data used as thumbnail, status set to "ready"
   - Large images: Status set to "pending"
3. Message saved to database with file statuses
4. `queue_pending_thumbnails()` queues background generation for pending files
5. ThreadPoolExecutor (2 workers) generates thumbnails asynchronously
6. Thumbnail saved to blob store (see [Database](../architecture/database.md#blob-storage) section)
7. Frontend polls `/api/messages/<id>/files/<idx>/thumbnail`:
   - Returns 200 with thumbnail data when ready
   - Returns 202 with `{"status": "pending"}` when still generating
   - Falls back to full image if generation failed

### Server Death Recovery

If the server dies while generating thumbnails, pending thumbnails would be stuck forever. The system handles this with lazy recovery:
- When thumbnail endpoint receives a request for a "pending" thumbnail older than 60 seconds, it regenerates synchronously
- This one-time cost recovers the thumbnail without needing a startup job

### Configuration

- `THUMBNAIL_SKIP_THRESHOLD_BYTES`: Skip thumbnails for images under this size (default: 100KB)
- `THUMBNAIL_WORKER_THREADS`: Number of background workers (default: 2)
- `THUMBNAIL_RESAMPLING`: BILINEAR (fast) or LANCZOS (quality) (default: BILINEAR)
- `THUMBNAIL_STALE_THRESHOLD_SECONDS`: Recovery threshold for stuck thumbnails (default: 60s)

### User Uploads vs Tool-Generated Images

- **User uploads**: Use background generation (`mark_files_for_thumbnail_generation()` → `queue_pending_thumbnails()`)
- **Tool-generated images**: Use synchronous generation via `process_image_files_sync()` since the LLM response is already complete

### Key Files

- [background_thumbnails.py](../../src/utils/background_thumbnails.py) - ThreadPoolExecutor, queue functions, `generate_and_save_thumbnail()` shared helper
- [images.py](../../src/utils/images.py) - `generate_thumbnail()`, `process_image_files_sync()` for tool outputs
- [routes/files.py](../../src/api/routes/files.py) - Thumbnail endpoint with 202 response and stale recovery
- [api/files.ts](../../web/src/api/files.ts) - `fetchThumbnail()` with polling and exponential backoff
- [config.ts](../../web/src/config.ts) - Frontend polling configuration

### Testing

- Unit tests: [test_background_thumbnails.py](../../tests/unit/test_background_thumbnails.py)
- Integration tests: [test_routes_thumbnails.py](../../tests/integration/test_routes_thumbnails.py)

## Copy to Clipboard

The app provides copy-to-clipboard functionality at two levels. (User-facing summary: [UI Features](ui-features.md#copy-to-clipboard).)

### Features

1. **Message-level copy**: Copy button in message actions copies the entire message content
2. **Inline copy**: Individual copy buttons on code blocks and tables

### Rich Text Support

- Copies both HTML and plain text formats using the Clipboard API
- When pasted into rich text editors (Word, Google Docs, etc.), formatting is preserved
- Tables are copied as HTML tables (preserves structure when pasted)
- Code blocks are copied as plain text (no syntax highlighting in clipboard)
- Plain text fallback for applications that don't support rich text

### Message-Level Copy Behavior

- Excludes file attachments, thinking/tool traces, inline copy buttons, and language labels
- Available on both user and assistant messages
- Shows checkmark feedback for 2 seconds after successful copy

### Inline Copy Buttons

- Appear on hover (desktop) or always visible at 70% opacity (touch devices)
- Code blocks: Shows language label (e.g., "python") in top-left corner
- Tables: Wrapped in a bordered container for visual distinction
- Copy button positioned in top-right corner of each block

### Implementation Details

- `copyWithRichText()` in [file-actions.ts](../../web/src/core/file-actions.ts) handles dual-format clipboard writing
- `tableToPlainText()` converts tables to tab-separated values for plain text
- Uses `ClipboardItem` API with fallback to `writeText()` for older browsers
- Markdown renderer in [markdown.ts](../../web/src/utils/markdown.ts) wraps code/tables in `.copyable-content` containers

### Key Files

- [markdown.ts](../../web/src/utils/markdown.ts) - Custom renderers for code blocks and tables with copy button injection
- [file-actions.ts](../../web/src/core/file-actions.ts) - `copyMessageContent()`, `copyInlineContent()`, `copyWithRichText()`
- [messages.css](../../web/src/styles/components/messages.css) - `.copyable-content`, `.inline-copy-btn`, `.code-language` styles

### Testing

- E2E tests: "Chat - Copy to Clipboard" describe block in [clipboard.spec.ts](../../web/tests/e2e/chat/clipboard.spec.ts)

## Video Uploads

Users can upload short videos (iPhone/Android camera or library) and consult the AI about their content.

### How it works

1. **Upload**: `video/mp4`, `video/quicktime`, `video/webm` up to 100MB (`MAX_VIDEO_FILE_SIZE`) ride the normal base64 chat request; the file input's `accept` offers camera capture on mobile. Magic-byte validation has a container-signature fallback (`ftyp`/EBML) because some libmagic builds detect video only via `from_file`, not `from_buffer`.
2. **Gemini Files API bridge**: Gemini's inline request limit is ~20MB, so videos are uploaded to the Files API before the agent runs (`attach_gemini_file_uris()` in [gemini_files.py](../../src/agent/gemini_files.py), called when the user message is saved), polled to `ACTIVE`, and sent as `{"type": "media", "file_uri", "mime_type"}` blocks. The `file_uri` (48h lifetime) is cached in `kv_store` under user `_system`, namespace `gemini_files`, key `message_id:file_index`, TTL 47h.
3. **Follow-up turns**: the video is attached only on its upload turn. History carries metadata only (`"type": "video"` + `retrieve_file` id); the system prompt tells the model to call `retrieve_file`, which reuses the cached URI or re-uploads from blob storage.
4. **Upload failure**: `attach_gemini_file_uris` never raises — the message content gets a text notice instead so the model can tell the user.

### File Retention

Attachments are not permanent storage: **videos are kept 7 days, images and all other files 30 days** (`VIDEO_RETENTION_DAYS` / `IMAGE_RETENTION_DAYS` / `FILE_RETENTION_DAYS`). Implemented in [file_retention.py](../../src/utils/file_retention.py):

- **Production**: a daily systemd timer runs [scripts/cleanup_files.py](../../scripts/cleanup_files.py) (installed by `make deploy`), consistent with the other scheduled jobs - see [Scheduled Jobs](../architecture/scheduled-jobs.md).
- **Development**: the dev scheduler loop calls `run_file_cleanup_if_due()` (at most one sweep per day, tracked via a `kv_store` stamp under `_system`/`file_cleanup`).
- The sweep deletes full-size blobs and stale Gemini URI cache entries, and purges conversations trashed more than `TRASH_RETENTION_DAYS` ago (see [Trash](ui-features.md#trash)). **Thumbnails are kept** so old conversations still render a placeholder. Runs are idempotent.
- Expiry is *age-derived* everywhere, so behavior is correct even before the sweep runs: history metadata marks files `"expired": true`, `retrieve_file` returns a clear "cleaned up" error, and the file endpoint returns **410 Gone** (`ErrorCode.GONE`).

### Playback

JWT is header-only, so a bare `<video src>` cannot authenticate. Sent videos render as tap-to-load players ([attachments.ts](../../web/src/components/messages/attachments.ts)): an authenticated fetch loads the blob and plays it via an object URL; a 410 renders an "expired" chip. Just-uploaded videos play directly from their local preview URL.

### Configuration

```bash
MAX_VIDEO_FILE_SIZE=104857600   # 100 MB
VIDEO_RETENTION_DAYS=7
IMAGE_RETENTION_DAYS=30
FILE_RETENTION_DAYS=30
```

### Key Files

- [gemini_files.py](../../src/agent/gemini_files.py) - Files API bridge + kv URI cache
- [file_retention.py](../../src/utils/file_retention.py) - retention policy + sweep; [cleanup_files.py](../../scripts/cleanup_files.py) runs it on a timer
- [file_retrieval.py](../../src/agent/tools/file_retrieval.py) - video branch + expiry errors
- [message_content.py](../../src/agent/message_content.py) - `build_message_content()` media blocks
- [chat_turn.py](../../src/api/helpers/chat_turn.py) - `attach_gemini_file_uris()` call site (user message save, both chat modes)
- [routes/files.py](../../src/api/routes/files.py) - 410 Gone gate
- [attachments.ts](../../web/src/components/messages/attachments.ts) - tap-to-load player

### Testing

- Unit: [test_gemini_files.py](../../tests/unit/test_gemini_files.py), [test_file_retention.py](../../tests/unit/test_file_retention.py), video classes in [test_files.py](../../tests/unit/test_files.py), [test_file_retrieval.py](../../tests/unit/test_file_retrieval.py), [test_history.py](../../tests/unit/test_history.py)
- Integration: video/410 classes in [test_routes_chat.py](../../tests/integration/test_routes_chat.py), [test_routes_files.py](../../tests/integration/test_routes_files.py)
- E2E: "Chat - Video Upload" in [attachments.spec.ts](../../web/tests/e2e/chat/attachments.spec.ts); real ffmpeg-generated fixtures in [tests/fixtures/](../../tests/fixtures/)

## See Also

- [Image Generation](image-generation.md) - `generate_image`, image-to-image editing
- [Code Execution Sandbox](code-execution.md) - `execute_code` and its output files
- [API Design](../architecture/api-design.md#two-phase-file-validation) - file validation, magic bytes
- [Database](../architecture/database.md#blob-storage) - Blob storage for files and thumbnails
- [UI Features](ui-features.md) - Input toolbar, file upload UI
