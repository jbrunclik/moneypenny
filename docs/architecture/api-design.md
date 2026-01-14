# API Design

The API follows RESTful principles with OpenAPI documentation, comprehensive validation, rate limiting, and standardized error handling.

## OpenAPI Documentation

The API is documented using [APIFlask](https://apiflask.com/) which automatically generates an OpenAPI 3.0 specification.

### Available Documentation

- **OpenAPI Spec**: [/api/openapi.json](http://localhost:8000/api/openapi.json) - JSON specification
- **Swagger UI**: [/api/docs](http://localhost:8000/api/docs) - Interactive API documentation
- **Static Spec**: [static/openapi.json](../../static/openapi.json) - Committed spec file for TypeScript generation

### TypeScript Type Generation

Types are auto-generated from the OpenAPI spec using [openapi-typescript](https://www.npmjs.com/package/openapi-typescript):

```bash
# Generate types from the committed spec
make types
```

This creates `web/src/types/generated-api.ts`. The manual types in [api.ts](../../web/src/types/api.ts) re-export these and add frontend-only types (e.g., `StreamEvent`, `ThinkingState`).

### Adding Response Schemas

Response schemas are defined in [schemas.py](../../src/api/schemas.py) alongside request schemas. Use `@api.output()` for success responses and `@api.doc(responses=[...])` to document error status codes:

```python
from apiflask import APIBlueprint
from src.api.schemas import MyResponse
from src.api.errors import raise_not_found_error

api = APIBlueprint("api", __name__, url_prefix="/api")

@api.route("/endpoint/<item_id>", methods=["GET"])
@api.output(MyResponse)  # 200 response - generates OpenAPI schema
@api.doc(responses=[404])  # Document possible error codes
@require_auth
def my_endpoint(user: User, item_id: str) -> tuple[dict, int]:
    item = db.get_item(item_id)
    if not item:
        raise_not_found_error("Item")  # Raises APIError, handled by error processor
    return {"id": item.id, "name": item.name}, 200
```

**Note**: Error responses use `raise_xxx_error()` functions from [errors.py](../../src/api/errors.py), which raise `APIError` exceptions. These are handled by the custom error processor in [app.py](../../src/app.py) and return our standardized error format.

### Response Validation

APIFlask validates responses against schemas in development mode:
- Enable via `app.config["VALIDATION_MODE"] = "response"`
- Automatically enabled in tests via the `openapi_client` fixture
- Disabled in production for performance

### Regenerating the Spec

To update the static OpenAPI spec after adding new endpoints or schemas:

```bash
# Export OpenAPI spec to static/openapi.json
make openapi

# Generate TypeScript types from the spec
make types
```

This workflow should be run whenever you modify:
- Response schemas in `src/api/schemas.py`
- Endpoint definitions or `@api.output()` decorators in `src/api/routes/`

### Key Files

- [app.py](../../src/app.py) - APIFlask configuration
- [schemas.py](../../src/api/schemas.py) - Request and response Pydantic schemas
- [routes/](../../src/api/routes/) - API endpoints organized by feature (see Route Organization below)
- [static/openapi.json](../../static/openapi.json) - Generated OpenAPI specification
- [web/src/types/generated-api.ts](../../web/src/types/generated-api.ts) - Auto-generated TypeScript types
- [web/src/types/api.ts](../../web/src/types/api.ts) - Frontend type definitions
- [tests/integration/test_openapi.py](../../tests/integration/test_openapi.py) - OpenAPI spec tests

### Route Organization

Routes are organized into focused modules by feature area (43 total endpoints across 11 modules):

**Auth-related routes** (`/auth` prefix):
- [routes/auth.py](../../src/api/routes/auth.py) - Google authentication (4 routes)
- [routes/todoist.py](../../src/api/routes/todoist.py) - Todoist integration (4 routes)
- [routes/calendar.py](../../src/api/routes/calendar.py) - Google Calendar integration (7 routes)

**API routes** (`/api` prefix):
- [routes/system.py](../../src/api/routes/system.py) - Models, config, version, health (5 routes)
- [routes/memory.py](../../src/api/routes/memory.py) - User memory management (2 routes)
- [routes/settings.py](../../src/api/routes/settings.py) - User settings (2 routes)
- [routes/conversations.py](../../src/api/routes/conversations.py) - Conversation CRUD (9 routes)
- [routes/planner.py](../../src/api/routes/planner.py) - Planner dashboard (4 routes)
- [routes/chat.py](../../src/api/routes/chat.py) - Chat endpoints (2 routes: batch and streaming)
- [routes/files.py](../../src/api/routes/files.py) - File serving (2 routes)
- [routes/costs.py](../../src/api/routes/costs.py) - Cost tracking (4 routes)

**Helper modules**:
- [helpers/validation.py](../../src/api/helpers/validation.py) - Common validation patterns
- [helpers/chat_streaming.py](../../src/api/helpers/chat_streaming.py) - Chat streaming utilities

All routes are registered via `register_blueprints()` in [routes/__init__.py](../../src/api/routes/__init__.py).

---

## Rate Limiting

The API implements rate limiting using Flask-Limiter to protect against DoS attacks and runaway clients. Rate limits are applied per-user when authenticated, or per-IP for unauthenticated endpoints.

### Configuration

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

### Endpoint Categories

Different rate limits apply to different endpoint categories:

| Category | Limit | Endpoints |
|----------|-------|-----------|
| Auth | 10/min | `/auth/google` |
| Chat | 30/min | `/chat/batch`, `/chat/stream` |
| Conversations | 60/min | Conversation CRUD, messages, sync |
| Files | 120/min | Thumbnails, file downloads |
| Default | 200/min | All other authenticated endpoints |
| Exempt | No limit | `/api/health`, `/api/ready`, `/api/version` |

### Rate Limit Key Strategy

- **Authenticated requests**: Rate limited by user ID (`user:{user_id}`)
- **Unauthenticated requests**: Rate limited by IP address (`ip:{ip_address}`)

This ensures one user can't affect others, while still protecting against unauthenticated abuse.

### Response Headers

When rate limiting is enabled, responses include standard rate limit headers:
- `X-RateLimit-Limit`: Maximum requests allowed in the window
- `X-RateLimit-Remaining`: Requests remaining in current window
- `X-RateLimit-Reset`: Unix timestamp when the window resets

### Rate Limit Exceeded Response

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

### Adding Rate Limits to New Endpoints

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

### Production Considerations

**Tuning limits:**
- Monitor 429 responses in logs to identify if limits are too strict
- Adjust per-endpoint limits based on actual usage patterns
- Consider increasing chat limits if users report throttling during normal use

### Key Files

- [rate_limiting.py](../../src/api/rate_limiting.py) - Limiter initialization and decorators
- [config.py](../../src/config.py) - Rate limit configuration
- [app.py](../../src/app.py) - Limiter initialization in app factory
- [routes/](../../src/api/routes/) - Rate limit decorators on endpoints
- [test_rate_limiting.py](../../tests/unit/test_rate_limiting.py) - Unit tests

---

## Request Validation

The API uses Pydantic v2 for request validation. All validation follows a consistent pattern using the `@validate_request` decorator.

### Schema Location

Request schemas are defined in [schemas.py](../../src/api/schemas.py):
- `GoogleAuthRequest` - POST /auth/google
- `CreateConversationRequest` - POST /api/conversations
- `UpdateConversationRequest` - PATCH /api/conversations/<id>
- `ChatRequest` - POST /chat/batch and /chat/stream
- `FileAttachment` - Nested schema for file uploads

### Adding Validation to a New Endpoint

**1. Define the schema in `src/api/schemas.py`:**

```python
from pydantic import BaseModel, Field, field_validator

class MyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    count: int = Field(default=10, ge=1, le=100)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if v.startswith("_"):
            raise ValueError("Name cannot start with underscore")
        return v
```

**2. Apply the decorator to your route:**

```python
from src.api.schemas import MyRequest
from src.api.validation import validate_request
from src.db.models import User

@api.route("/endpoint", methods=["POST"])
@require_auth
@validate_request(MyRequest)
def my_endpoint(user: User, data: MyRequest) -> tuple[dict, int]:
    # user is injected by @require_auth
    # data is the validated Pydantic model from @validate_request
    name = data.name
    count = data.count
    ...
```

### Decorator Order

Decorators are applied bottom-to-top, so the order matters:

```python
@api.route("/endpoint", methods=["POST"])
@require_auth           # 2nd: checks auth, injects user
@validate_request(...)  # 1st: validates JSON, appends data after user
def handler(user: User, data: MySchema):
    ...
```

This means auth errors return before validation is attempted (correct behavior - don't validate requests from unauthenticated users). The `user` argument comes first (from `@require_auth`), followed by `data` (from `@validate_request`).

### Two-Phase File Validation

File uploads use two-phase validation:

1. **Structure (Pydantic)**: Field presence, MIME type in allowed list, file count limit
2. **Content (validate_files)**: Base64 decoding, file size limits, magic bytes verification

This allows fast-fail on structure before expensive base64 operations.

### Magic Bytes Validation

After base64 decoding and size validation, files are verified using `python-magic` (libmagic) to ensure file content matches the claimed MIME type. This prevents MIME type spoofing attacks where malicious files are disguised as allowed types.

**How it works:**
1. Binary file formats (images, PDF) are validated by comparing magic-detected MIME type against allowed aliases
2. Text-based formats (text/plain, markdown, csv, json) skip magic validation since libmagic detection is unreliable for these
3. If magic detection fails (library error), validation passes to avoid blocking legitimate files

**MIME type aliases:**
The `MIME_TYPE_ALIASES` dict in [files.py](../../src/utils/files.py) maps claimed MIME types to acceptable magic-detected types. This handles cases where libmagic detects a slightly different type (e.g., `text/x-python` for Python source vs `text/plain`).

**System dependency:**
Requires `libmagic` system library:
- macOS: `brew install libmagic`
- Ubuntu/Debian: `apt-get install libmagic1`
- Alpine: `apk add libmagic`

**Key files:**
- [files.py](../../src/utils/files.py) - `verify_file_type_by_magic()`, `MIME_TYPE_ALIASES`, `TEXT_BASED_MIME_TYPES`
- [test_files.py](../../tests/unit/test_files.py) - Unit tests for magic validation

### Error Response Format

Validation errors return the standard error format:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable error message",
    "retryable": false,
    "details": {"field": "field_name"}
  }
}
```

### Key Files

- [schemas.py](../../src/api/schemas.py) - Pydantic schema definitions
- [validation.py](../../src/api/validation.py) - `@validate_request` decorator and error conversion
- [errors.py](../../src/api/errors.py) - Error response helpers
- [files.py](../../src/utils/files.py) - Content validation for files

---

## Error Handling

The application implements comprehensive error handling across both backend and frontend to ensure graceful failure recovery and a good user experience.

### Backend Error Responses

All API errors return a standardized JSON format from [errors.py](../../src/api/errors.py):

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable message",
    "retryable": false,
    "details": { "field": "email" }
  }
}
```

**Error codes** (from `ErrorCode` enum):
- `AUTH_REQUIRED`, `AUTH_INVALID`, `AUTH_EXPIRED`, `AUTH_FORBIDDEN` - Authentication errors
- `VALIDATION_ERROR`, `MISSING_FIELD`, `INVALID_FORMAT` - Input validation errors
- `NOT_FOUND`, `CONFLICT` - Resource errors
- `SERVER_ERROR`, `TIMEOUT`, `SERVICE_UNAVAILABLE`, `RATE_LIMITED` - Server errors (retryable)
- `EXTERNAL_SERVICE_ERROR`, `LLM_ERROR`, `TOOL_ERROR` - External service errors

**Raising errors** - Use `raise_xxx_error()` functions which raise `APIError` exceptions:

```python
from src.api.errors import raise_validation_error, raise_not_found_error, raise_server_error

# Raises APIError, handled by custom error processor in app.py
raise_validation_error("Invalid email", field="email")  # 400
raise_not_found_error("Conversation")  # 404
raise_server_error()  # 500
```

**How error handling works:**
1. Route code calls `raise_xxx_error()` which raises an `APIError` exception
2. `APIError` extends APIFlask's `HTTPError` with our custom error structure in `extra_data`
3. The custom `error_processor` in [app.py](../../src/app.py) catches all `HTTPError` exceptions
4. For `APIError`, it returns the `extra_data` which contains our standardized error format
5. For standard `HTTPError` (e.g., Flask's 404), it wraps the message in our format

**Note:** The `@validate_request` decorator uses `raise_validation_error()` and `raise_invalid_json_error()` internally, so validation errors are automatically formatted correctly.

### Frontend Error Handling

#### Toast Notifications

Use [Toast.ts](../../web/src/components/Toast.ts) for transient error messages:

```typescript
import { toast } from './components/Toast';

toast.error('Failed to save.');
toast.error('Connection lost.', {
  action: { label: 'Retry', onClick: () => retry() }
});
toast.warning('File too large.');
toast.success('Saved!');
toast.info('Processing...');
```

- Auto-dismiss after 5 seconds by default
- Persistent if action button is provided
- Top-center positioning (doesn't interfere with input)

#### Modal Dialogs

Use [Modal.ts](../../web/src/components/Modal.ts) instead of native `alert()`, `confirm()`, `prompt()`:

```typescript
import { showAlert, showConfirm, showPrompt } from './components/Modal';

await showAlert({ title: 'Error', message: 'Something went wrong.' });

const confirmed = await showConfirm({
  title: 'Delete',
  message: 'Are you sure?',
  confirmLabel: 'Delete',
  danger: true
});

const value = await showPrompt({
  title: 'Rename',
  message: 'Enter new name:',
  defaultValue: 'Untitled'
});
```

#### API Client Error Handling

The [api/client.ts](../../web/src/api/client.ts) provides:

1. **Retry logic with exponential backoff** - Only for GET requests (idempotent)
2. **Request timeouts** - 30s default, 5 minutes for chat
3. **Streaming per-read timeout** - 60s timeout per read (backend sends keepalives every 15s)
4. **Extended ApiError class** with semantic properties

```typescript
try {
  await someApiCall();
} catch (error) {
  if (error instanceof ApiError) {
    if (error.isTimeout) {
      toast.error('Request timed out.');
    } else if (error.isNetworkError) {
      toast.error('Network error. Check your connection.');
    } else if (error.retryable) {
      toast.error('Failed.', { action: { label: 'Retry', onClick: retry } });
    } else {
      toast.error(error.message);
    }
  }
}
```

**IMPORTANT - Retry Safety:**
- ✅ Safe to retry: GET requests (idempotent)
- ⚠️ Conditionally safe: PATCH, DELETE (idempotent operations)
- ❌ NOT safe to retry: POST (creates resources, could duplicate)

#### Draft-Based Message Recovery

When a chat message fails to send (network error, timeout, server error), the user's message and any attached files are preserved in a draft so they can retry.

**How it works:**
1. **Error occurs**: When `sendMessage()` fails (either batch or streaming mode), the catch block saves the message and files to draft state
2. **Draft saved**: `store.setDraft(message, files)` persists to Zustand store, which syncs to localStorage
3. **Toast with retry**: User sees error toast with "Retry" button
4. **Retry clicked**: `retryFromDraft()` restores message to input field, clears draft, and re-sends
5. **Success**: Draft is automatically cleared when message sends successfully

**Draft state in store:**
```typescript
// store.ts
draftMessage: string | null;
draftFiles: FileAttachment[];
setDraft: (message: string | null, files: FileAttachment[]) => void;
```

**Key functions in messaging.ts:**
- `sendMessage()` - Outer catch block saves draft and shows toast
- `sendStreamingMessage()` - Converts error events to ApiError, re-throws
- `sendBatchMessage()` - Re-throws errors to outer catch
- `retryFromDraft()` - Restores draft to input and re-sends

**Testing:**
E2E tests for retry functionality are in [chat.spec.ts](../../web/tests/e2e/chat.spec.ts) under "Chat - Message Retry" describe block.

### Error Handling Guidelines

**Backend:**
1. Never expose internal error details to users - log them, return generic message
2. Use `@validate_request` decorator for JSON parsing and validation (handles malformed JSON gracefully)
3. Wrap external API calls (Gemini, Google Auth) in try/except
4. Use `raise_xxx_error()` functions from `errors.py` to raise errors (not return)
5. Log errors with `exc_info=True` before raising error

**Frontend:**
1. Every async operation should have error handling
2. Use toast for transient errors, modal for confirmations
3. Preserve user input on send failures (draft system in store)
4. Show retry buttons for retryable errors
5. Don't hide partial content on streaming errors

### Key Files

- [errors.py](../../src/api/errors.py) - `APIError` class and `raise_xxx_error()` functions
- [app.py](../../src/app.py) - Custom error processor that formats `APIError` responses
- [Toast.ts](../../web/src/components/Toast.ts) - Toast notification component
- [Modal.ts](../../web/src/components/Modal.ts) - Modal dialog component
- [api/client.ts](../../web/src/api/client.ts) - API client with retry/timeout
- [store.ts](../../web/src/state/store.ts) - Notification state, draft persistence

## See Also

- [Authentication](authentication.md) - Auth error codes and handling
- [File Handling](../features/file-handling.md) - File validation
- [Testing Guide](../testing.md) - Testing error scenarios
