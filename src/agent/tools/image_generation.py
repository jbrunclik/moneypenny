"""Image generation tool using Gemini."""

import base64
import json
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from langchain_core.tools import tool

from src.agent.tools.context import (
    get_conversation_context,
    get_current_message_files,
)
from src.agent.tools.permission_check import check_autonomous_permission
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Valid aspect ratios for image generation
VALID_ASPECT_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"}


@tool
def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    reference_images: str | None = None,
    history_image_message_id: str | None = None,
    history_image_file_index: int = 0,
) -> str:
    """Generate or edit an image using Gemini image generation.

    Use this tool when the user asks you to create, generate, draw, or make an image.
    If the user uploaded an image and wants you to modify/edit it, use reference_images
    to include the uploaded image(s) as reference for the generation.

    To use an image from earlier in the conversation, use history_image_message_id and
    history_image_file_index. The IDs can be found in the conversation history metadata
    (each user message with files includes a "files" array with "id" in format "message_id:file_index").

    Args:
        prompt: A detailed description of the image to generate or the edit to make.
                Be specific about style, colors, composition, lighting, and any text.
        aspect_ratio: The image aspect ratio. Options: 1:1 (square, default),
                     16:9 (landscape/widescreen), 9:16 (portrait/mobile),
                     4:3 (standard), 3:4 (portrait), 3:2, 2:3
        reference_images: Which uploaded images FROM THE CURRENT MESSAGE to use as reference.
                         Options: "all" (use all uploaded images), "0" (first image),
                         "0,1" (first and second), etc. None means generate from scratch.
        history_image_message_id: Message ID of a previously uploaded image to use as reference.
                                 Found in history metadata as "id" in format "message_id:file_index".
        history_image_file_index: File index within the message (default 0 for first file).

    Returns:
        JSON with the prompt used and base64 image data, or an error message
    """
    # Check permission for autonomous agents (always requires approval - costs money)
    check_autonomous_permission("generate_image", {"prompt": prompt})

    # Validate prompt
    if not prompt or not prompt.strip():
        return json.dumps({"error": "Prompt cannot be empty"})

    prompt = prompt.strip()
    if len(prompt) > Config.MAX_IMAGE_PROMPT_LENGTH:
        return json.dumps(
            {
                "error": f"Prompt is too long. Maximum length is {Config.MAX_IMAGE_PROMPT_LENGTH} characters, got {len(prompt)}"
            }
        )

    # Validate aspect ratio
    if aspect_ratio not in VALID_ASPECT_RATIOS:
        return json.dumps(
            {
                "error": f"Invalid aspect ratio '{aspect_ratio}'. Valid options: {', '.join(sorted(VALID_ASPECT_RATIOS))}"
            }
        )

    try:
        logger.debug(
            "Starting image generation",
            extra={
                "model": Config.IMAGE_GENERATION_MODEL,
                "aspect_ratio": aspect_ratio,
                "has_reference_images": reference_images is not None,
                "has_history_image": history_image_message_id is not None,
            },
        )
        # Create client with API key
        client = genai.Client(api_key=Config.GEMINI_API_KEY)

        # Build contents - either text-only or multimodal with reference images
        contents: Any = prompt  # Default: text-only
        history_image_data: dict[str, str] | None = None

        # Handle history image reference (from earlier in conversation)
        if history_image_message_id:
            # Import here to avoid circular imports
            from src.db.blob_store import get_blob_store
            from src.db.models import db, make_blob_key

            conv_id, user_id = get_conversation_context()

            if not conv_id or not user_id:
                return json.dumps(
                    {
                        "error": "Cannot access conversation history. No conversation context available."
                    }
                )

            # Get the message
            message = db.get_message_by_id(history_image_message_id)
            if not message:
                return json.dumps({"error": f"Message not found: {history_image_message_id}"})

            # Verify message belongs to this conversation
            if message.conversation_id != conv_id:
                return json.dumps({"error": "Message does not belong to this conversation."})

            # Check file exists and is an image
            if not message.files or history_image_file_index >= len(message.files):
                return json.dumps(
                    {
                        "error": f"File index {history_image_file_index} not found in message. "
                        f"Message has {len(message.files) if message.files else 0} file(s)."
                    }
                )

            file_meta = message.files[history_image_file_index]
            mime_type = file_meta.get("type", "")

            if not mime_type.startswith("image/"):
                return json.dumps(
                    {
                        "error": f"File is not an image (type: {mime_type}). Only images can be used as references."
                    }
                )

            # Get file data from blob store
            blob_store = get_blob_store()
            blob_key = make_blob_key(history_image_message_id, history_image_file_index)
            blob_result = blob_store.get(blob_key)

            if blob_result:
                binary_data, stored_mime_type = blob_result
                if stored_mime_type:
                    mime_type = stored_mime_type
            elif "data" in file_meta:
                try:
                    binary_data = base64.b64decode(file_meta["data"])
                except Exception:
                    return json.dumps(
                        {"error": "Failed to read image data from conversation history."}
                    )
            else:
                return json.dumps({"error": "Image data not found in storage."})

            # Store the history image data to be added to contents
            history_image_data = {
                "mime_type": mime_type,
                "data": base64.b64encode(binary_data).decode("utf-8"),
            }
            logger.debug(
                "Retrieved history image for generation",
                extra={
                    "message_id": history_image_message_id,
                    "file_index": history_image_file_index,
                    "mime_type": mime_type,
                    "size": len(binary_data),
                },
            )

        if reference_images or history_image_data:
            # Start building multimodal contents
            contents = [prompt]

            # Add history image first if present
            if history_image_data:
                contents.append(
                    {
                        "inline_data": {
                            "mime_type": history_image_data["mime_type"],
                            "data": history_image_data["data"],
                        }
                    }
                )
                logger.debug("Added history image to generation request")

            # Add current message reference images if specified
            if reference_images:
                # Get files from context for image-to-image editing
                files = get_current_message_files()
                if files:
                    # Filter to only image files
                    image_files = [f for f in files if f.get("type", "").startswith("image/")]
                    if image_files:
                        # Determine which images to include
                        if reference_images.lower() == "all":
                            indices = list(range(len(image_files)))
                        else:
                            # Parse comma-separated indices
                            try:
                                indices = [
                                    int(i.strip())
                                    for i in reference_images.split(",")
                                    if i.strip().isdigit()
                                ]
                            except ValueError:
                                indices = []

                        for idx in indices:
                            if 0 <= idx < len(image_files):
                                img = image_files[idx]
                                contents.append(
                                    {
                                        "inline_data": {
                                            "mime_type": img["type"],
                                            "data": img["data"],  # Already base64
                                        }
                                    }
                                )
                        if indices:
                            logger.debug(
                                "Added current message reference images to generation request",
                                extra={
                                    "reference_image_count": len(
                                        [idx for idx in indices if 0 <= idx < len(image_files)]
                                    ),
                                    "total_available_images": len(image_files),
                                },
                            )
                    else:
                        logger.warning(
                            "reference_images specified but no image files found in uploads"
                        )
                else:
                    logger.warning("reference_images specified but no files in current message")

            # Log total reference images
            total_refs = len(contents) - 1  # Subtract 1 for the prompt
            if total_refs > 0:
                logger.debug(
                    "Total reference images for generation",
                    extra={"count": total_refs},
                )

        # Generate image using Gemini image generation model
        # The model generates one final image by default (uses internal "thinking" to iterate)
        logger.debug("Calling Gemini image generation API")
        response = client.models.generate_content(
            model=Config.IMAGE_GENERATION_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
            ),
        )
        logger.debug("Image generation API call completed")

        # Extract usage metadata for cost tracking
        usage_metadata_dict: dict[str, Any] | None = None
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage = response.usage_metadata
            usage_metadata_dict = {
                "prompt_token_count": getattr(usage, "prompt_token_count", 0) or 0,
                "candidates_token_count": getattr(usage, "candidates_token_count", 0) or 0,
                "thoughts_token_count": getattr(usage, "thoughts_token_count", 0) or 0,
                "total_token_count": getattr(usage, "total_token_count", 0) or 0,
            }
            logger.debug(
                "Image generation usage metadata extracted",
                extra=usage_metadata_dict,
            )

        # Extract image from response
        if not response.candidates:
            logger.warning("No candidates in image generation response")
            return json.dumps(
                {"error": "No image generated. The model may have refused the request."}
            )

        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            logger.warning("No content/parts in image generation response")
            return json.dumps(
                {"error": "No image generated. The model may have refused the request."}
            )

        for part in candidate.content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                image_data = part.inline_data
                # Encode to base64
                if image_data.data is None:
                    continue
                image_base64 = base64.b64encode(image_data.data).decode("utf-8")
                image_size = len(image_data.data)
                logger.info(
                    "Image generated successfully",
                    extra={
                        "image_size_bytes": image_size,
                        "mime_type": image_data.mime_type,
                        "aspect_ratio": aspect_ratio,
                        "used_reference_images": reference_images is not None,
                    },
                )
                # Return TWO things:
                # 1. A summary for the LLM (no image data - to avoid sending 500KB back to the model)
                # 2. The full image data stored in a special field that gets extracted server-side
                #
                # The LLM only sees the summary, which confirms the image was generated.
                # The server extracts _full_result for storage and display.
                result = {
                    "success": True,
                    "prompt": prompt,
                    "aspect_ratio": aspect_ratio,
                    "message": "Image generated successfully. The image will be displayed to the user.",
                    # This field is extracted server-side and NOT sent to the LLM
                    "_full_result": {
                        "image": {
                            "data": image_base64,
                            "mime_type": image_data.mime_type or "image/png",
                        },
                    },
                }
                # Include usage_metadata for cost tracking
                if usage_metadata_dict:
                    result["usage_metadata"] = usage_metadata_dict

                return json.dumps(result)

        logger.warning("No image data found in response parts")
        return json.dumps({"error": "No image data found in response"})

    except genai_errors.ClientError as e:
        error_msg = str(e)
        logger.warning("Image generation client error", extra={"error": error_msg})
        # Provide user-friendly error messages for common issues
        if "SAFETY" in error_msg.upper() or "BLOCKED" in error_msg.upper():
            return json.dumps(
                {
                    "error": "The image generation was blocked due to safety filters. Please try a different prompt."
                }
            )
        return json.dumps({"error": f"Image generation failed: {error_msg}"})
    except genai_errors.ServerError as e:
        logger.error("Image generation server error", extra={"error": str(e)}, exc_info=True)
        return json.dumps(
            {"error": "Image generation service temporarily unavailable. Please try again."}
        )
    except genai_errors.APIError as e:
        logger.error("Image generation API error", extra={"error": str(e)}, exc_info=True)
        return json.dumps({"error": f"Image generation failed: {e}"})
