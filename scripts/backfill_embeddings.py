#!/usr/bin/env python3
"""Backfill embeddings for existing memories and messages.

New writes are embedded automatically (db.add_message hook + manage_memory);
this script covers rows created before the embeddings feature shipped.

Usage:
    python scripts/backfill_embeddings.py [--dry-run] [--kind memory|message]
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# Courtesy pause between embedding API calls
_SLEEP_BETWEEN_CALLS_SECONDS = 0.2


def _rows_missing_embeddings(conn: sqlite3.Connection, kind: str) -> list[tuple[str, str, str]]:
    """(ref_id, user_id, content) rows of `kind` that have no embedding yet."""
    if kind == "memory":
        query = """
            SELECT m.id, m.user_id, m.content FROM user_memories m
            LEFT JOIN embeddings e ON e.kind = 'memory' AND e.ref_id = m.id
            WHERE e.id IS NULL AND m.deleted_at IS NULL AND TRIM(m.content) != ''
        """
    else:
        query = """
            SELECT msg.id, c.user_id, msg.content FROM messages msg
            JOIN conversations c ON c.id = msg.conversation_id
            LEFT JOIN embeddings e ON e.kind = 'message' AND e.ref_id = msg.id
            WHERE e.id IS NULL AND TRIM(msg.content) != ''
        """
    return [(row[0], row[1], row[2]) for row in conn.execute(query).fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="only count, don't embed")
    parser.add_argument("--kind", choices=["memory", "message"], help="limit to one kind")
    args = parser.parse_args()

    from src.config import Config
    from src.db.models import db
    from src.utils.embeddings import embed_text, pack_vector

    kinds = [args.kind] if args.kind else ["memory", "message"]

    with sqlite3.connect(Config.DATABASE_PATH) as conn:
        pending = {kind: _rows_missing_embeddings(conn, kind) for kind in kinds}

    for kind, rows in pending.items():
        print(f"{kind}: {len(rows)} rows missing embeddings")

    if args.dry_run:
        return 0

    embedded = 0
    failed = 0
    for kind, rows in pending.items():
        for i, (ref_id, user_id, content) in enumerate(rows, 1):
            vec = embed_text(content)
            if vec is None:
                failed += 1
            else:
                db.upsert_embedding(
                    user_id, kind, ref_id, Config.EMBEDDING_MODEL, len(vec), pack_vector(vec)
                )
                embedded += 1
            if i % 50 == 0:
                print(f"  {kind}: {i}/{len(rows)}")
            time.sleep(_SLEEP_BETWEEN_CALLS_SECONDS)

    print(f"Done: {embedded} embedded, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
