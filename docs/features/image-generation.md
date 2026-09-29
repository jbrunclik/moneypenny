# Image Generation

The app can generate images using Gemini's image generation model (`gemini-3-pro-image`).

## How it works

1. **Tool available**: `generate_image(prompt, aspect_ratio, image_size, use_search, reference_images, history_image_message_id, history_image_file_index)` tool in [tools/image_generation.py](../../src/agent/tools/image_generation.py)
2. **Tool returns JSON**: Returns `{"prompt": "...", "image": {"data": "base64...", "mime_type": "image/png"}}`
3. **Image data bypasses the model**: the tool node stores the image under `_full_result` server-side and strips it from what the model sees (see [Agent Graph](../architecture/agent-graph.md#tool-node))
4. **Backend extracts images**: when the turn is saved, `extract_generated_images_from_tool_results()` ([utils/images.py](../../src/utils/images.py)) reads the captured results (called from `save_message_to_db()` in [chat_save.py](../../src/api/helpers/chat_save.py) and from the agent executor)
5. **Images stored as files**: Generated images are stored as file attachments on the message
6. **Metadata stored in DB**: Messages table has a `generated_images` column (JSON array)
7. **UI shows sparkles button**: A sparkles icon appears in message actions when generated images exist, opening a popup showing the prompt used and the cost of image generation (excluding prompt tokens)

## Aspect Ratios

Supported: `1:1` (default), `16:9`, `9:16`, `4:3`, `3:4`, `3:2`, `2:3`, `4:5`, `5:4`, `21:9`

## Resolution and Search Grounding

- **`image_size`**: `1K` (default), `2K`, `4K` (case-insensitive; the API itself rejects lowercase `k`). 1K and 2K both produce 1120 image tokens (~$0.134); 4K produces 2000 (~$0.24). Output is always JPEG, roughly 0.5 MB at 1K, 3–4 MB at 2K, and ~11 MB at 4K.
- **`use_search`**: adds the Google Search tool to the request so the image can reflect real-world or current facts. Search requests are free up to 5,000/month (shared across Gemini 3.x models), so they are not tracked as a cost.
- **Large references are downscaled**: when a stored image is reused via `history_image_*`, anything with a longest edge above `IMAGE_REFERENCE_MAX_EDGE_PX` (default 2048) is resized and re-encoded as JPEG before being sent inline. A 4K image is ~15 MB as base64, and Gemini's inline request limit is ~20 MB.
- **Not available on the Developer API**: `output_mime_type` / compression (Vertex only). The model also has no masks, denoise strength, seeds, negative prompts, or ControlNet/FaceID. Edits regenerate the whole image, so the system prompt tells the agent to spell out what must stay unchanged when a person's likeness matters.

## Image-to-Image Editing

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
- `set_current_message_files(files)` is called by `TurnContext.apply()` ([chat_turn.py](../../src/api/helpers/chat_turn.py)) before the agent runs
- `get_current_message_files()` is called by the tool to access uploaded files
- Only image files (MIME type starting with `image/`) are used as references
- Non-image files (PDFs, text) are filtered out

## History Image References

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
- `set_conversation_context(conversation_id, user_id)` is also set by `TurnContext.apply()` before the agent runs
- `get_conversation_context()` returns the current conversation/user IDs for ownership verification
- The tool verifies the message belongs to the current conversation before retrieving

## Tool Result Handling

Tool results (including generated images) are returned from both `chat_batch()` and `stream_chat_events()` but are **not persisted** to the database as tool messages (a bounded text digest is - see [Tool-Output Digests](../architecture/conversation-context.md#tool-output-digests); image generation is excluded from it). This is intentional:
1. **Prevents state bloat**: Generated images are large base64 blobs that would grow the state rapidly
2. **Ensures fresh tool calls**: If tool results were persisted, the LLM might skip calling `generate_image` for follow-up requests, thinking the tool was already called
3. **Conversation context is sufficient**: The human/AI message history stored in the `messages` table provides enough context for multi-turn conversations

The `chat_batch()` method returns `(response_text, tool_results, usage_info, result_messages)`. The batch and streaming endpoints extract images from `tool_results` for storage, then discard the tool results themselves.

## Metadata Extraction

Image metadata is not parsed from the response text (the old `<!-- METADATA: -->`
block is gone): `extract_image_prompts_from_messages()` in
[content.py](../../src/agent/content.py) reads the prompts from the `generate_image`
tool-call arguments (sources come from the pages the turn read - `extract_read_sources()`).

## Key Files

- [tools/image_generation.py](../../src/agent/tools/image_generation.py) - `generate_image()` tool with `reference_images` and `history_image_*` parameters
- [tools/file_retrieval.py](../../src/agent/tools/file_retrieval.py) - `retrieve_file()` tool
- [tools/context.py](../../src/agent/tools/context.py) - Context variable helpers
- [prompt_texts/core.py](../../src/agent/prompt_texts/core.py) - System prompt with image editing and file retrieval instructions
- [models/](../../src/db/models/) - `Message.generated_images` field
- [chat_turn.py](../../src/api/helpers/chat_turn.py) - sets files and conversation context before the agent call
- [chat_save.py](../../src/api/helpers/chat_save.py), [utils/images.py](../../src/utils/images.py) - image extraction from tool results when the turn is saved
- [ImageGenPopup.ts](../../web/src/components/ImageGenPopup.ts) - Popup showing generation info
- [InfoPopup.ts](../../web/src/components/InfoPopup.ts) - Generic popup component used by both sources and image gen
- [messages/actions.ts](../../web/src/components/messages/actions.ts) - Sparkles button rendering

## See Also

- [File Handling](file-handling.md) - uploads and `retrieve_file` (history image IDs)
- [Cost Tracking](cost-tracking.md) - image generation costs
- [Thinking Indicator and Source Chips](thinking-and-sources.md) - the "Generating image" trace item
