"""A news page's publish date from its markup.

The search providers in use return no dates (Linkup, ddgs), so a year-old
article read like a current one: Oct 2026, a pre-departure piece from Oct 2025
"supported" a politician's old party as his current one, for the model and the
grounding check alike. The line built here goes at the top of the extracted
text, like the product line, so no length cap can cut it.

Only pages that declare themselves articles get a date: the only dates on
Wikipedia and hub pages are creation or copyright years, which would make a
maintained page look stale.
"""

import trafilatura

from src.utils.logging import get_logger

logger = get_logger(__name__)


def page_date_line(html: str) -> str:
    """'Published: YYYY-MM-DD' for an article that states its date, else ""."""
    try:
        metadata = trafilatura.extract_metadata(html)
    except Exception:
        logger.debug("Page metadata extraction failed", exc_info=True)
        return ""
    if metadata is None or metadata.pagetype != "article" or not metadata.date:
        return ""
    return f"Published: {metadata.date}"
