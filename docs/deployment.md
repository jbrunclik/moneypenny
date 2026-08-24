# Production Operations

Scheduled maintenance jobs, reverse proxy configuration, and log management
for a systemd-based deployment. See the README's Deployment section for the
initial install and zero-downtime update flow.

## .env Changes Require a Full Restart (Not Reload)

The systemd unit loads `.env` via `EnvironmentFile=`, which is read only at
service **start**. `systemctl --user reload` (what `make update` uses) sends
HUP - gunicorn re-forks workers but the master's environment stays frozen,
and `load_dotenv()` does not override variables systemd already set. So
`.env` edits silently do nothing until:

```bash
systemctl --user restart ai-chatbot
```

(Aug 2026 incident: ALLOWED_FILE_TYPES additions were invisible through
several deploys; uploads kept failing with the stale allow-list until a
restart. Verify what the live process actually sees with:
`cat /proc/$(systemctl --user show ai-chatbot -p MainPID --value)/environ | tr '\0' '\n' | grep VAR_NAME`.)

## Database Vacuum

A weekly systemd timer is automatically configured to run VACUUM on both SQLite databases (main database and blob storage). This reclaims disk space from deleted records and optimizes database performance.

```bash
# Check timer status
systemctl --user list-timers

# View vacuum logs
journalctl --user -u ai-chatbot-vacuum

# Run vacuum manually
make vacuum
```

## Currency Rate Updates

A daily systemd timer updates currency exchange rates from a free API (no API key required). Rates are stored in the database and used for cost display without requiring an app restart.

```bash
# View currency update logs
journalctl --user -u ai-chatbot-currency

# Run update manually
make update-currency
```

## Database Backup

A daily systemd timer creates timestamped snapshots of both SQLite databases (main database and blob storage), keeping 7 days of history by default. Backups use SQLite's online backup API for consistent snapshots even while the database is in use.

```bash
# Check timer status
systemctl --user list-timers

# View backup logs
journalctl --user -u ai-chatbot-backup

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
journalctl --user -u ai-chatbot-memory-defrag

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

**Service-level limits** (configured in `ai-chatbot.service`):
- `LogRateLimitIntervalSec=30`: Time window for rate limiting
- `LogRateLimitBurst=10000`: Maximum messages per interval

**Global journald limits** (optional, requires root):

To configure system-wide journald limits, create or edit `/etc/systemd/journald.conf.d/ai-chatbot.conf`:

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
journalctl --user -u ai-chatbot --disk-usage

# Clean old logs (keeps last 7 days)
journalctl --user --vacuum-time=7d
```

**Monitoring log volume:**
When running with `LOG_LEVEL=DEBUG`, monitor disk usage regularly:
```bash
# Watch journal size
watch -n 60 'journalctl --user --disk-usage'
```
