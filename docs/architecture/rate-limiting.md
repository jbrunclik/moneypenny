# Rate Limiting

The API implements rate limiting using Flask-Limiter to protect against DoS attacks and runaway clients. Rate limits are applied per-user when authenticated, or per-IP for unauthenticated endpoints.

## Configuration

```bash
# .env
RATE_LIMITING_ENABLED=true                    # Enable/disable (default: enabled)
RATE_LIMIT_STORAGE_URI=sqlite://              # Storage backend (default: sqlite://)
RATE_LIMIT_DB_PATH=ratelimits.db              # sqlite:// counter file, relative to the project root
RATE_LIMIT_DEFAULT=200 per minute             # Default for all endpoints
RATE_LIMIT_AUTH=10 per minute                 # Authentication (brute force protection)
RATE_LIMIT_CHAT=30 per minute                 # Chat endpoints (expensive LLM calls)
RATE_LIMIT_CONVERSATIONS=60 per minute        # Conversation CRUD
RATE_LIMIT_FILES=120 per minute               # File downloads
```

**Storage backend options:**
- `sqlite://` (default) - counters shared by every worker process in `RATE_LIMIT_DB_PATH`; survives reloads. See [Shared SQLite storage](#shared-sqlite-storage).
- `memory://` - per worker process (with N workers each limit is effectively xN) and reset on every reload. Tests use it (`tests/conftest.py`) so hits never leak between tests or xdist workers.
- `redis://host:port` / `memcached://host:port` - need a server; the production host has none.

## Shared SQLite storage

`src/utils/rate_limit_storage.py` is a `limits` storage registered under the `sqlite` scheme (importing the module registers it; `init_rate_limiting` passes the file path as the `path` storage option).

- **Own file.** Counters live in `ratelimits.db`, never `chatbot.db`, so a counter write never waits on (or holds) the main database's write lock. The file is created on first use; it holds only short-lived counters, so it needs no backup or migration and can be deleted at any time (limits restart from zero).
- **Atomic across processes.** Each hit is one `INSERT ... ON CONFLICT DO UPDATE ... RETURNING count` statement in autocommit mode: a counter whose window has expired restarts at the hit's cost with a new expiry, otherwise it adds to the count and keeps the window's first expiry (fixed-window semantics, same as `memory://`).
- **WAL, short busy timeout** (1 s): a wedged file fails fast instead of stalling requests.
- **Lazy cleanup.** Expired rows are ignored on read and swept by a `DELETE` at most once a minute per process.
- **Fork-safe.** The connection opens lazily and is reopened if the process id changed, so a pre-fork connection is never shared.
- **Strategy.** Only the fixed-window strategy (the one the app configures) is supported; moving and sliding windows would need the `MovingWindowSupport`/`SlidingWindowCounterSupport` extras.

**Fail open.** The limiter runs with `in_memory_fallback_enabled=True` and `swallow_errors=True`. When the storage raises (it logs `Rate-limit storage error` with the cause), Flask-Limiter logs `Rate limit storage unreachable - falling back to in-memory storage`, counts in that worker's memory, and re-checks the storage with backoff until it answers again; any error past that is swallowed and the request goes through. A broken rate-limit file never fails a request.

## Endpoint Categories

Different rate limits apply to different endpoint categories:

| Category | Limit | Endpoints |
|----------|-------|-----------|
| Auth | 10/min | `/auth/google` |
| Chat | 30/min | `chat/batch`, `chat/stream`, `chat/interject`, stream resume (all under `/api/conversations/<id>/`) |
| Conversations | 60/min | Conversation CRUD, messages, sync |
| Files | 120/min | Thumbnails, file downloads |
| Default | 200/min | All other authenticated endpoints |
| Exempt | No limit | `/api/health`, `/api/ready`, `/api/version` |

## Rate Limit Key Strategy

- **Authenticated requests**: Rate limited by user ID (`user:{user_id}`)
- **Unauthenticated requests**: Rate limited by IP address (`ip:{ip_address}`)

This ensures one user can't affect others, while still protecting against unauthenticated abuse.

## Response Headers

When rate limiting is enabled, responses include standard rate limit headers:
- `X-RateLimit-Limit`: Maximum requests allowed in the window
- `X-RateLimit-Remaining`: Requests remaining in current window
- `X-RateLimit-Reset`: Unix timestamp when the window resets

## Rate Limit Exceeded Response

When rate limit is exceeded, the API returns HTTP 429 with our standard error format:

```json
{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Too many requests. Please slow down.",
    "retryable": true,
    "details": {"retry_after": 60}
  }
}
```

The `Retry-After` header is also included when available.

## Adding Rate Limits to New Endpoints

Use the appropriate rate limit decorator based on the endpoint category:

```python
from src.api.rate_limiting import (
    rate_limit_auth,
    rate_limit_chat,
    rate_limit_conversations,
    rate_limit_files,
    exempt_from_rate_limit,
)

# For authentication endpoints (strictest)
@auth.route("/new-auth", methods=["POST"])
@rate_limit_auth
def new_auth_endpoint():
    ...

# For chat/LLM endpoints (moderate)
@api.route("/chat/new", methods=["POST"])
@rate_limit_chat
@require_auth
def new_chat_endpoint():
    ...

# For conversation operations (generous)
@api.route("/conversations/new", methods=["GET"])
@rate_limit_conversations
@require_auth
def new_conversations_endpoint():
    ...

# For file downloads (generous but capped)
@api.route("/files/new", methods=["GET"])
@rate_limit_files
@require_auth
def new_files_endpoint():
    ...

# For health checks (exempt from rate limiting)
@api.route("/status", methods=["GET"])
@exempt_from_rate_limit
def status_endpoint():
    ...
```

## Production Considerations

**Tuning limits:**
- Monitor 429 responses in logs to identify if limits are too strict
- Adjust per-endpoint limits based on actual usage patterns
- Consider increasing chat limits if users report throttling during normal use

## Key Files

- [rate_limiting.py](../../src/api/rate_limiting.py) - Limiter initialization and decorators
- [rate_limit_storage.py](../../src/utils/rate_limit_storage.py) - `sqlite://` storage shared across workers
- [config.py](../../src/config.py) - Rate limit configuration
- [app.py](../../src/app.py) - Limiter initialization in app factory
- [routes/](../../src/api/routes/) - Rate limit decorators on endpoints
- [test_rate_limiting.py](../../tests/unit/test_rate_limiting.py) - Unit tests, including enforcement and fail-open through the SQLite storage
- [test_rate_limit_storage.py](../../tests/unit/test_rate_limit_storage.py) - SQLite storage: counting, expiry, cross-process sharing

## See Also

- [API Design](api-design.md) - route organization and validation
- [Error Handling](error-handling.md) - the `RATE_LIMITED` error format
