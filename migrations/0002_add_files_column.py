"""
Add files column to messages table.

Separates file attachments from message content for cleaner data model.
- content: Plain text message (string)
- files: JSON array of file objects (nullable)

Migrates existing JSON-structured content to the new format.
"""

import json

from yoyo import step


def migrate_content_to_files(conn):
    """Extract files from JSON content and move to files column."""
    cursor = conn.cursor()

    # Get all messages
    cursor.execute("SELECT id, content FROM messages")
    rows = cursor.fetchall()

    for row in rows:
        msg_id, content = row

        # Try to parse as JSON
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict) and ("text" in parsed or "files" in parsed):
                # This is structured content - migrate it
                text = parsed.get("text", "")
                files = parsed.get("files", [])
                files_json = json.dumps(files) if files else None

                cursor.execute(
                    "UPDATE messages SET content = ?, files = ? WHERE id = ?",
                    (text, files_json, msg_id)
                )
        except (json.JSONDecodeError, TypeError):
            # Plain string content - leave as-is, files stays NULL
            pass

    conn.commit()


def migrate_files_to_content(conn):
    """Rollback: merge files back into content as JSON."""
    cursor = conn.cursor()

    # Get all messages with files
    cursor.execute("SELECT id, content, files FROM messages WHERE files IS NOT NULL")
    rows = cursor.fetchall()

    for row in rows:
        msg_id, content, files_json = row
        files = json.loads(files_json) if files_json else []

        # Reconstruct JSON content
        structured = {"text": content, "files": files}
        cursor.execute(
            "UPDATE messages SET content = ? WHERE id = ?",
            (json.dumps(structured), msg_id)
        )

    conn.commit()


steps = [
    # Add the files column
    step(
        "ALTER TABLE messages ADD COLUMN files TEXT",
        # SQLite doesn't support DROP COLUMN easily, but for rollback we just ignore it
        ""
    ),
    # Migrate existing data
    step(
        migrate_content_to_files,
        migrate_files_to_content
    ),
]
