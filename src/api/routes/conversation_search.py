"""Conversation search route (full-text search across titles and messages).

Attached to conversations.api (one shared "Conversations" blueprint keeps a
single OpenAPI tag and the original endpoint names).
"""

from typing import Any

from flask import request

from src.api.errors import raise_validation_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.routes.conversations import api
from src.api.schemas.conversations import SearchResultsResponse
from src.auth.jwt_auth import require_auth
from src.config import Config
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)


@api.route("/search", methods=["GET"])
@api.output(SearchResultsResponse)
@api.doc(responses=[400, 429])
@rate_limit_conversations
@require_auth
def search_conversations(user: User) -> dict[str, Any]:
    """Search across all conversations and messages.

    Uses full-text search with BM25 ranking. Searches both conversation
    titles and message content. Results are ordered by relevance.

    Query parameters:
    - q: Search query (required, 1-200 characters)
    - limit: Number of results to return (default: 20, max: 50)
    - offset: Number of results to skip for pagination (default: 0)

    Returns:
    - results: Array of search results with conversation info and message snippets
    - total: Total number of matching results
    - query: The search query that was executed
    """
    query = request.args.get("q", "").strip()

    # Validate query
    if not query:
        raise_validation_error("Search query is required", field="q")
    if len(query) > Config.SEARCH_MAX_QUERY_LENGTH:
        raise_validation_error(
            f"Search query too long (max {Config.SEARCH_MAX_QUERY_LENGTH} characters)",
            field="q",
        )

    # Parse pagination parameters
    try:
        limit = min(int(request.args.get("limit", 20)), Config.SEARCH_MAX_LIMIT)
        limit = max(1, limit)
    except ValueError:
        limit = 20

    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        offset = 0

    logger.debug(
        "Search request",
        extra={"user_id": user.id, "query": query, "limit": limit, "offset": offset},
    )

    results, total = db.search(user.id, query, limit=limit, offset=offset)

    logger.info(
        "Search completed",
        extra={"user_id": user.id, "query": query, "results": len(results), "total": total},
    )

    return {
        "results": [
            {
                "conversation_id": r.conversation_id,
                "conversation_title": r.conversation_title,
                "message_id": r.message_id,
                "message_snippet": r.message_content,
                "match_type": r.match_type,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in results
        ],
        "total": total,
        "query": query,
    }
