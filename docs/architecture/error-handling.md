# Error Handling

The application implements comprehensive error handling across both backend and frontend to ensure graceful failure recovery and a good user experience.

## Backend Error Responses

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
- `NOT_FOUND`, `GONE` (expired per retention policy), `CONFLICT`, `PAYLOAD_TOO_LARGE` - Resource errors
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

## Frontend Error Handling

### Toast Notifications

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

### Modal Dialogs

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

### API Client Error Handling

The HTTP layer ([api/http.ts](../../web/src/api/http.ts), used by [api/client.ts](../../web/src/api/client.ts); SSE reading in [api/sse.ts](../../web/src/api/sse.ts)) provides:

1. **Retry logic with exponential backoff** - opt-in per call (`requestWithRetry`), used for idempotent reads
2. **Request timeouts** - `API_DEFAULT_TIMEOUT_MS` (30s), `API_CHAT_TIMEOUT_MS` (5 min) for chat, and a 30s connect timeout on the streaming POST (`API_CHAT_CONNECT_TIMEOUT_MS`)
3. **Streaming per-read timeout** - `API_STREAM_READ_TIMEOUT_MS` (60s) per read; the backend sends keepalives every `SSE_KEEPALIVE_INTERVAL` (15s)
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

### Failed Chat Sends

A chat send that fails is **not** saved to a draft (the old `setDraft` / `retryFromDraft`
flow is gone). The user message stays in place as a bubble backed by the persisted send
outbox:

1. `dispatchSend()` in [messaging.ts](../../web/src/core/messaging.ts) runs the send
   through `sendStreamingMessage()` ([stream-send.ts](../../web/src/core/stream-send.ts))
   or `sendBatchMessage()` ([batch-send.ts](../../web/src/core/batch-send.ts)); both
   re-throw failures to it.
2. `handleSendFailure()` classifies the error: a **409** means an earlier attempt already
   landed (`client_message_id` dedupe) - confirm delivery and refetch; an abort marks the
   message failed; a transient network error or connect timeout gets **one silent
   auto-retry** after `SEND_AUTO_RETRY_DELAY_MS`; anything else calls `markSendFailed()`
   ([send-delivery.ts](../../web/src/core/send-delivery.ts)) and toasts.
3. The failed bubble shows inline **Retry / Discard**; `retryFailedMessage()` in
   [rerun.ts](../../web/src/core/rerun.ts) re-dispatches the outbox entry (idempotent via
   the same `client_message_id`).
4. A failure *after* delivery (the stream died mid-reply) is not a send failure:
   `markSendFailed` no-ops once delivery was confirmed, and stream resume / poll recovery
   takes over.

Details: [Reliable Sends](../features/chat-and-streaming.md#reliable-sends-outbox) and
[Frontend Send, Re-run and Retry](../features/chat-and-streaming.md#frontend-send-re-run-and-retry).

**Testing:** "Chat - Message Retry" in
[message-actions.spec.ts](../../web/tests/e2e/chat/message-actions.spec.ts) and
[send-failure.spec.ts](../../web/tests/e2e/chat/send-failure.spec.ts).

## Error Handling Guidelines

**Backend:**
1. Never expose internal error details to users - log them, return generic message
2. Use `@validate_request` decorator for JSON parsing and validation (handles malformed JSON gracefully)
3. Wrap external API calls (Gemini, Google Auth) in try/except
4. Use `raise_xxx_error()` functions from `errors.py` to raise errors (not return)
5. Log errors with `exc_info=True` before raising error

**Frontend:**
1. Every async operation should have error handling
2. Use toast for transient errors, modal for confirmations
3. Preserve user input on send failures (the failed message stays as a bubble with Retry / Discard)
4. Show retry buttons for retryable errors
5. Don't hide partial content on streaming errors

## Key Files

- [errors.py](../../src/api/errors.py) - `APIError` class and `raise_xxx_error()` functions
- [app.py](../../src/app.py) - Custom error processor that formats `APIError` responses
- [Toast.ts](../../web/src/components/Toast.ts) - Toast notification component
- [Modal.ts](../../web/src/components/Modal.ts) - Modal dialog component
- [api/http.ts](../../web/src/api/http.ts) - `request`, `requestWithRetry`, `ApiError`, timeouts
- [api/client.ts](../../web/src/api/client.ts) - API methods
- [messaging.ts](../../web/src/core/messaging.ts), [send-delivery.ts](../../web/src/core/send-delivery.ts), [outbox.ts](../../web/src/core/outbox.ts) - send failure handling

## See Also

- [API Design](api-design.md) - schemas, validation, route organization
- [Rate Limiting](rate-limiting.md) - the `RATE_LIMITED` response
- [Authentication](authentication.md) - Auth error codes and handling
- [Chat and Streaming](../features/chat-and-streaming.md) - stream errors, resume, outbox
