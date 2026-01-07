"""Web tools for the AI agent."""

import base64
import contextvars
import json
import os as local_os
import tempfile
from typing import Any

import html2text
import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from langchain_core.tools import tool

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Contextvar to hold the current message's files for tool access
# This allows tools (like generate_image) to access uploaded images for image-to-image workflows
_current_message_files: contextvars.ContextVar[list[dict[str, Any]] | None] = (
    contextvars.ContextVar("_current_message_files", default=None)
)

# Contextvars to hold conversation context for tools that need to access history
# This allows tools (like retrieve_file) to access files from previous messages
_current_conversation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_conversation_id", default=None
)
_current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_user_id", default=None
)


def set_current_message_files(files: list[dict[str, Any]] | None) -> None:
    """Set the current message's files for tool access."""
    _current_message_files.set(files)


def get_current_message_files() -> list[dict[str, Any]] | None:
    """Get the current message's files (for tools like generate_image to access)."""
    return _current_message_files.get()


def set_conversation_context(conversation_id: str | None, user_id: str | None) -> None:
    """Set the conversation context for tool access.

    This allows tools to access files from conversation history.
    """
    _current_conversation_id.set(conversation_id)
    _current_user_id.set(user_id)


def get_conversation_context() -> tuple[str | None, str | None]:
    """Get the current conversation context (conversation_id, user_id)."""
    return _current_conversation_id.get(), _current_user_id.get()


# Flag to track if Docker is available for code execution
_docker_available: bool | None = None


def _check_docker_available() -> bool:
    """Check if Docker is available for code execution.

    Caches the result to avoid repeated checks.
    """
    global _docker_available
    if _docker_available is not None:
        return _docker_available

    try:
        from llm_sandbox import SandboxSession

        # Try to create a quick session to verify Docker connectivity
        # Use standard Docker Hub image to avoid ghcr.io authentication issues
        with SandboxSession(lang="python", image=Config.CODE_SANDBOX_IMAGE) as session:
            result = session.run("print('ok')")
            _docker_available = result.exit_code == 0
            if _docker_available:
                logger.info("Docker sandbox available for code execution")
            else:
                logger.warning("Docker sandbox test failed", extra={"exit_code": result.exit_code})
    except Exception as e:
        _docker_available = False
        logger.warning(
            "Docker not available for code execution",
            extra={"error": str(e), "note": "Code execution tool will be disabled"},
        )

    return _docker_available


def is_code_sandbox_available() -> bool:
    """Check if code sandbox is available and enabled."""
    if not Config.CODE_SANDBOX_ENABLED:
        return False
    return _check_docker_available()


