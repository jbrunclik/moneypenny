# Database Architecture

The app uses SQLite for data storage with a separate blob storage database for files and thumbnails.

## Database Files

- **`chatbot.db`** - Main database (users, conversations, messages with metadata)
- **`files.db`** - Blob storage (file data, thumbnails)

## Blob Storage

File data and thumbnails are stored in a separate SQLite database to keep the main database small and fast.

### Why Separate Blob Storage

- Main DB stays small (~KB per message instead of ~MB with embedded images)
- Faster queries on conversations and messages (no large BLOB columns)
- Native SQLite BLOB storage is ~33% smaller than base64-encoded JSON
- Easier backup strategies (can backup main DB more frequently)

### Key Format

Blobs are stored with keys that encode the message and file index:

- **Files**: `{message_id}/{index}` (e.g., `msg-abc123/0`)
- **Thumbnails**: `{message_id}/{index}.thumb` (e.g., `msg-abc123/0.thumb`)

### How It Works

**1. Message creation** - When a message with files is saved:
- File metadata (name, type, size, has_thumbnail) stored in `messages.files` JSON column
- File binary data extracted from base64, saved to blob store
- Thumbnail data (if present) saved separately with `.thumb` suffix

**2. File retrieval** - `/api/messages/<id>/files/<idx>` endpoint:
- First tries blob store lookup with `{message_id}/{index}` key
- Falls back to legacy base64 in `messages.files` JSON (for unmigrated messages)

**3. Thumbnail retrieval** - `/api/messages/<id>/files/<idx>/thumbnail` endpoint:
- First tries blob store lookup with `{message_id}/{index}.thumb` key
- Falls back to legacy `thumbnail` field in files JSON

**4. Conversation deletion**:
- Uses `delete_by_prefixes()` to delete all blobs for all messages in a single SQL query (batched deletion)

### Indexing

The blob store uses `key TEXT PRIMARY KEY` which automatically provides a B-tree index:
- Exact key lookups (`WHERE key = ?`)
- Prefix queries (`WHERE key LIKE 'prefix%'`) - SQLite uses the B-tree for left-anchored LIKE patterns

No additional indexes are needed.

### Configuration

```bash
# .env
BLOB_STORAGE_PATH=files.db  # Path relative to project root (default: files.db)
```

### Migration

Existing messages are migrated via yoyo migration `0012_migrate_files_to_blob_store.py`:
- Processes messages in batches of 100
- Extracts base64 data → saves to blob store
- Updates JSON to remove `data`/`thumbnail`, add `size`/`has_thumbnail`
- Idempotent (skips already migrated files)
- Has rollback support

### Key Files

- [blob_store.py](../../src/db/blob_store.py) - `BlobStore` class with CRUD methods
- [models.py](../../src/db/models.py) - Blob key helpers, file metadata extraction
- [routes.py](../../src/api/routes.py) - File/thumbnail endpoints with blob store + legacy fallback
- [config.py](../../src/config.py) - Configuration
- [0011_create_blob_store.py](../../migrations/0011_create_blob_store.py) - Creates blob store DB
- [0012_migrate_files_to_blob_store.py](../../migrations/0012_migrate_files_to_blob_store.py) - Migrates existing data

### Testing

- Unit tests: [test_blob_store.py](../../tests/unit/test_blob_store.py)
- Test fixtures use isolated blob stores per test (see `test_blob_store` fixture in conftest.py)

---

## Connection Pooling

The application uses thread-local connection pooling to avoid the overhead of repeatedly opening and closing database connections.

### How It Works

1. Each thread gets its own connection that's reused for all operations
2. Connections are stored in a thread-local variable and tracked for cleanup
3. Broken connections are detected and replaced automatically
4. WAL (Write-Ahead Logging) mode is enabled for better concurrent read/write performance

### Why Thread-Local Instead of Traditional Pool

- SQLite uses file-level locking, so connection pools don't improve concurrency
- Reusing connections within a thread avoids open/close overhead
- Thread-local connections avoid thread-safety issues without explicit locking

### Key Features

