# Rate Limiting

The API implements rate limiting using Flask-Limiter to protect against DoS attacks and runaway clients. Rate limits are applied per-user when authenticated, or per-IP for unauthenticated endpoints.

## Configuration

```bash
# .env
RATE_LIMITING_ENABLED=true                    # Enable/disable (default: enabled)
RATE_LIMIT_STORAGE_URI=memory://              # Storage backend (default: memory://)
RATE_LIMIT_DEFAULT=200 per minute             # Default for all endpoints
RATE_LIMIT_AUTH=10 per minute                 # Authentication (brute force protection)
RATE_LIMIT_CHAT=30 per minute                 # Chat endpoints (expensive LLM calls)
RATE_LIMIT_CONVERSATIONS=60 per minute        # Conversation CRUD
RATE_LIMIT_FILES=120 per minute               # File downloads
```

**Storage backend options:**
- `memory://` - Simple, no external dependencies. Lost on restart. Suitable for single-process deployments.
- `redis://host:port` - Recommended for multi-process/multi-instance deployments. Persistent across restarts.
- `memcached://host:port` - Alternative distributed cache

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
- [config.py](../../src/config.py) - Rate limit configuration
- [app.py](../../src/app.py) - Limiter initialization in app factory
- [routes/](../../src/api/routes/) - Rate limit decorators on endpoints
- [test_rate_limiting.py](../../tests/unit/test_rate_limiting.py) - Unit tests

## See Also

- [API Design](api-design.md) - route organization and validation
- [Error Handling](error-handling.md) - the `RATE_LIMITED` error format
