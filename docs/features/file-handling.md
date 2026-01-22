# File Handling

This document covers image generation, code execution, file uploads, clipboard paste, and upload progress features.

## Image Generation

The app can generate images using Gemini's image generation model (`gemini-3-pro-image-preview`).

### How it works

1. **Tool available**: `generate_image(prompt, aspect_ratio, reference_images, history_image_message_id, history_image_file_index)` tool in [tools/image_generation.py](../../src/agent/tools/image_generation.py)
2. **Tool returns JSON**: Returns `{"prompt": "...", "image": {"data": "base64...", "mime_type": "image/png"}}`
3. **LLM appends metadata**: System prompt instructs LLM to include `"generated_images": [{"prompt": "..."}]` in the metadata block
4. **Backend extracts images**: `extract_generated_images_from_tool_results()` in [routes/chat.py](../../src/api/routes/chat.py) parses tool results
5. **Images stored as files**: Generated images are stored as file attachments on the message
6. **Metadata stored in DB**: Messages table has a `generated_images` column (JSON array)
7. **UI shows sparkles button**: A sparkles icon appears in message actions when generated images exist, opening a popup showing the prompt used and the cost of image generation (excluding prompt tokens)

### Aspect Ratios

Supported: `1:1` (default), `16:9`, `9:16`, `4:3`, `3:4`, `3:2`, `2:3`

### Image-to-Image Editing

Users can upload images and ask the LLM to modify them. The uploaded images are passed to the Gemini image generation API as reference images.

**How it works:**
1. User uploads an image and requests a modification (e.g., "make me look like a wizard")
2. LLM recognizes this as an image editing task
3. LLM calls `generate_image(prompt="...", reference_images="all")` to include the uploaded image
4. The tool retrieves uploaded images from a context variable set by the routes
5. Images are passed to Gemini's `generate_content` API alongside the text prompt
6. Gemini generates a modified version of the image

**reference_images parameter options:**
- `"all"` - Include all uploaded images
- `"0"` - Include only the first uploaded image
- `"0,1"` - Include specific images by index (comma-separated)
- `None` - Generate from scratch (no reference images)

**Context variable pattern:**
- `set_current_message_files(files)` is called in [routes/chat.py](../../src/api/routes/chat.py) before the agent runs
- `get_current_message_files()` is called by the tool to access uploaded files
- Only image files (MIME type starting with `image/`) are used as references
- Non-image files (PDFs, text) are filtered out

### History Image References

The LLM can reference images from earlier in the conversation history using the `history_image_*` parameters or the `retrieve_file` tool. File IDs are provided in the conversation history metadata.

**How it works:**
1. Each user message with files includes a `files` array in metadata with `id` in format `"message_id:file_index"`
2. LLM extracts the message_id and file_index from the history metadata
3. LLM calls `generate_image(prompt="...", history_image_message_id="msg-xxx", history_image_file_index=0)`
4. The tool retrieves the image from blob storage (or legacy base64) using conversation context
5. Image is passed to Gemini's API as a reference image

**history_image parameters:**
- `history_image_message_id` - The message ID containing the historical image
- `history_image_file_index` - The file index within that message (default: 0)

**Context variable pattern for history:**
- `set_conversation_context(conversation_id, user_id)` is called in [routes/chat.py](../../src/api/routes/chat.py) before the agent runs
- `get_conversation_context()` returns the current conversation/user IDs for ownership verification
- The tool verifies the message belongs to the current conversation before retrieving

### File Retrieval Tool

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

**Security:**
- Verifies message belongs to the current conversation
- Verifies conversation belongs to the current user
- Returns error for unauthorized access attempts

### Tool Result Handling

Tool results (including generated images) are returned from both `chat_batch()` and `stream_chat()` methods but are **not persisted** to the database. This is intentional:
1. **Prevents state bloat**: Generated images are large base64 blobs that would grow the state rapidly
2. **Ensures fresh tool calls**: If tool results were persisted, the LLM might skip calling `generate_image` for follow-up requests, thinking the tool was already called
3. **Conversation context is sufficient**: The human/AI message history stored in the `messages` table provides enough context for multi-turn conversations

The `chat_batch()` method returns `(response_text, tool_results, usage_info)`. The batch and streaming endpoints extract images from `tool_results` for storage, then discard the tool results themselves.

### Metadata Format

The metadata block supports both sources and generated_images:
```html
<!-- METADATA:
{"sources": [...], "generated_images": [{"prompt": "..."}]}
-->
```

### Key Files