- Automatic connection health checking (verifies connection with `SELECT 1`)
- Graceful handling of broken connections (creates new connection if broken)
- Rollback on exceptions (uncommitted transactions are rolled back)
- Proper cleanup on shutdown (`close()` method closes all connections)

### Usage in Code

```python
# Both Database and BlobStore use the same pattern
with self._pool.get_connection() as conn:
    conn.execute("SELECT * FROM users")
    conn.commit()
```

### Key Files

- [connection_pool.py](../../src/utils/connection_pool.py) - `ConnectionPool` class
- [models.py](../../src/db/models.py) - `Database` class uses `self._pool`
- [blob_store.py](../../src/db/blob_store.py) - `BlobStore` class uses `self._pool`

---

## Database Indexes

The following indexes are defined to optimize common query patterns:

### Conversations Table

- `idx_conversations_user_id` - For filtering by user
- `idx_conversations_user_id_updated_at` - Composite index for `list_conversations()` (filter + sort)

### Messages Table

- `idx_messages_conversation_id` - For filtering by conversation
- `idx_messages_conversation_id_created_at` - Composite index for `get_messages()` (filter + sort)

### Message Costs Table

- `idx_message_costs_message_id` - For cost lookups by message
- `idx_message_costs_conversation_id` - For conversation cost totals
- `idx_message_costs_user_id` - For user cost queries
- `idx_message_costs_created_at` - For date-based queries

---

## Slow Query Logging

In development/debug mode, the database tracks query execution time and logs warnings for slow queries.

### Configuration

- `SLOW_QUERY_THRESHOLD_MS`: Threshold in milliseconds (default: 100)
- Enabled when `LOG_LEVEL=DEBUG` or `FLASK_ENV=development`

### Log Output

```json
{
  "level": "WARNING",
  "message": "Slow query detected",
  "query_snippet": "SELECT * FROM conversations WHERE user_id = ? ORDER BY...",
  "params_snippet": "('user-123-abc',)",
  "elapsed_ms": 150.5,
  "threshold_ms": 100
}
```

### Security Considerations

- Query text is truncated to 200 characters
- Parameters are truncated to 100 characters (to avoid logging large base64 file data)

### Implementation

The query timing logic is centralized in [db_helpers.py](../../src/utils/db_helpers.py):
- `execute_with_timing()` - Executes queries with optional timing and logging
- `init_query_logging()` - Returns configuration tuple `(should_log, threshold_ms)`

Both [models.py](../../src/db/models.py) and [blob_store.py](../../src/db/blob_store.py) delegate to these shared helpers.
The blob store uses `log_prefix="Blob "` to distinguish its logs from main database logs.

---

## Database Connectivity Check

At startup, the application verifies database connectivity before starting the Flask app.

### Checks Performed

1. Parent directory exists
2. Parent directory is writable
3. Database file is readable/writable (if exists)
4. Can connect and execute `SELECT 1`

### Error Handling

- **Missing directory**: Clear message about missing directory
- **Permission errors**: Guidance on file/directory permissions
- **Database locked**: Indicates another process is using it
- **Disk I/O errors**: Suggests checking disk health

### Key Files

- [models.py](../../src/db/models.py) - `check_database_connectivity()`
- [app.py](../../src/app.py) - Startup connectivity check in `main()`
- [config.py](../../src/config.py) - `SLOW_QUERY_THRESHOLD_MS` setting

---

## Database Vacuum

SQLite databases can accumulate unused space over time as data is deleted. The VACUUM command reclaims this space and optimizes the database file.

### Automatic Vacuum (systemd timer)

- Runs weekly on Sunday at 3:00 AM (with up to 1 hour random delay)
- Vacuums both `chatbot.db` (main database) and `files.db` (blob storage)
- Automatically enabled when running `make deploy`
- Check timer status: `systemctl --user list-timers`
- View vacuum logs: `journalctl --user -u ai-chatbot-vacuum`

### Manual Vacuum

```bash
make vacuum  # Run vacuum immediately
```

### What VACUUM Does

- Rebuilds the database file, reclaiming space from deleted rows
- Defragments the database for better read performance
- Requires exclusive access (no concurrent writes during vacuum)

### Key Files

