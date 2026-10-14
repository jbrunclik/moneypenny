# Production Operations

Scheduled maintenance jobs, reverse proxy configuration, and log management
for a systemd-based deployment. See the README's Deployment section for the
initial install and zero-downtime update flow.

## Python Interpreter (uv-managed, no apt)

Prod Python is a project-managed standalone CPython installed via
[uv](https://docs.astral.sh/uv/) — no root, no custom apt repos, pinned by
`.python-version` in the repo root:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # one-time, user-local
~/.local/bin/uv python install 3.14
~/.local/bin/uv venv .venv --seed --python 3.14   # --seed keeps pip (Makefile uses it)
.venv/bin/pip install -r requirements.txt
systemctl --user restart moneypenny
```

Upgrading Python later = the same steps with a new version (keep the old
venv as `.venv-<ver>-bak` until the new one proves healthy). The systemd
unit references `.venv/bin/gunicorn`, so no unit changes are needed.
Migrated Aug 24 2026 (3.13.5 system Python → uv CPython 3.14.2, aligning
with `requires-python >= 3.14`).

## .env Changes Require a Full Restart (Not Reload)

The systemd unit loads `.env` via `EnvironmentFile=`, which is read only at
service **start**. `systemctl --user reload` (what `make update` uses) sends
HUP - gunicorn re-forks workers but the master's environment stays frozen,
and `load_dotenv()` does not override variables systemd already set. So
`.env` edits silently do nothing until:

```bash
systemctl --user restart moneypenny
```

(Aug 2026 incident: ALLOWED_FILE_TYPES additions were invisible through
several deploys; uploads kept failing with the stale allow-list until a
restart. Verify what the live process actually sees with:
`cat /proc/$(systemctl --user show moneypenny -p MainPID --value)/environ | tr '\0' '\n' | grep VAR_NAME`.)

## Deploys Delete the Previous Build's Chunks

`make build` empties `static/assets/` (`emptyOutDir`), so a page loaded before
a deploy (an installed PWA resumed from the background, a tab left open) still
references the old hashed chunks, and its first lazy import (PDF viewer,
settings, agent editor) 404s. Vite reports that as a `vite:preloadError` event;
[web/src/core/stale-chunks.ts](../web/src/core/stale-chunks.ts) reloads the page
once (the composer draft is persisted), and a second failure within
`STALE_CHUNK_RELOAD_GUARD_MS` surfaces the error instead of looping. (Oct 14
2026: PDF attachments did nothing on click after the previous evening's deploy.)

## Profiling Worker Memory

Check a worker's memory with `grep ^Pss: /proc/<pid>/smaps_rollup` (PSS counts
pages shared with the master once, unlike RSS). To find what a growing worker
accumulates, trace it with tracemalloc (`src/utils/memory_profile.py`):

1. Set `MEMORY_PROFILE_ENABLED=true` in `.env` and **restart** (see above).
   Each worker traces from its start; expect it to be slower and larger while
   on.
2. Soon after the restart, and again after hours of real use, dump a snapshot
   of the same worker: `kill -USR2 <worker pid>` (a worker, not the master -
   the master ignores the profiler). Snapshots land in `MEMORY_PROFILE_DIR`
   as `<pid>-<timestamp>.tracemalloc`; each dump logs a `Memory snapshot
   written` line with `traced_bytes` and `pss_bytes`.
3. Diff them: `.venv/bin/python scripts/memory_profile_diff.py OLD NEW`
   (`--group-by traceback` shows the call chain).
4. Compare the two log lines first: if `pss_bytes` grew much more than
   `traced_bytes`, the growth is outside the Python allocator (C extensions,
   fragmentation) and the diff will not explain it.
5. Turn the flag off and restart when done.

Snapshots are pickles - loading one runs its code - so the directory is
`0700` and files `0600`. Only diff snapshots this service wrote.

Workers are recycled after `GUNICORN_MAX_REQUESTS` requests, so both
snapshots must come from the same pid - check it is still alive before the
second dump.

## Database Vacuum

A weekly systemd timer is automatically configured to run VACUUM on both SQLite databases (main database and blob storage). This reclaims disk space from deleted records and optimizes database performance.

```bash
# Check timer status
systemctl --user list-timers

# View vacuum logs
journalctl --user -u moneypenny-vacuum

# Run vacuum manually
make vacuum
```

## Currency Rate Updates

A daily systemd timer updates currency exchange rates from a free API (no API key required). Rates are stored in the database and used for cost display without requiring an app restart.

```bash
# View currency update logs
journalctl --user -u moneypenny-currency

# Run update manually
make update-currency
```

## Database Backup

A daily systemd timer creates timestamped snapshots of both SQLite databases (main database and blob storage), keeping 1 day of history by default (today's and yesterday's copy). Older copies live in the production host's daily full-disk images, which pick up each night's consistent copy, so a longer local history only duplicates them. Backups use SQLite's online backup API for consistent snapshots even while the database is in use.

```bash
# Check timer status
systemctl --user list-timers

# View backup logs
journalctl --user -u moneypenny-backup

# Create backup manually
make backup

# List existing backups
make backup-list
```

Backups are stored in `backups/{database_name}/` directories alongside the databases. Each backup file is named with a timestamp: `chatbot-20240101-120000.db`.

## Memory Defragmentation

A nightly systemd timer consolidates and cleans up user memories using an LLM: it merges
related memories, removes duplicates, drops stale entries, and purges soft-deleted memories
whose recovery window has passed.

The job is deliberately conservative. It asks the model for a schema-validated plan rather
than parsing prose, it refuses a plan that would leave the user with *more* memories than it
started with, it skips memories marked protected, and its deletes are soft - so a bad run is
recoverable until the retention window expires.

```bash
# View defrag logs
journalctl --user -u moneypenny-memory-defrag

# Run defragmentation manually
make defrag-memories

# Preview changes without applying (dry run)
make defrag-memories -- --dry-run
```

Only users with `MEMORY_DEFRAG_THRESHOLD` memories or more are processed (default: 30).

## Reverse Proxy (nginx)

**Do not add security headers in nginx that the app already sets.** The Flask
app sends `Permissions-Policy`, CSP, and the other security headers itself
(`src/app.py`). If nginx *also* adds a `Permissions-Policy` header (common in
site hardening templates), browsers receive both and apply the **intersection**
of the policies - a template default of `geolocation=()` silently kills the
app's device-location feature in every browser, with only a console
"permissions policy" violation as the clue. This happened in production
(Aug 2026): the app's `geolocation=(self)` was intersected away by an nginx
`add_header Permissions-Policy "geolocation=(), ..."` line. If a shared
hardening template must stay, carve out this vhost: geolocation and microphone
need `(self)` (device location and voice input).

If running behind nginx, ensure timeouts and compression are configured:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;

    # Standard proxy headers
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # Timeouts - must match or exceed GUNICORN_TIMEOUT
    proxy_connect_timeout 60s;
    proxy_send_timeout 300s;    # Match GUNICORN_TIMEOUT
    proxy_read_timeout 300s;    # Match GUNICORN_TIMEOUT

    # Disable buffering for streaming responses
    proxy_buffering off;

    # Gzip compression (add to http or server block)
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_proxied any;
    gzip_types text/plain text/css text/javascript application/javascript application/json application/xml text/xml;
    gzip_comp_level 6;
}
```

**Note on gzip**: The gzip directives can also be placed in the `http` or `server` block to apply globally. The `gzip_vary on` directive ensures proper caching behavior with CDNs. Compression is skipped for already-compressed formats (images, PDFs) and responses smaller than `gzip_min_length`.

The app uses SSE keepalive heartbeats (configurable via `SSE_KEEPALIVE_INTERVAL`) to prevent proxy timeouts during LLM "thinking" phases. For very long operations, increase both `GUNICORN_TIMEOUT` and nginx timeouts.

## Log Rotation and Disk Space

The systemd service file includes log rate limiting to prevent disk space issues, especially when using `LOG_LEVEL=DEBUG`. The default settings allow ~333 log messages per second.

**Service-level limits** (configured in `moneypenny.service`):
- `LogRateLimitIntervalSec=30`: Time window for rate limiting
- `LogRateLimitBurst=10000`: Maximum messages per interval

**Global journald limits** (optional, requires root):

To configure system-wide journald limits, create or edit `/etc/systemd/journald.conf.d/moneypenny.conf`:

```ini
[Journal]
# Maximum disk space for journal (default: 10% of filesystem)
SystemMaxUse=1G

# Maximum disk space for persistent journal
SystemKeepFree=500M

# Maximum age of journal entries (older entries are deleted)
MaxRetentionSec=7day

# Maximum number of journal files to keep
MaxFiles=10
```

After modifying journald configuration:
```bash
sudo systemctl restart systemd-journald
```

**Viewing log sizes:**
```bash
# Check journal disk usage
journalctl --user --disk-usage

# Check service-specific log size
journalctl --user -u moneypenny --disk-usage

# Clean old logs (keeps last 7 days)
journalctl --user --vacuum-time=7d
```

**Monitoring log volume:**
When running with `LOG_LEVEL=DEBUG`, monitor disk usage regularly:
```bash
# Watch journal size
watch -n 60 'journalctl --user --disk-usage'
```
