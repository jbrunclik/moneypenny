# Logging

The AI Chatbot uses structured JSON logging across both backend and frontend for easy integration with log aggregation systems like Loki. All logs include contextual information and request IDs for correlation.

## Table of Contents

- [Overview](#overview)
- [Backend Logging](#backend-logging)
- [Frontend Logging](#frontend-logging)
- [Configuration](#configuration)
- [Logging Guidelines](#logging-guidelines)
- [Key Logging Points](#key-logging-points)
- [Key Files](#key-files)

## Overview

### Design Principles

- **Structured logging**: All logs are JSON-formatted with consistent schema
- **Request correlation**: Unique request IDs enable tracing across the stack
- **Contextual information**: Logs include relevant IDs (user, conversation, message)
- **Appropriate levels**: DEBUG for troubleshooting, INFO for operations, ERROR for failures
- **Security**: Sensitive data is never logged (passwords, tokens, PII)

### Log Aggregation

The structured JSON format integrates easily with:
- **Loki**: Grafana's log aggregation system
- **Elasticsearch**: For log indexing and search
- **CloudWatch**: AWS log monitoring
- **DataDog**: Application monitoring and logging

## Backend Logging

### Log Format

All backend logs are JSON-formatted with the following structure:

```json
{
  "timestamp": "2024-01-01 12:00:00",
  "level": "INFO",
  "logger": "src.api.routes",
  "message": "Batch chat request",
  "request_id": "abc-123-def",
  "user_id": "user-123",
  "conversation_id": "conv-456"
}
```

### Request IDs

Every request automatically gets a unique request ID:

- Generated as UUID if not provided in `X-Request-ID` header
- Included in all log entries for that request
- Enables correlation of logs across the request lifecycle
- Tracked in `g.request_id` Flask global

### Logger Creation

Use the centralized logger factory:

```python
from src.utils.logging import get_logger

logger = get_logger(__name__)

def my_function(user_id: str):
    logger.info("Function called", extra={"user_id": user_id})
```

### Log Levels

**DEBUG** - Detailed information for troubleshooting:
```python
logger.debug("Function entry", extra={
    "user_id": user_id,
    "params": params
})
```

**INFO** - Important operations that happen per-request:
```python
logger.info("Conversation created", extra={
    "user_id": user_id,
    "conversation_id": conv_id
})
```

**WARNING** - Unusual but recoverable situations:
```python
logger.warning("Validation failed", extra={
    "user_id": user_id,
    "field": "email",
    "reason": "invalid format"
})
```

**ERROR** - Failures that need attention:
```python
try:
    perform_operation()
except Exception as e:
    logger.error("Operation failed", extra={
        "user_id": user_id,
        "error": str(e)
    }, exc_info=True)  # ← Include stack trace
    raise
```

### Payload Logging

Use the helper function to log payload snippets:

```python
from src.utils.logging import log_payload_snippet

log_payload_snippet(logger, large_data_dict)
```

This truncates large payloads to prevent log bloat while preserving useful debugging information.

### Example Usage

```python
from src.utils.logging import get_logger, log_payload_snippet

logger = get_logger(__name__)

def process_chat_request(user_id: str, data: dict) -> dict:
    logger.debug("Processing chat request", extra={"user_id": user_id})
    log_payload_snippet(logger, data)

    try:
        result = llm_call(data['message'])
        logger.info("Chat completed", extra={
            "user_id": user_id,
            "tokens": result['usage']['total_tokens']
        })
        return result
    except Exception as e:
        logger.error("Chat failed", extra={
            "user_id": user_id,
            "error": str(e)
        }, exc_info=True)
        raise
```

## Frontend Logging

The frontend uses a structured logging utility similar to the backend, providing consistent logging across the application.

### Log Format

**Development** - Colored console output:
```
[my-module] Function called { userId: 'user-123', data: {...} }
```

**Production** - JSON-formatted output:
```json
{
  "level": "info",
  "module": "my-module",
  "message": "Function called",
  "context": { "userId": "user-123", "data": {...} }
}
```

### Logger Creation

```typescript
import { createLogger } from './utils/logger';

const log = createLogger('my-module');

function myFunction(userId: string, data: any) {
  log.debug('Function called', { userId, data });

  try {
    const result = processData(data);
    log.info('Operation completed', { result });
    return result;
  } catch (error) {
    log.error('Operation failed', { error, userId });
    throw error;
  }
}
```

### Log Levels

**debug** - Detailed information for troubleshooting (dev only by default):
```typescript
log.debug('Retry attempt', { attempt: 3, maxRetries: 5 });
```

**info** - Important operations and state changes:
```typescript
log.info('User authenticated', { userId, method: 'google' });
```

**warn** - Unusual but recoverable situations:
```typescript
log.warn('Cost fetch failed', { conversationId, error });
```

**error** - Failures that affect functionality:
```typescript
log.error('API request failed', { endpoint, error, statusCode });
```

### Runtime Configuration

Override log level at runtime via browser console:

```javascript
// Set log level to debug
window.__LOG_LEVEL__ = 'debug';
```

This is useful for debugging production issues without redeploying.

## Configuration

### Backend Configuration

Set log level via environment variable:

```bash
# .env
LOG_LEVEL=INFO  # Valid levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
```

**Development defaults**:
- `FLASK_ENV=development` → `LOG_LEVEL=DEBUG`
- Shows all logs including debug details

**Production defaults**:
- `FLASK_ENV=production` → `LOG_LEVEL=INFO`
- Shows only info, warning, and error logs

### Frontend Configuration

Set log level in [../../web/src/config.ts](../../web/src/config.ts):

```typescript
export const LOG_LEVEL = import.meta.env.PROD ? 'warn' : 'debug';
```

**Development** (dev server):
- `LOG_LEVEL='debug'`
- All logs shown
- Colored console output

**Production** (built bundle):
- `LOG_LEVEL='warn'`
- Only warnings and errors
- JSON-formatted output

Can be overridden via `window.__LOG_LEVEL__` at runtime.

## Logging Guidelines

### When to Log

**DO log**:
- Request start/completion (INFO)
- Authentication events (INFO)
- Database operations (DEBUG)
- LLM API calls and responses (INFO)
- Tool executions (DEBUG)
- Errors and exceptions (ERROR with `exc_info=True`)
- State transitions (DEBUG)

**DON'T log**:
- Sensitive data (passwords, tokens, API keys)
- Personal information (emails, names, unless necessary)
- Full file contents (use snippets)
- High-frequency events (inner loop iterations)

### Log Level Selection

**DEBUG**:
- Function entry/exit
- Intermediate state values
- Payload snippets
- Loop iterations (use sparingly)

**INFO**:
- Request/response
- Successful operations
- Authentication/authorization
- Resource creation/deletion

**WARNING**:
- Validation failures
- Missing optional data
- Retryable errors
- Deprecated API usage

**ERROR**:
- Exceptions (always with `exc_info=True`)
- Failed operations
- System errors
- External service failures

### Best Practices

**Use structured logging with context**:
```python
# Good - structured with context
logger.info("Chat completed", extra={
    "user_id": user_id,
    "conversation_id": conv_id,
    "tokens": token_count
})

# Bad - unstructured message
logger.info(f"Chat completed for user {user_id}")
```

**Include relevant IDs**:
```python
logger.debug("Function called", extra={
    "user_id": user_id,
    "conversation_id": conv_id,
    "message_id": msg_id
})
```

**Always use exc_info for exceptions**:
```python
try:
    risky_operation()
except Exception as e:
    logger.error("Operation failed", extra={
        "user_id": user_id,
        "error": str(e)
    }, exc_info=True)  # ← Stack trace included
    raise
```

**Truncate large data**:
```python
# Use helper for large payloads
log_payload_snippet(logger, large_dict)

# Or manually truncate
logger.debug("Response", extra={
    "content_length": len(content),
    "content_preview": content[:200]  # First 200 chars
})
```

**Don't spam logs**:
```python
# Bad - logs on every iteration
for item in large_list:
    logger.debug(f"Processing {item}")  # Don't do this!

# Good - log summary
logger.debug(f"Processing {len(large_list)} items")
process_items(large_list)
logger.debug("Processing complete")
```

## Key Logging Points

### Backend

**Routes** ([../../src/api/routes/](../../src/api/routes/)):
- All endpoints log request/response with status codes
- Include request ID, user ID, conversation ID where applicable

**Agent** ([../../src/agent/](../../src/agent/)):
- LLM invocations with token counts ([agent.py](../../src/agent/agent.py))
- Tool calls and results ([graph.py](../../src/agent/graph.py))
- Response extraction and metadata parsing ([content.py](../../src/agent/content.py))

**Tools** ([../../src/agent/tools/](../../src/agent/tools/)):
- Tool execution start/completion
- Tool errors and retries
- External API calls

**Database** ([../../src/db/models/](../../src/db/models/)):
- CRUD operations with record IDs
- Query execution time (slow query warnings)
- State saves and updates

**Auth** ([../../src/auth/jwt_auth.py](../../src/auth/jwt_auth.py), [../../src/auth/google_auth.py](../../src/auth/google_auth.py)):
- Token validation
- User lookups
- Authentication failures

**File Processing** ([../../src/utils/images.py](../../src/utils/images.py)):
- File validation
- Thumbnail generation
- Processing errors

### Frontend

**API Client** ([../../web/src/api/client.ts](../../web/src/api/client.ts)):
- Request/response logging
- Retry attempts
- Timeout events
- Network errors

**State Management** ([../../web/src/state/store.ts](../../web/src/state/store.ts)):
- State transitions
- Action dispatches
- Subscription updates

**Components**:
- User interactions
- Component lifecycle
- Error boundaries

**Auth** ([../../web/src/auth/google.ts](../../web/src/auth/google.ts)):
- Authentication flow
- Token refresh
- Auth errors

## Key Files

**Backend**:
- [../../src/utils/logging.py](../../src/utils/logging.py) - Logger factory, `get_logger()`, `log_payload_snippet()`
- [../../src/config.py](../../src/config.py) - `LOG_LEVEL` configuration
- [../../src/app.py](../../src/app.py) - Logger initialization

**Frontend**:
- [../../web/src/utils/logger.ts](../../web/src/utils/logger.ts) - Logger utility, `createLogger()` factory
- [../../web/src/config.ts](../../web/src/config.ts) - `LOG_LEVEL` configuration

**Configuration**:
- [../../.env.example](../../.env.example) - Environment variable examples

## See Also

- [Error Handling](backend/error-handling.md) - Error handling and logging integration
- [API Documentation](backend/api.md) - API request/response logging
- [Testing](testing.md) - Log output in tests
- [Deployment](deployment/production.md) - Production logging configuration
