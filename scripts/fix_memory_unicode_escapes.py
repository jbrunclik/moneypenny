#!/usr/bin/env python3
"""Repair memories poisoned with literal \\uXXXX escape sequences.

The memory list used to be injected into the prompt with json.dumps'
default ensure_ascii=True, so the model saw Czech text as \\u0159-style
escapes and copied them back into STORED content when consolidating
memories. The injection is fixed (ensure_ascii=False); this repairs
existing rows and re-embeds them.

Usage:
    python scripts/fix_memory_unicode_escapes.py [--dry-run]
"""

import argparse
import re
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")


def decode_escapes(text: str) -> str:
    """Replace literal \\uXXXX sequences with their characters (BMP only)."""
    return _ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # No src.db.models import: constructing a second Database would contend
    # for the yoyo migration lock against the live app. Raw SQL only.

    from src.config import Config
    from src.utils.embeddings import embed_text, pack_vector

    conn = sqlite3.connect(Config.DATABASE_PATH, timeout=30)
    rows = conn.execute(
        r"SELECT id, user_id, content FROM user_memories WHERE content LIKE '%\u%'"
    ).fetchall()

    repaired = 0
    for memory_id, user_id, content in rows:
        fixed = decode_escapes(content)
        if fixed == content:
            continue
        print(f"{'DRY ' if args.dry_run else ''}repair {memory_id}: ...{fixed[:60]!r}...")
        if not args.dry_run:
            conn.execute("UPDATE user_memories SET content = ? WHERE id = ?", (fixed, memory_id))
            repaired += 1
            # Re-embed from the repaired text (the old vector encoded escapes)
            vec = embed_text(fixed)
            if vec is not None:
                conn.execute(
                    """INSERT INTO embeddings (id, user_id, kind, ref_id, model, dim, vector, created_at)
                       VALUES (?, ?, 'memory', ?, ?, ?, ?, ?)
                       ON CONFLICT(kind, ref_id) DO UPDATE SET
                           model = excluded.model, dim = excluded.dim,
                           vector = excluded.vector, created_at = excluded.created_at""",
                    (
                        str(uuid.uuid4()),
                        user_id,
                        memory_id,
                        Config.EMBEDDING_MODEL,
                        len(vec),
                        pack_vector(vec),
                        datetime.now().isoformat(),
                    ),
                )

    if not args.dry_run:
        conn.commit()
    conn.close()
    print(f"{len(rows)} candidate row(s), {repaired} repaired")
    return 0


if __name__ == "__main__":
    sys.exit(main())
