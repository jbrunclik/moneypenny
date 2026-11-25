"""Search database operations mixin.

Contains full-text search functionality using FTS5.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.config import Config
from src.db.models.dataclasses import RecentConversation, SearchResult
from src.db.models.timestamps import from_db, from_db_or_none, to_db
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
        after: datetime | None = None,
        before: datetime | None = None,
        exclude_conversation_id: str | None = None,
        keep_message_ids: set[str] | None = None,
    ) -> tuple[list[SearchResult], int]:
        """Search conversation titles and messages (FTS5, BM25 ranked).

        Every word is a prefix and all must match. When that finds fewer than
        ``CONVERSATION_SEARCH_FALLBACK_MIN_RESULTS``, an any-word query with
        Czech endings trimmed runs too and its new hits follow the strict ones
        (``match_mode="any"``) - one inflected or wrong word no longer empties
        the result. ``after`` (inclusive) and ``before`` (exclusive) bound the
        message time (a title match: any of the conversation's messages).
        ``exclude_conversation_id`` (the chat already in the agent's context)
        is dropped before the fallback threshold, except ``keep_message_ids``
        (its summarized part) - its hits must not stop the fallback.

        Returns the page of results and the total after deduplication.
        """
        query = query.strip()
        strict = fts_query(query)
        if not strict:
            return [], 0

        keep = keep_message_ids or set()

        def wanted(results: list[SearchResult]) -> list[SearchResult]:
            return [
                r
                for r in results
                if r.conversation_id != exclude_conversation_id or r.message_id in keep
            ]

        with self._pool.get_connection() as conn:
            unique_results = wanted(
                _unique_results(self._match_rows(conn, user_id, strict, after, before))
            )
            if len(unique_results) < Config.CONVERSATION_SEARCH_FALLBACK_MIN_RESULTS:
                any_query = fts_query(query, any_words=True)
                if any_query != strict:
                    seen = {r.message_id or r.conversation_id for r in unique_results}
                    unique_results += [
                        replace(r, match_mode="any")
                        for r in wanted(
                            _unique_results(
                                self._match_rows(
                                    conn, user_id, any_query, after, before, ANY_ROW_LIMIT
                                )
                            )
                        )
                        if (r.message_id or r.conversation_id) not in seen
                    ]

        total_count = len(unique_results)
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

    def _match_rows(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        match: str,
        after: datetime | None,
        before: datetime | None,
        row_limit: int = -1,
    ) -> list[sqlite3.Row]:
        """The ranked FTS rows for one MATCH expression ([] if FTS rejects it).

        bm25() is negative, more negative = better; it and snippet() don't
        work with GROUP BY, so duplicates are dropped in Python.
        """
        after_db = to_db(after) if after else None
        before_db = to_db(before) if before else None
        bounds = (after_db, after_db, before_db, before_db)
        try:
            return list(
                self._execute_with_timing(
                    conn,
                    """
                    SELECT
                        si.conversation_id,
                        c.title as conversation_title,
                        (SELECT p.name FROM projects p
                         WHERE p.id = c.project_id AND p.deleted_at IS NULL) AS project_name,
                        si.message_id,
                        CASE
                            WHEN si.type = 'message' THEN snippet(
                                search_index, 5, '[[HIGHLIGHT]]', '[[/HIGHLIGHT]]', '...', 32
                            )
                            -- an artifact's title (column 4) is its snippet
                            WHEN si.type = 'artifact' THEN snippet(
                                search_index, 4, '[[HIGHLIGHT]]', '[[/HIGHLIGHT]]', '...', 32
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
                      AND c.deleted_at IS NULL
                      AND (
                        (? IS NULL AND ? IS NULL)
                        OR (m.id IS NOT NULL
                            AND (? IS NULL OR m.created_at >= ?)
                            AND (? IS NULL OR m.created_at < ?))
                        OR (m.id IS NULL AND EXISTS (
                            SELECT 1 FROM messages mm WHERE mm.conversation_id = c.id
                              AND (? IS NULL OR mm.created_at >= ?)
                              AND (? IS NULL OR mm.created_at < ?)))
                      )
                    ORDER BY rank ASC, message_created_at DESC NULLS LAST
                    LIMIT ?
                    """,
                    (user_id, match, after_db, before_db, *bounds, *bounds, row_limit),
                ).fetchall()
            )
        except sqlite3.OperationalError as exc:
            # A query the FTS5 grammar still rejects after escaping: no hits
            logger.warning("Search query rejected", extra={"error": str(exc)})
            return []

    def recent_conversations(
        self,
        user_id: str,
        after: datetime | None,
        before: datetime | None,
        limit: int,
    ) -> list[RecentConversation]:
        """Conversations with a message in ``[after, before)``, newest activity first.

        Each comes with its first user message (cut to 200 chars) so a list
        answers "what did we talk about yesterday"; trashed ones are left out.
        """
        after_db = to_db(after) if after else None
        before_db = to_db(before) if before else None
        with self._pool.get_connection() as conn:
            rows = self._execute_with_timing(
                conn,
                """
                SELECT c.id, c.title, MAX(m.created_at) AS last_at,
                       (SELECT u.content FROM messages u
                         WHERE u.conversation_id = c.id AND u.role = 'user'
                         ORDER BY u.created_at LIMIT 1) AS first_user
                FROM conversations c
                JOIN messages m ON m.conversation_id = c.id
                WHERE c.user_id = ? AND c.deleted_at IS NULL
                  AND (? IS NULL OR m.created_at >= ?)
                  AND (? IS NULL OR m.created_at < ?)
                GROUP BY c.id
                ORDER BY last_at DESC
                LIMIT ?
                """,
                (user_id, after_db, after_db, before_db, before_db, limit),
            ).fetchall()
        return [
            RecentConversation(
                conversation_id=row[0],
                title=row[1],
                last_message_at=from_db(row[2]),
                first_user_message=(row[3] or "")[:_FIRST_MESSAGE_CHARS],
            )
            for row in rows
        ]


# The recent-chats listing shows this much of each chat's first user message
_FIRST_MESSAGE_CHARS = 200

# The any-word fallback reads at most this many rows: a common word ORed in
# would otherwise run snippet() and bm25() on every message that has it
ANY_ROW_LIMIT = 200

# The any-word fallback: words shorter than this are dropped (unless no word
# is left), longer ones from _TRIM_FROM lose _TRIM_CHARS as a crude Czech
# ending trim ("olympiáda" -> "olympiá*" also matches "olympiády")
_ANY_MIN_WORD = 3
_TRIM_FROM = 6
_TRIM_CHARS = 2


def fts_query(query: str, any_words: bool = False) -> str:
    """The FTS5 MATCH expression for a stripped query ("" when it has no words).

    Default: every word a prefix, all required ("hel wor" matches "hello
    world"). ``any_words``: the words ORed, words under 3 letters dropped and
    long ones trimmed; a query of only short words has nothing to loosen and
    gets the strict expression (ORing "a", "je", "to" matches nearly every
    Czech message).
    """
    words = [word for word in query.split() if word]
    if any_words:
        kept = [word for word in words if len(word) >= _ANY_MIN_WORD]
        if not kept:
            return fts_query(query)
        words = [word[:-_TRIM_CHARS] if len(word) >= _TRIM_FROM else word for word in kept]
    return (" OR " if any_words else " ").join(_term(word) for word in words)


def _term(word: str) -> str:
    """One quoted FTS term; a prefix unless it holds a single letter or digit.

    "C++" tokenizes to "c", and ``"c"*`` matched every word starting with c.
    Quotes are doubled after any trim, so no escape is cut in half.
    """
    quoted = '"' + word.replace('"', '""') + '"'
    return quoted + "*" if sum(char.isalnum() for char in word) >= 2 else quoted


def _unique_results(rows: list[sqlite3.Row]) -> list[SearchResult]:
    """The rows as SearchResults, one per message (or title) match."""
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
                created_at=from_db_or_none(row["message_created_at"]),
                project_name=row["project_name"],
            )
        )

    return unique_results
