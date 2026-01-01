"""
Create separate blob storage database for files and thumbnails.

This migration initializes the blob store (files.db) which stores file data
and thumbnails separately from the main database. This improves performance
by keeping the main database small and queries fast.

Note: The blob store creates its own table via BlobStore._init_db(), but this
migration ensures the database file exists and is properly initialized during
the standard migration process.
"""

from pathlib import Path

from yoyo import step

from src.config import Config


def create_blob_store(conn):
    """Initialize the blob store database."""
    # Import here to avoid circular imports during migration
    from src.db.blob_store import BlobStore

    # Create blob store - this initializes the database and creates the table
    blob_store = BlobStore(Config.BLOB_STORAGE_PATH)

    # Log that we created it (for migration visibility)
    print(f"Created blob store at {blob_store.db_path}")


def drop_blob_store(conn):
    """Remove the blob store database file."""
    blob_path = Config.BLOB_STORAGE_PATH
    if blob_path.exists():
        blob_path.unlink()
        print(f"Removed blob store at {blob_path}")


steps = [
    step(create_blob_store, drop_blob_store),
]
