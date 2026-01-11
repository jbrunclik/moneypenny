"""Web tools for fetching URLs and searching the web."""

import base64
import json
from typing import Any

import html2text
import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException
from langchain_core.tools import tool

from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


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
