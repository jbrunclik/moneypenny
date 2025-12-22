"""Web tools for the AI agent."""

import html2text
import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS
from langchain_core.tools import tool


def _extract_text_from_html(html: str, max_length: int = 15000) -> str:
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
    if len(text) > max_length:
        text = text[:max_length] + "\n\n[Content truncated...]"

    return text.strip()


@tool
def fetch_url(url: str) -> str:
    """Fetch and extract text content from a URL.

    Use this tool to read the content of a web page. Returns the main text
    content in markdown format.

    Args:
        url: The URL to fetch (must start with http:// or https://)

    Returns:
        The text content of the page in markdown format
    """
    if not url.startswith(("http://", "https://")):
        return f"Error: Invalid URL '{url}'. URL must start with http:// or https://"

    try:
        with httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            },
        ) as client:
            response = client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return f"Error: URL returned non-text content type: {content_type}"

            return _extract_text_from_html(response.text)

    except httpx.TimeoutException:
        return f"Error: Request to {url} timed out"
    except httpx.HTTPStatusError as e:
        return f"Error: HTTP {e.response.status_code} when fetching {url}"
    except httpx.RequestError as e:
        return f"Error: Failed to fetch {url}: {e}"


@tool
def web_search(query: str, num_results: int = 5) -> str:
    """Search the web using DuckDuckGo.

    Use this tool to find current information, news, prices, or any other
    information that might not be in your training data. After searching,
    you can use fetch_url to read specific pages.

    Args:
        query: The search query
        num_results: Number of results to return (default 5, max 10)

    Returns:
        JSON with search results containing title, URL, and snippet
    """
    import json

    num_results = min(max(1, num_results), 10)

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))

        if not results:
            return json.dumps(
                {"query": query, "results": [], "error": None}, ensure_ascii=False, indent=2
            )

        # Structure results as JSON
        structured_results = []
        for r in results:
            structured_results.append(
                {
                    "title": r.get("title", "No title"),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
            )

        return json.dumps(
            {
                "query": query,
                "results": structured_results,
                "error": None,
            },
            ensure_ascii=False,
            indent=2,
        )

    except Exception as e:
        return json.dumps(
            {"query": query, "results": [], "error": str(e)}, ensure_ascii=False, indent=2
        )


# List of all available tools for the agent
TOOLS = [fetch_url, web_search]