- [vacuum_databases.py](../../scripts/vacuum_databases.py) - Python script that runs VACUUM on both databases
- [ai-chatbot-vacuum.service](../../systemd/ai-chatbot-vacuum.service) - Systemd service (oneshot)
- [ai-chatbot-vacuum.timer](../../systemd/ai-chatbot-vacuum.timer) - Systemd timer (weekly)

---

## Database Backup

Daily automated backups create timestamped snapshots of both SQLite databases, keeping 7 days of history by default.

### Automatic Backup (systemd timer)

- Runs daily at 2:00 AM (with up to 30 min random delay)
- Backs up both `chatbot.db` (main database) and `files.db` (blob storage)
- Uses SQLite's online backup API for consistent snapshots even while the database is in use
- Automatically enabled when running `make deploy`
- Check timer status: `systemctl --user list-timers`
- View backup logs: `journalctl --user -u ai-chatbot-backup`

### Manual Backup

```bash
make backup       # Create backup immediately
make backup-list  # List existing backups with sizes and ages
```

### Backup Location

Backups are stored in `backups/{database_name}/` directories alongside the databases:
- `backups/chatbot.db/chatbot-20240101-120000.db`
- `backups/files.db/files-20240101-120000.db`

### Retention

- Default: 7 days (configurable via `--retention` flag)
- Old backups are automatically cleaned up after each backup run

### Key Files

- [backup_databases.py](../../scripts/backup_databases.py) - Python script for backup and cleanup
- [ai-chatbot-backup.service](../../systemd/ai-chatbot-backup.service) - Systemd service (oneshot)
- [ai-chatbot-backup.timer](../../systemd/ai-chatbot-backup.timer) - Systemd timer (daily)

### Testing

- Unit tests: [test_backup.py](../../tests/unit/test_backup.py)

---

## Database Best Practices

When adding or modifying database code, follow these guidelines:

### Avoiding N+1 Queries

- Never query inside a loop - fetch all needed data in a single query
- Use JOINs or subqueries when you need related data
- If you need to load a list of items with counts/aggregates, use a single query with GROUP BY

```python
# BAD - N+1 pattern (1 query + N queries)
conversations = db.list_conversations(user_id)
for conv in conversations:
    count = db.get_message_count(conv.id)  # N queries!

# GOOD - Single query with JOIN or subquery
conversations = db.list_conversations_with_counts(user_id)  # 1 query
```

### When to Add Indexes

- Add indexes on columns used in WHERE clauses (e.g., `user_id`, `conversation_id`)
- Add composite indexes for queries that filter AND sort (e.g., `(user_id, updated_at DESC)`)
- Primary keys and UNIQUE constraints already have indexes
- Don't over-index - each index slows down INSERT/UPDATE operations

### Index Naming Convention

```sql
-- Single column: idx_{table}_{column}
CREATE INDEX idx_conversations_user_id ON conversations(user_id)

-- Composite: idx_{table}_{col1}_{col2}
CREATE INDEX idx_conversations_user_id_updated_at ON conversations(user_id, updated_at DESC)
```

### Query Patterns in This Codebase

- All queries go through `_execute_with_timing()` for automatic slow query detection
- Use parameterized queries (`?` placeholders) - never string concatenation for VALUES
- **Dynamic column names**: If you must build SQL with dynamic column names (e.g., for UPDATE statements), use a whitelist. See `_CONVERSATION_UPDATE_COLUMNS` in [models.py](../../src/db/models.py) for the pattern
- Keep queries in [models.py](../../src/db/models.py) - don't write SQL in routes
- Return dataclasses (`User`, `Conversation`, `Message`) from database methods

### Migration Guidelines

- Create new migration files in `migrations/` directory (numbered sequentially)
- Use `IF NOT EXISTS` / `IF EXISTS` for safe rollbacks
- Follow pattern from existing migrations (see [0005_add_cost_tracking.py](../../migrations/0005_add_cost_tracking.py))
- Test migrations on a copy of production data before deploying

## See Also

- [File Handling](../features/file-handling.md) - File storage and thumbnails
- [Cost Tracking](../features/cost-tracking.md) - Message costs table
- [Search](../features/search.md) - FTS5 search index
- [Logging](../logging.md) - Structured logging with request IDs
