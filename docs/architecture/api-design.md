# API Design

The API follows RESTful principles with OpenAPI documentation and Pydantic request validation. Rate limiting and error handling have their own pages: [Rate Limiting](rate-limiting.md), [Error Handling](error-handling.md).

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

Routes are organized into focused modules by feature area and registered via
`register_blueprints()` in [routes/__init__.py](../../src/api/routes/__init__.py). Counts are
approximate - check the module when it matters.

**Auth-related routes** (`/auth` prefix):
- [routes/auth.py](../../src/api/routes/auth.py) - Google authentication (4 routes)
- [routes/todoist.py](../../src/api/routes/todoist.py) - Todoist OAuth (4)
- [routes/calendar.py](../../src/api/routes/calendar.py) - Google Calendar OAuth, calendar selection (7)
- [routes/garmin.py](../../src/api/routes/garmin.py) - Garmin Connect (4)
- [routes/rouvy.py](../../src/api/routes/rouvy.py) - Rouvy (3)

**API routes** (`/api` prefix):
- [routes/system.py](../../src/api/routes/system.py) - Models, config, version, health (5)
- [routes/memory.py](../../src/api/routes/memory.py) - User memory management (5)
- [routes/settings.py](../../src/api/routes/settings.py) - User settings (2)
- [routes/conversations.py](../../src/api/routes/conversations.py) - Conversation CRUD, messages, archive, pins (17)
- [routes/chat.py](../../src/api/routes/chat.py) - batch, stream, interject, stream resume (4) - see [Chat and Streaming](../features/chat-and-streaming.md)
- [routes/files.py](../../src/api/routes/files.py) - File serving, thumbnails (2)
- [routes/costs.py](../../src/api/routes/costs.py) - Cost tracking, compaction status (5)
- [routes/planner.py](../../src/api/routes/planner.py) - Planner dashboard (4)
- [routes/agents.py](../../src/api/routes/agents.py) - Agents, approvals, AI-assist helpers (15)
- [routes/kv_store.py](../../src/api/routes/kv_store.py) - K/V store (`/api/kv`, 6)
- [routes/push.py](../../src/api/routes/push.py) - Web Push (`/api/push`, 4)
- [routes/sports.py](../../src/api/routes/sports.py), [routes/language.py](../../src/api/routes/language.py) - program features, generated by the shared factory in [routes/programs.py](../../src/api/routes/programs.py) (5 each, plus quick actions from [program_quick_actions.py](../../src/api/routes/program_quick_actions.py))

**Helper modules** ([helpers/](../../src/api/helpers/)):
- [validation.py](../../src/api/helpers/validation.py) - Common validation patterns
- [chat_turn.py](../../src/api/helpers/chat_turn.py) - turn setup shared by batch and streaming
- [chat_streaming.py](../../src/api/helpers/chat_streaming.py), [stream_producer.py](../../src/api/helpers/stream_producer.py), [stream_finalize.py](../../src/api/helpers/stream_finalize.py) - streaming consumer / producer / finalize
- [chat_save.py](../../src/api/helpers/chat_save.py) - saving a finished turn
- [stream_resume.py](../../src/api/helpers/stream_resume.py) - stream journal and resume
- [program_context.py](../../src/api/helpers/program_context.py) - sports / language context for a turn

## Request Validation

The API uses Pydantic v2 for request validation. All validation follows a consistent pattern using the `@validate_request` decorator.

### Schema Location

Request schemas are defined in [schemas.py](../../src/api/schemas.py):
- `GoogleAuthRequest` - POST /auth/google
- `CreateConversationRequest` - POST /api/conversations
- `UpdateConversationRequest` - PATCH /api/conversations/<id>
- `ChatRequest` - POST /api/conversations/<id>/chat/batch and .../chat/stream (also `client_message_id`, `rerun_mode`, `client_location`)
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

## See Also

- [Rate Limiting](rate-limiting.md) - per-category limits and decorators
- [Error Handling](error-handling.md) - error format, frontend error UX
- [Authentication](authentication.md) - `@require_auth`, JWT
- [File Handling](../features/file-handling.md) - uploads validated here