- [tools/image_generation.py](../../src/agent/tools/image_generation.py) - `generate_image()` tool with `reference_images` and `history_image_*` parameters
- [tools/file_retrieval.py](../../src/agent/tools/file_retrieval.py) - `retrieve_file()` tool
- [tools/context.py](../../src/agent/tools/context.py) - Context variable helpers
- [prompts.py](../../src/agent/prompts.py) - System prompt with image editing and file retrieval instructions
- [models/](../../src/db/models/) - `Message.generated_images` field
- [routes/chat.py](../../src/api/routes/chat.py) - Sets files and conversation context before agent call, image extraction from tool results
- [ImageGenPopup.ts](../../web/src/components/ImageGenPopup.ts) - Popup showing generation info
- [InfoPopup.ts](../../web/src/components/InfoPopup.ts) - Generic popup component used by both sources and image gen
- [messages/actions.ts](../../web/src/components/messages/actions.ts) - Sparkles button rendering

## Code Execution Sandbox

The app can execute Python code in a secure Docker sandbox using [llm-sandbox](https://github.com/vndee/llm-sandbox).

### How it works

1. **Tool available**: `execute_code(code)` tool in [tools/code_execution.py](../../src/agent/tools/code_execution.py)
2. **Docker sandbox**: Code runs in an isolated container with no network access
3. **Custom image**: Uses a pre-built Docker image with fonts and libraries pre-installed for faster execution
4. **File output**: Code saves files to `/output/` directory, which are extracted and returned
5. **Automatic plots**: Matplotlib plots are captured automatically via llm-sandbox
6. **Pre-installed libraries**: numpy, pandas, matplotlib, scipy, sympy, pillow, reportlab, fpdf2

### Custom Docker Image

For optimal performance, the app uses a custom Docker image with pre-installed dependencies:

**Building the image:**
```bash
make sandbox-image
```

This builds `ai-chatbot-sandbox:local` with:
- DejaVu fonts for Unicode support in PDF generation (fpdf2)
- All Python libraries pre-installed (numpy, pandas, matplotlib, etc.)
- Compiler tools (gcc, g++) for native extensions

**Benefits:**
- **Faster execution**: No runtime font installation (~2-5s saved per fpdf execution)
- **Faster library loading**: Pre-installed libraries avoid pip install overhead
- **Reliability**: No risk of apt-get or pip failures during execution

**Automatic cleanup:**
- `make sandbox-image` removes old image versions to prevent bloat
- Each build replaces the previous `ai-chatbot-sandbox:local` image

### Security Constraints

- **No network**: Containers run with `--network none` (default in llm-sandbox)
- **No host access**: Code cannot access files outside the container
- **Resource limits**: Configurable timeout (30s default), memory limit (512MB default)
- **Fresh container**: Each execution creates a new container, destroyed after use

### Configuration

```bash
CODE_SANDBOX_ENABLED=true                    # Enable/disable (default: true)
CODE_SANDBOX_IMAGE=ai-chatbot-sandbox:local  # Custom Docker image (required)
CODE_SANDBOX_TIMEOUT=30                      # Execution timeout in seconds
CODE_SANDBOX_MEMORY_LIMIT=512m               # Container memory limit
CODE_SANDBOX_CPU_LIMIT=1.0                   # CPU limit (1.0 = 1 core)
CODE_SANDBOX_LIBRARIES=numpy,pandas,matplotlib,scipy,sympy,pillow,reportlab,fpdf2
```

### Deployment

Each deployment environment must build the custom image:

```bash
# Initial setup
make setup
make sandbox-image

# Update .env
CODE_SANDBOX_IMAGE=ai-chatbot-sandbox:local

# On updates (if Dockerfile changed)
make sandbox-image
```

**Note:** The custom image is required. The base Python image lacks pre-installed fonts and libraries, causing code execution to fail or perform poorly.

### File Output Pattern (uses `_full_result` to save tokens)

The tool uses the same `_full_result` pattern as `generate_image` to avoid sending large file data back to the LLM:

1. **Wrapped execution**: User code is wrapped to create `/output/` directory and list files after execution
2. **File extraction**: Files are extracted via `session.copy_from_runtime()` to temp files
3. **LLM sees metadata only**: Response includes file metadata (name, type, size) but NOT the base64 data
4. **Full data in `_full_result`**: Actual file data is stored in `_full_result.files` for server-side extraction
5. **Server extracts files**: `extract_code_output_files_from_tool_results()` extracts files from `_full_result`
6. **Stored as attachments**: Files are attached to the assistant message like any other file upload

**Token optimization:**
- Without this pattern: Each 100KB file would add ~130K tokens to the next request
- With this pattern: LLM only sees ~50 tokens of metadata per file

### Example Use Cases

- Mathematical calculations (sympy for symbolic math)
- Data analysis (pandas, numpy)
- Charts and visualizations (matplotlib)
- PDF document generation (reportlab)
- JSON/CSV data transformation

### Graceful Degradation

- If Docker is not available, the tool returns an error message
- Docker availability is checked once and cached
- The tool is only added to the available tools list if `CODE_SANDBOX_ENABLED=true`

### Key Files

- [code_execution.py](../../src/agent/tools/code_execution.py) - `execute_code()` tool, `is_code_sandbox_available()`, `_check_docker_available()`
- [Dockerfile](../../docker/code-sandbox/Dockerfile) - Custom Docker image with pre-installed fonts and libraries
- [Makefile](../../Makefile) - `sandbox-image` target for building custom image
- [images.py](../../src/utils/images.py) - `extract_code_output_files_from_tool_results()` for file extraction
- [config.py](../../src/config.py) - `CODE_SANDBOX_*` configuration options
- [prompts.py](../../src/agent/prompts.py) - System prompt with code execution instructions
- [routes/chat.py](../../src/api/routes/chat.py) - Extracts and attaches code output files to messages

### Testing Locally

```bash
# Ensure Docker is running
docker info

# Test the sandbox manually
python -c "
from llm_sandbox import SandboxSession
with SandboxSession(lang='python') as s:
    result = s.run('print(1+1)')
    print(result.stdout)
"
```

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
- E2E tests: "Chat - Clipboard Paste" describe block in [chat.spec.ts](../../web/tests/e2e/chat.spec.ts)

## Upload Progress

When sending messages with file attachments, an upload progress indicator shows the upload status.

### How it works

1. When files are attached and the user clicks send, `showUploadProgress()` is called
2. In batch mode: Uses XMLHttpRequest with `upload.onprogress` to track actual upload progress (0-100%)
3. In streaming mode: Shows indeterminate progress ("Uploading...") since fetch doesn't support upload progress
4. Progress bar updates in real-time showing percentage and "Processing..." at 100%
5. `hideUploadProgress()` is called in the finally block to ensure cleanup

### UI Behavior

- Progress bar appears below file preview, above input container
- Shows percentage text (e.g., "Uploading 75%") during upload
- Shows "Processing..." when upload reaches 100% (server is processing)
- Hidden when not uploading (uses `.hidden` class)
- CSS transition animates the progress bar smoothly

### Implementation Details

- `requestWithProgress<T>()` in [client.ts](../../web/src/api/client.ts) wraps XHR for upload progress tracking
- `chat.sendBatch()` accepts optional `onUploadProgress` callback, uses XHR when files are present
- `showUploadProgress()`, `hideUploadProgress()`, `updateUploadProgress()` in [MessageInput.ts](../../web/src/components/MessageInput.ts)
- `uploadProgress` state in Zustand store (not currently used for display, but available for future use)
- CSS styles in [input.css](../../web/src/styles/components/input.css) using `--progress` custom property

### Key Files

- [client.ts](../../web/src/api/client.ts) - `requestWithProgress()` XHR wrapper
- [MessageInput.ts](../../web/src/components/MessageInput.ts) - Progress UI functions
- [messaging.ts](../../web/src/core/messaging.ts) - Integration in `sendBatchMessage()` and `sendStreamingMessage()`
- [input.css](../../web/src/styles/components/input.css) - `.upload-progress` styles

### Testing

- Unit tests: "Upload Progress UI Functions" describe block in [message-input.test.ts](../../web/tests/unit/message-input.test.ts)
- E2E tests: "Chat - Upload Progress" describe block in [chat.spec.ts](../../web/tests/e2e/chat.spec.ts)

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
- [client.ts](../../web/src/api/client.ts) - `fetchThumbnail()` with polling and exponential backoff
- [config.ts](../../web/src/config.ts) - Frontend polling configuration

### Testing

- Unit tests: [test_background_thumbnails.py](../../tests/unit/test_background_thumbnails.py)
- Integration tests: [test_routes_thumbnails.py](../../tests/integration/test_routes_thumbnails.py)

## Copy to Clipboard

The app provides copy-to-clipboard functionality at two levels.

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

- E2E tests: "Chat - Copy to Clipboard" describe block in [chat.spec.ts](../../web/tests/e2e/chat.spec.ts)

## See Also

- [Chat and Streaming](chat-and-streaming.md) - Web search sources, thinking indicators
- [UI Features](ui-features.md) - Input toolbar, file upload UI
- [Architecture: Database](../architecture/database.md) - Blob storage for files and thumbnails
