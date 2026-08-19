"""
Embeddings for semantic recall over memories and messages.

Brute-force cosine at family scale (a few thousand vectors) - no vector index
extension needed. kind: 'memory' | 'message'; ref_id: the source row id;
vector: packed float32 (struct), dim recorded so model/dim changes can coexist
during a re-embed.
"""

from yoyo import step

__depends__ = {"0048_upgrade_fast_model"}

steps = [
    step(
        """
        CREATE TABLE embeddings (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            ref_id TEXT NOT NULL,
            model TEXT NOT NULL,
            dim INTEGER NOT NULL,
            vector BLOB NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(kind, ref_id)
        )
        """,
        "DROP TABLE embeddings",
    ),
    step(
        "CREATE INDEX idx_embeddings_user_kind ON embeddings(user_id, kind)",
        "DROP INDEX IF EXISTS idx_embeddings_user_kind",
    ),
]