def _extract_text_from_html(html: str, max_length: int | None = None) -> str:
    """Extract readable text from HTML content."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove script, style, nav, footer, header elements
    for element in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        element.decompose()

    # Convert to markdown
    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.ignore_emphasis = False
    converter.body_width = 0  # No wrapping

    text = converter.handle(str(soup))

    # Truncate if too long
    limit = max_length if max_length is not None else Config.HTML_TEXT_MAX_LENGTH
    if len(text) > limit:
        text = text[:limit] + "\n\n[Content truncated...]"

    return text.strip()


# Supported binary MIME types for fetch_url
FETCHABLE_BINARY_TYPES = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/gif": "gif",
    "image/webp": "webp",
}


def _get_content_type_category(content_type: str) -> str:
    """Categorize content type as 'html', 'text', 'binary', or 'unsupported'.

    Args:
        content_type: The Content-Type header value

    Returns:
        Category string: 'html', 'text', 'binary', or 'unsupported'
    """
    # Normalize content type (remove charset and parameters)
    mime_type = content_type.split(";")[0].strip().lower()

    if "text/html" in mime_type:
        return "html"
    if mime_type in ("text/plain", "text/markdown", "text/csv"):
        return "text"
    if mime_type in FETCHABLE_BINARY_TYPES:
        return "binary"
    return "unsupported"


@tool
def fetch_url(url: str) -> str | list[dict[str, Any]]:
    """Fetch content from a URL - supports web pages, PDFs, and images.

    Use this tool to:
    - Read the content of web pages (returns text in markdown format)
    - Analyze PDF documents (returns the PDF for your analysis)
    - Analyze images from URLs (returns the image for your analysis)

    For PDFs and images, the binary content is returned directly for you to analyze.
    You can describe images, extract text from PDFs, answer questions about their content, etc.

    Args:
        url: The URL to fetch (must start with http:// or https://)

    Returns:
        For web pages: The text content in markdown format
        For PDFs/images: Multimodal content for analysis
        For errors: JSON with error field
    """
    logger.info("fetch_url called", extra={"url": url})
    if not url.startswith(("http://", "https://")):
        logger.warning("Invalid URL format", extra={"url": url})
        return json.dumps(
            {"error": f"Invalid URL '{url}'. URL must start with http:// or https://"}
        )

    try:
        logger.debug("Fetching URL", extra={"url": url})
        with httpx.Client(
            timeout=float(Config.TOOL_TIMEOUT),
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            },
        ) as client:
            response = client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            content_category = _get_content_type_category(content_type)
            content_length = len(response.content)

            logger.debug(
                "URL fetched successfully",
                extra={
                    "url": url,
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "content_category": content_category,
                    "content_length": content_length,
                },
            )

            # Handle HTML content - extract text
            if content_category == "html":
                extracted_text = _extract_text_from_html(response.text)
                logger.info(
                    "HTML content extracted", extra={"url": url, "text_length": len(extracted_text)}
                )
                return extracted_text

            # Handle plain text content
            if content_category == "text":
                text_content = response.text
                limit = Config.HTML_TEXT_MAX_LENGTH
                if len(text_content) > limit:
                    text_content = text_content[:limit] + "\n\n[Content truncated...]"
                logger.info(
                    "Text content fetched", extra={"url": url, "text_length": len(text_content)}
                )
                return text_content

            # Handle binary content (PDFs, images)
            if content_category == "binary":
                # Check file size limit (10MB default)
                max_size = Config.FETCH_URL_MAX_FILE_SIZE
                if content_length > max_size:
                    logger.warning(
                        "File too large",
                        extra={"url": url, "size": content_length, "max_size": max_size},
                    )
                    return json.dumps(
                        {
                            "error": f"File is too large ({content_length // 1024 // 1024}MB). "
                            f"Maximum allowed size is {max_size // 1024 // 1024}MB."
                        }
                    )

                # Get normalized MIME type
                mime_type = content_type.split(";")[0].strip().lower()
                # Normalize image/jpg to image/jpeg
                if mime_type == "image/jpg":
                    mime_type = "image/jpeg"

                # Encode as base64
                file_base64 = base64.b64encode(response.content).decode("utf-8")

                # Extract filename from URL for context
                filename = url.split("/")[-1].split("?")[0] or "file"

                logger.info(
                    "Binary content fetched",
                    extra={
                        "url": url,
                        "mime_type": mime_type,
                        "size": content_length,
                        "file_name": filename,
                    },
                )

                # Return multimodal content that the LLM can analyze
                # This format matches how user-uploaded files are passed to the LLM
                return [
                    {
                        "type": "text",
                        "text": f"Here is the content from {url} ({filename}, {mime_type}, {content_length} bytes):",
                    },
                    {
                        "type": "image",  # LangChain uses "image" type for both images and PDFs
                        "base64": file_base64,
                        "mime_type": mime_type,
                    },
                ]

            # Unsupported content type
            logger.warning(
                "Unsupported content type", extra={"url": url, "content_type": content_type}
            )
            return json.dumps(
                {
                    "error": f"Unsupported content type: {content_type}. "
                    f"Supported types: HTML, plain text, PDF, and common image formats (PNG, JPEG, GIF, WebP)."
                }
            )

    except httpx.TimeoutException:
        logger.warning("URL fetch timeout", extra={"url": url})
        return json.dumps({"error": f"Request to {url} timed out"})
    except httpx.HTTPStatusError as e:
        logger.warning(
            "URL fetch HTTP error", extra={"url": url, "status_code": e.response.status_code}
        )
        return json.dumps({"error": f"HTTP {e.response.status_code} when fetching {url}"})
    except httpx.RequestError as e:
        logger.error("URL fetch request error", extra={"url": url, "error": str(e)}, exc_info=True)
        return json.dumps({"error": f"Failed to fetch {url}: {e}"})


@tool
def web_search(query: str, num_results: int | None = None) -> str:
    """Search the web using DuckDuckGo.

    Use this tool to find current information, news, prices, or any other
    information that might not be in your training data. After searching,
    you can use fetch_url to read specific pages.

    Args:
        query: The search query
        num_results: Number of results to return (default from config, max from config)

    Returns:
        JSON string with query and results array containing title, url, and snippet
    """
    if num_results is None:
        num_results = Config.WEB_SEARCH_DEFAULT_RESULTS
    logger.info("web_search called", extra={"query": query, "num_results": num_results})
    num_results = min(max(1, num_results), Config.WEB_SEARCH_MAX_RESULTS)

    try:
        logger.debug("Executing DuckDuckGo search")
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))

        if not results:
            logger.warning("No search results found", extra={"query": query})
            return json.dumps({"query": query, "results": [], "error": "No results found"})

        search_results = [
            {
                "title": r.get("title", "No title"),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            }
            for r in results
        ]

        logger.info("Search completed", extra={"query": query, "result_count": len(search_results)})
        return json.dumps({"query": query, "results": search_results})

    except RatelimitException:
        logger.warning("Search rate limited", extra={"query": query})
        return json.dumps(
            {"query": query, "results": [], "error": "Search rate limited. Please try again later."}
        )
    except TimeoutException:
        logger.warning("Search timeout", extra={"query": query})
        return json.dumps(
            {"query": query, "results": [], "error": "Search timed out. Please try again."}
        )
    except DDGSException as e:
        logger.error("Search error", extra={"query": query, "error": str(e)}, exc_info=True)
        return json.dumps({"query": query, "results": [], "error": str(e)})


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
    history_image_file_index to reference a previously uploaded image. Use retrieve_file
    with list_files=True first to see what images are available.

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
                                 Use retrieve_file(list_files=True) to find available images.
        history_image_file_index: File index within the message (default 0 for first file).

    Returns:
        JSON with the prompt used and base64 image data, or an error message
    """
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


# ============================================================================
# Code Execution Helper Functions
# ============================================================================


def _get_mime_type(filename: str) -> str:
    """Get MIME type from filename extension."""
    ext = filename.lower().split(".")[-1] if "." in filename else ""
    mime_types = {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "svg": "image/svg+xml",
        "csv": "text/csv",
        "json": "application/json",
        "txt": "text/plain",
        "html": "text/html",
        "xml": "application/xml",
    }
    return mime_types.get(ext, "application/octet-stream")


def _build_font_setup_code() -> str:
    """Build code snippet to install DejaVu fonts for Unicode support in fpdf2."""
    return """
# Install DejaVu fonts for Unicode support in PDF generation
import subprocess as _sp
import sys as _sys
_sp.run(['apt-get', 'update', '-qq'], capture_output=True)
_sp.run(['apt-get', 'install', '-y', '-qq', 'fonts-dejavu-core'], capture_output=True)
# Helper to get DejaVu font path
def _get_dejavu_font():
    return '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
"""


def _needs_font_setup(code: str) -> bool:
    """Check if code uses fpdf and needs font setup for Unicode support."""
    return "fpdf" in code.lower() or "FPDF" in code


def _wrap_user_code(code: str) -> str:
    """Wrap user code with setup and file listing logic.

    The wrapped code:
    1. Creates /output directory for file saving
    2. Installs fonts if fpdf2 is detected (for Unicode support)
    3. Runs the user code
    4. Lists files in /output for extraction

    Args:
        code: The user's Python code to wrap

    Returns:
        Wrapped code ready for sandbox execution
    """
    font_setup = _build_font_setup_code() if _needs_font_setup(code) else ""

    return f"""
import os
os.makedirs('/output', exist_ok=True)
{font_setup}
# User code starts here
{code}
# User code ends here

# List generated files for extraction
import json as _json
_output_files = []
if os.path.exists('/output'):
    for _f in os.listdir('/output'):
        _path = os.path.join('/output', _f)
        if os.path.isfile(_path):
            _output_files.append(_f)
if _output_files:
    print('__OUTPUT_FILES__:' + _json.dumps(_output_files))
"""


def _parse_output_files_from_stdout(stdout: str) -> tuple[list[str], str]:
    """Parse output file list from stdout and return cleaned stdout.

    The wrapped code prints a special marker line with the list of files
    in /output directory. This function extracts that list and removes
    the marker line from stdout.

    Args:
        stdout: Raw stdout from sandbox execution

    Returns:
        Tuple of (list of filenames, cleaned stdout without marker line)
    """
    output_files: list[str] = []
    clean_lines = []

    for line in stdout.split("\n"):
        if line.startswith("__OUTPUT_FILES__:"):
            try:
                output_files = json.loads(line[17:])
            except json.JSONDecodeError:
                pass
        else:
            clean_lines.append(line)

    return output_files, "\n".join(clean_lines).rstrip()


def _extract_file_from_sandbox(
    session: Any, filename: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Extract a single file from the sandbox and return metadata and full data.

    Args:
        session: The SandboxSession instance
        filename: Name of the file to extract from /output/

    Returns:
        Tuple of (full_file_data, file_metadata) or (None, None) on failure.
        full_file_data contains the base64 encoded data for server storage.
        file_metadata contains only name, type, size for the LLM.
    """
    try:
        # Create a temp file to receive the data
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        # Copy file from sandbox
        session.copy_from_runtime(f"/output/{filename}", tmp_path)

        # Read and encode the file
        with open(tmp_path, "rb") as f:
            file_data = f.read()

        mime_type = _get_mime_type(filename)
        file_size = len(file_data)

        # Full data for server-side extraction (includes base64)
        full_file_data = {
            "name": filename,
            "mime_type": mime_type,
            "data": base64.b64encode(file_data).decode("utf-8"),
            "size": file_size,
        }

        # Metadata for LLM (no base64 data - saves tokens)
        file_metadata = {
            "name": filename,
            "mime_type": mime_type,
            "size": file_size,
        }

        # Clean up temp file
        local_os.unlink(tmp_path)

        return full_file_data, file_metadata

    except Exception as e:
        logger.warning(
            "Failed to extract file from sandbox",
            extra={"filename": filename, "error": str(e)},
        )
        return None, None


def _extract_output_files(
    session: Any, filenames: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract all output files from the sandbox.

    Args:
        session: The SandboxSession instance
        filenames: List of filenames to extract from /output/

    Returns:
        Tuple of (full_files_list, metadata_list).
        full_files_list contains base64 data for server storage.
        metadata_list contains only name/type/size for the LLM.
    """
    full_files: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []

    for filename in filenames:
        full_data, meta = _extract_file_from_sandbox(session, filename)
        if full_data and meta:
            full_files.append(full_data)
            metadata.append(meta)

    return full_files, metadata


def _extract_plots(result: Any) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Extract matplotlib plots from sandbox execution result.

    Args:
        result: The execution result from SandboxSession.run()

    Returns:
        Tuple of (full_plots_list, metadata_list).
        full_plots_list contains base64 data for server storage.
        metadata_list contains only format/name for the LLM.
    """
    full_plots: list[dict[str, Any]] = []
    metadata: list[dict[str, str]] = []

    if not hasattr(result, "plots") or not result.plots:
        return full_plots, metadata

    for i, plot in enumerate(result.plots):
        plot_format = plot.format.value if hasattr(plot.format, "value") else str(plot.format)
        plot_name = f"plot_{i + 1}.{plot_format}"

        # Full data for server-side extraction
        full_plots.append(
            {
                "name": plot_name,
                "mime_type": f"image/{plot_format}",
                "data": plot.content_base64,
                "size": len(base64.b64decode(plot.content_base64)) if plot.content_base64 else 0,
            }
        )

        # Metadata for LLM
        metadata.append({"format": plot_format, "name": plot_name})

    return full_plots, metadata


def _build_execution_response(
    result: Any,
    clean_stdout: str,
    file_metadata: list[dict[str, Any]],
    plot_metadata: list[dict[str, str]],
    full_result_files: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the final response dictionary for code execution.

    Uses the _full_result pattern: LLM sees only metadata, server extracts
    full file data from _full_result for storage and display.

    Args:
        result: The execution result from SandboxSession.run()
        clean_stdout: Stdout with marker lines removed
        file_metadata: Metadata for files (no base64) - shown to LLM
        plot_metadata: Metadata for plots - shown to LLM
        full_result_files: Full file data (with base64) - extracted server-side

    Returns:
        Response dictionary ready for JSON serialization
    """
    stderr = result.stderr or ""

    response: dict[str, Any] = {
        "success": result.exit_code == 0,
        "exit_code": result.exit_code,
        "stdout": clean_stdout,
        "stderr": stderr,
    }

    # Add file metadata for LLM
    if file_metadata:
        response["files"] = file_metadata
        response["message"] = (
            f"Generated {len(file_metadata)} file(s): "
            + ", ".join(f["name"] for f in file_metadata)
            + ". Files will be displayed to the user."
        )

    # Add plot metadata for LLM
    if plot_metadata:
        response["plots"] = plot_metadata

    # Store full file data in _full_result (stripped before sending to LLM)
    if full_result_files:
        response["_full_result"] = {"files": full_result_files}

    return response


@tool
def execute_code(code: str) -> str:
    """Execute Python code in a secure, isolated sandbox environment.

    Use this tool for tasks that require computation, data processing, or generating files.
    The sandbox has NO network access and NO access to local files outside the sandbox.

    ## Capabilities
    - Mathematical calculations (numpy, scipy, sympy)
    - Data analysis and manipulation (pandas, numpy)
    - Creating charts and plots (matplotlib) - returned as base64 images
    - Generating PDF documents (reportlab)
    - Image processing (pillow)
    - Text parsing and processing
    - JSON/CSV data transformation

    ## Pre-installed Libraries
    numpy, pandas, matplotlib, scipy, sympy, pillow, reportlab

    ## Limitations
    - NO network access (cannot fetch URLs, APIs, or download anything)
    - NO access to user's local files (cannot read/write files outside sandbox)
    - 30 second execution timeout
    - 512MB memory limit

    ## Best Practices
    - Print results you want to show the user
    - For plots: use plt.savefig() or plt.show() - plots are captured automatically
    - For generated files (PDFs, images): save to /output/ directory and they will be
      returned as base64-encoded data in the response

    ## Example: Generate a PDF
    ```python
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas("/output/report.pdf", pagesize=letter)
    c.drawString(100, 750, "Hello World!")
    c.save()
    print("PDF generated successfully")
    ```

    ## Example: Generate a plot
    ```python
    import matplotlib.pyplot as plt
    import numpy as np

    x = np.linspace(0, 10, 100)
    plt.plot(x, np.sin(x))
    plt.title("Sine Wave")
    plt.savefig("/output/plot.png")
    print("Plot saved")
    ```

    Args:
        code: Python code to execute. Should be complete, runnable code.

    Returns:
        JSON with stdout, stderr, exit_code, and any generated files.
        Files saved to /output/ are returned as base64-encoded data.
    """
    # Check if sandbox is available
    if not Config.CODE_SANDBOX_ENABLED:
        return json.dumps({"error": "Code execution is disabled on this server."})

    if not _check_docker_available():
        return json.dumps(
            {
                "error": "Code execution is not available. Docker is not running or accessible.",
                "hint": "The server administrator needs to ensure Docker is running and accessible.",
            }
        )

    if not code or not code.strip():
        return json.dumps({"error": "Code cannot be empty."})

    logger.info(
        "execute_code called",
        extra={"code_length": len(code), "code_preview": code[:200] if len(code) > 200 else code},
    )

    try:
        from llm_sandbox import SandboxSession

        wrapped_code = _wrap_user_code(code)

        # Create sandbox session with security constraints
        # Note: llm-sandbox runs containers with --network none by default for security
        with SandboxSession(
            lang="python",
            image=Config.CODE_SANDBOX_IMAGE,
            verbose=False,
        ) as session:
            logger.debug("Sandbox session created, executing code")

            # Execute code with pre-installed libraries
            result = session.run(
                wrapped_code,
                libraries=Config.CODE_SANDBOX_LIBRARIES,
            )

            # Parse output and extract files
            stdout = result.stdout or ""
            output_files, clean_stdout = _parse_output_files_from_stdout(stdout)

            # Extract files from sandbox
            full_result_files: list[dict[str, Any]] = []
            file_metadata: list[dict[str, Any]] = []

            if output_files and result.exit_code == 0:
                full_files, file_metadata = _extract_output_files(session, output_files)
                full_result_files.extend(full_files)
                if file_metadata:
                    logger.info(
                        "Code execution extracted files",
                        extra={
                            "file_count": len(file_metadata),
                            "filenames": [f["name"] for f in file_metadata],
                        },
                    )

            # Extract matplotlib plots
            plot_full_data, plot_metadata = _extract_plots(result)
            full_result_files.extend(plot_full_data)
            if plot_metadata:
                logger.info(
                    "Code execution captured plots", extra={"plot_count": len(plot_metadata)}
                )

            # Build response
            response = _build_execution_response(
                result, clean_stdout, file_metadata, plot_metadata, full_result_files
            )

            # Log execution result
            if result.exit_code == 0:
                logger.info(
                    "Code execution succeeded",
                    extra={
                        "stdout_length": len(response["stdout"]),
                        "has_files": bool(response.get("files")),
                        "has_plots": bool(response.get("plots")),
                    },
                )
            else:
                logger.warning(
                    "Code execution failed",
                    extra={
                        "exit_code": result.exit_code,
                        "stderr_preview": (result.stderr or "")[:500],
                    },
                )

            return json.dumps(response)

    except TimeoutError:
        logger.warning("Code execution timed out")
        return json.dumps(
            {
                "error": f"Code execution timed out after {Config.CODE_SANDBOX_TIMEOUT} seconds.",
                "hint": "Try optimizing your code or breaking it into smaller pieces.",
            }
        )
    except Exception as e:
        error_msg = str(e)
        logger.error("Code execution error", extra={"error": error_msg}, exc_info=True)

        # Provide helpful error messages for common issues
        if "docker" in error_msg.lower() or "connection" in error_msg.lower():
            return json.dumps(
                {
                    "error": "Docker connection failed. The sandbox service is temporarily unavailable.",
                    "hint": "Please try again later or contact the administrator.",
                }
            )

        return json.dumps({"error": f"Code execution failed: {error_msg}"})


# ============================================================================
# File Retrieval Tool
# ============================================================================


@tool
def retrieve_file(
    message_id: str | None = None,
    file_index: int = 0,
    list_files: bool = False,
) -> str | list[dict[str, Any]]:
    """Retrieve a file from conversation history or list all available files.

    Use this tool to:
    - List all files in the conversation to see what's available
    - Retrieve a specific file by message_id and file_index for analysis
    - Get images from earlier messages to use with generate_image as references

    Args:
        message_id: The message ID containing the file. Required unless list_files=True.
        file_index: Index of the file in the message (0-based, default 0).
        list_files: If True, returns a list of all files in the conversation.
                   Ignores message_id and file_index when True.

    Returns:
        For list_files=True: JSON with files array containing message_id, file_index,
                            name, type, and size for each file.
        For file retrieval: Multimodal content with the file data for analysis,
                           or JSON with error field if not found.

    Examples:
        - retrieve_file(list_files=True) - List all files in conversation
        - retrieve_file(message_id="msg-abc123", file_index=0) - Get first file from message
        - retrieve_file(message_id="msg-abc123") - Same as above (file_index defaults to 0)

    After retrieving an image, you can pass it to generate_image using:
        generate_image(prompt="...", retrieved_file_message_id="msg-abc123", retrieved_file_index=0)
    """
    # Import here to avoid circular imports
    from src.db.blob_store import get_blob_store
    from src.db.models import db, make_blob_key

    conv_id, user_id = get_conversation_context()

    if not conv_id or not user_id:
        logger.warning("retrieve_file called without conversation context")
        return json.dumps(
            {
                "error": "No conversation context available. This tool can only be used during a chat."
            }
        )

    # Verify user owns the conversation
    conv = db.get_conversation(conv_id, user_id)
    if not conv:
        logger.warning(
            "retrieve_file: conversation not found or not authorized",
            extra={"conv_id": conv_id, "user_id": user_id},
        )
        return json.dumps({"error": "Conversation not found or not authorized."})

    # List all files in conversation
    if list_files:
        logger.info(
            "retrieve_file: listing files",
            extra={"conv_id": conv_id, "user_id": user_id},
        )
        messages = db.get_messages(conv_id)
        all_files: list[dict[str, Any]] = []

        for msg in messages:
            if msg.files:
                for idx, file in enumerate(msg.files):
                    all_files.append(
                        {
                            "message_id": msg.id,
                            "file_index": idx,
                            "name": file.get("name", f"file_{idx}"),
                            "type": file.get("type", "application/octet-stream"),
                            "size": file.get("size", 0),
                            "role": msg.role.value,  # user or assistant
                        }
                    )

        logger.info(
            "retrieve_file: found files",
            extra={"conv_id": conv_id, "file_count": len(all_files)},
        )
        return json.dumps(
            {
                "files": all_files,
                "count": len(all_files),
                "message": f"Found {len(all_files)} file(s) in conversation."
                if all_files
                else "No files found in conversation.",
            }
        )

    # Retrieve specific file
    if not message_id:
        return json.dumps(
            {
                "error": "message_id is required to retrieve a file. Use list_files=True to see available files."
            }
        )

    logger.info(
        "retrieve_file: retrieving file",
        extra={
            "conv_id": conv_id,
            "message_id": message_id,
            "file_index": file_index,
        },
    )

    # Get the message
    message = db.get_message_by_id(message_id)
    if not message:
        logger.warning(
            "retrieve_file: message not found",
            extra={"message_id": message_id},
        )
        return json.dumps({"error": f"Message not found: {message_id}"})

    # Verify message belongs to this conversation
    if message.conversation_id != conv_id:
        logger.warning(
            "retrieve_file: message belongs to different conversation",
            extra={
                "message_id": message_id,
                "message_conv_id": message.conversation_id,
                "current_conv_id": conv_id,
            },
        )
        return json.dumps({"error": "Message does not belong to this conversation."})

    # Check file exists
    if not message.files or file_index >= len(message.files):
        logger.warning(
            "retrieve_file: file not found",
            extra={
                "message_id": message_id,
                "file_index": file_index,
                "file_count": len(message.files) if message.files else 0,
            },
        )
        return json.dumps(
            {
                "error": f"File index {file_index} not found in message. Message has {len(message.files) if message.files else 0} file(s)."
            }
        )

    file_meta = message.files[file_index]
    file_name = file_meta.get("name", f"file_{file_index}")
    mime_type = file_meta.get("type", "application/octet-stream")
    file_size = file_meta.get("size", 0)

    # Get file data from blob store
    blob_store = get_blob_store()
    blob_key = make_blob_key(message_id, file_index)
    blob_result = blob_store.get(blob_key)

    if blob_result:
        binary_data, stored_mime_type = blob_result
        # Use stored MIME type if available
        if stored_mime_type:
            mime_type = stored_mime_type
    else:
        # Fall back to legacy base64 data in message
        if "data" in file_meta:
            try:
                binary_data = base64.b64decode(file_meta["data"])
            except Exception:
                logger.error(
                    "retrieve_file: failed to decode legacy base64 data",
                    extra={"message_id": message_id, "file_index": file_index},
                )
                return json.dumps({"error": "Failed to read file data."})
        else:
            logger.warning(
                "retrieve_file: no file data found",
                extra={"message_id": message_id, "file_index": file_index},
            )
            return json.dumps({"error": "File data not found in storage."})

    # Encode as base64 for return
    file_base64 = base64.b64encode(binary_data).decode("utf-8")
    file_size = len(binary_data)

    logger.info(
        "retrieve_file: file retrieved successfully",
        extra={
            "message_id": message_id,
            "file_index": file_index,
            "file_name": file_name,
            "mime_type": mime_type,
            "size": file_size,
        },
    )

    # For images and PDFs, return multimodal content for analysis
    if mime_type.startswith("image/") or mime_type == "application/pdf":
        return [
            {
                "type": "text",
                "text": f"Here is {file_name} ({mime_type}, {file_size} bytes) from message {message_id}:",
            },
            {
                "type": "image",  # LangChain uses "image" type for both images and PDFs
                "base64": file_base64,
                "mime_type": mime_type,
            },
        ]

    # For text files, decode and return as text
    if mime_type.startswith("text/") or mime_type in (
        "application/json",
        "application/xml",
    ):
        try:
            text_content = binary_data.decode("utf-8")
            return f"Here is the content of {file_name} ({mime_type}):\n\n{text_content}"
        except UnicodeDecodeError:
            pass  # Fall through to base64 return

    # For other files, return metadata with base64
    return json.dumps(
        {
            "success": True,
            "file": {
                "message_id": message_id,
                "file_index": file_index,
                "name": file_name,
                "type": mime_type,
                "size": file_size,
                "data": file_base64,
            },
        }
    )


def get_available_tools() -> list[Any]:
    """Get the list of available tools, including execute_code if Docker is available.

    This function checks Docker availability on first call and caches the result.
    """
    tools = [fetch_url, web_search, generate_image, retrieve_file]

    # Only add execute_code if sandbox is enabled and Docker is available
    if Config.CODE_SANDBOX_ENABLED:
        # Don't check Docker availability here to avoid slow startup
        # The tool will return an error if Docker is not available when called
        tools.append(execute_code)
        logger.debug("execute_code tool added to available tools")

    return tools


# List of all available tools for the agent
# Note: Use get_available_tools() for dynamic tool list based on Docker availability
TOOLS = get_available_tools()
