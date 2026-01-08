"""
Detect and populate language field for existing assistant messages.

This migration:
1. Reads all assistant messages with NULL language field
2. Uses langdetect library to detect the language
3. Updates the language column with the detected ISO 639-1 code

The migration is idempotent - it only processes messages without a language set.
"""

from yoyo import step

from src.utils.logging import get_logger

logger = get_logger(__name__)


def detect_message_languages(conn):
    """Detect language for existing assistant messages."""
    try:
        from langdetect import detect, LangDetectException
    except ImportError:
        print("Warning: langdetect not installed. Run 'pip install langdetect' first.")
        print("Skipping language detection - you can re-run this migration later.")
        return

    # Count messages to process
    cursor = conn.execute(
        """
        SELECT COUNT(*) FROM messages
        WHERE role = 'assistant' AND language IS NULL AND content IS NOT NULL AND content != ''
        """
    )
    total_messages = cursor.fetchone()[0]
    print(f"Found {total_messages} assistant messages without language")

    if total_messages == 0:
        print("No messages to process")
        return

    # Process messages in batches
    batch_size = 100
    offset = 0
    detected_count = 0
    failed_count = 0

    while offset < total_messages:
        cursor = conn.execute(
            """
            SELECT id, content FROM messages
            WHERE role = 'assistant' AND language IS NULL AND content IS NOT NULL AND content != ''
            ORDER BY created_at
            LIMIT ? OFFSET ?
            """,
            (batch_size, offset),
        )
        rows = cursor.fetchall()

        if not rows:
            break

        for row in rows:
            message_id = row[0]
            content = row[1]

            try:
                # Detect language from content
                detected_lang = detect(content)
                # Normalize to 2-char ISO 639-1 code
                lang_code = detected_lang[:2].lower()

                conn.execute(
                    "UPDATE messages SET language = ? WHERE id = ?",
                    (lang_code, message_id),
                )
                detected_count += 1
            except LangDetectException:
                # Language detection failed (e.g., content too short or ambiguous)
                failed_count += 1
            except Exception as e:
                print(f"  Warning: Failed to detect language for message {message_id}: {e}")
                failed_count += 1

        conn.commit()
        offset += batch_size
        print(f"  Processed {min(offset, total_messages)}/{total_messages} messages...")

    print(f"Language detection complete:")
    print(f"  - Detected language for {detected_count} messages")
    print(f"  - Failed to detect for {failed_count} messages")


def rollback_languages(conn):
    """Rollback: Clear all detected languages.

    Note: This will clear languages for all messages, including those
    set during chat (not just those detected by this migration).
    You may want to run the forward migration again after rollback.
    """
    cursor = conn.execute("UPDATE messages SET language = NULL WHERE language IS NOT NULL")
    print(f"Cleared language for {cursor.rowcount} messages")
    conn.commit()


steps = [
    step(detect_message_languages, rollback_languages),
]
