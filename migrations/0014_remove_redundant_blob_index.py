"""
Remove redundant idx_blobs_key_prefix index from blob store.

The index was redundant because the PRIMARY KEY on 'key' already provides
a B-tree index that SQLite uses for both exact matches and LIKE prefix queries.
"""

import sqlite3
from pathlib import Path

from yoyo import step

from src.config import Config


def drop_redundant_index(conn):
    """Drop the redundant index from blob store."""
    blob_path = Config.BLOB_STORAGE_PATH
    if not blob_path.exists():
        print(f"Blob store not found at {blob_path}, skipping")
        return

    blob_conn = sqlite3.connect(blob_path)
    try:
        blob_conn.execute("DROP INDEX IF EXISTS idx_blobs_key_prefix")
        blob_conn.commit()
        print(f"Dropped redundant idx_blobs_key_prefix from {blob_path}")
    finally:
        blob_conn.close()


def recreate_index(conn):
    """Recreate the index for rollback (though it's redundant)."""
    blob_path = Config.BLOB_STORAGE_PATH
    if not blob_path.exists():
        print(f"Blob store not found at {blob_path}, skipping")
        return

    blob_conn = sqlite3.connect(blob_path)
    try:
        blob_conn.execute("CREATE INDEX IF NOT EXISTS idx_blobs_key_prefix ON blobs(key)")
        blob_conn.commit()
        print(f"Recreated idx_blobs_key_prefix on {blob_path}")
    finally:
        blob_conn.close()


steps = [
    step(drop_redundant_index, recreate_index),
]
