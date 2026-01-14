"""Search database operations mixin.

Contains full-text search functionality using FTS5.
"""

import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.db.models.dataclasses import SearchResult
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.utils.connection_pool import ConnectionPool

logger = get_logger(__name__)


class SearchMixin:
    """Mixin providing full-text search database operations."""

    _pool: ConnectionPool

    def _execute_with_timing(
        self,
        conn: sqlite3.Connection,
        query: str,
        params: tuple[Any, ...] = (),
    ) -> sqlite3.Cursor:
        """Execute query with timing (defined in base class)."""
        raise NotImplementedError

    def search(
        self,
        user_id: str,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[SearchResult], int]:
        """Search conversations and messages using FTS5 full-text search.

        Uses BM25 ranking algorithm for relevance scoring. Searches both
        conversation titles and message content. Results are ordered by
        relevance (best matches first).

        The query supports prefix matching - each word is automatically
        treated as a prefix (e.g., "hel wor" matches "hello world").

        Args:
            user_id: The user ID (only searches this user's data)
            query: Search query text
            limit: Maximum number of results to return (default: 20)
            offset: Number of results to skip for pagination (default: 0)

        Returns:
            Tuple of:
            - List of SearchResult objects ordered by relevance
            - Total count of matching results (for pagination UI)
        """
        # Clean and validate query
        query = query.strip()
        if not query:
            return [], 0

        # Escape FTS5 special characters to prevent query syntax errors
        # FTS5 special chars: " * ( ) : ^ -
        escaped_query = query.replace('"', '""')

        # Build prefix-matching query: "hello world" -> "hello"* "world"*
        # This provides better type-ahead search experience
        words = escaped_query.split()
        fts_query = " ".join(f'"{word}"*' for word in words if word)

        if not fts_query:
            return [], 0

        with self._pool.get_connection() as conn:
            # Get ranked results with conversation titles
            # bm25() returns negative scores where more negative = better match
            # snippet() returns text with highlight markers around matches
            #
            # Note: We fetch ALL matching results and deduplicate in Python because:
            # 1. FTS5's bm25() and snippet() functions don't work with GROUP BY
            # 2. The search index may have duplicate entries for the same message
            # 3. We need accurate total counts after deduplication
            rows = self._execute_with_timing(
                conn,
                """
                SELECT
                    si.conversation_id,
                    c.title as conversation_title,
                    si.message_id,
                    CASE
                        WHEN si.type = 'message' THEN snippet(
                            search_index, 5, '[[HIGHLIGHT]]', '[[/HIGHLIGHT]]', '...', 32
                        )
                        ELSE NULL
                    END as message_snippet,
                    si.type as match_type,
                    bm25(search_index) as rank,
                    m.created_at as message_created_at
                FROM search_index si
                JOIN conversations c ON c.id = si.conversation_id
                LEFT JOIN messages m ON m.id = si.message_id
                WHERE si.user_id = ? AND search_index MATCH ?
                ORDER BY rank ASC, message_created_at DESC NULLS LAST
                """,
                (user_id, fts_query),
            ).fetchall()

            if not rows:
                return [], 0

            # Deduplicate results in Python by message_id (for message matches)
            # or conversation_id (for title matches). This handles duplicate
            # index entries that can occur due to trigger timing or other issues.
            seen: set[str] = set()
            unique_results: list[SearchResult] = []

            for row in rows:
                # Use message_id as unique key for message matches,
                # conversation_id for title matches
                unique_key = row["message_id"] or row["conversation_id"]
                if unique_key in seen:
                    continue
                seen.add(unique_key)

                unique_results.append(
                    SearchResult(
                        conversation_id=row["conversation_id"],
                        conversation_title=row["conversation_title"],
                        message_id=row["message_id"],
                        message_content=row["message_snippet"],
                        match_type=row["match_type"],
                        rank=float(row["rank"]),
                        created_at=(
                            datetime.fromisoformat(row["message_created_at"])
                            if row["message_created_at"]
                            else None
                        ),
                    )
                )

            # Total count is the number of unique results
            total_count = len(unique_results)

            # Apply pagination after deduplication
            paginated_results = unique_results[offset : offset + limit]

            logger.debug(
                "Search completed",
                extra={
                    "user_id": user_id,
                    "query": query,
                    "results": len(paginated_results),
                    "total": total_count,
                },
            )

            return paginated_results, total_count
