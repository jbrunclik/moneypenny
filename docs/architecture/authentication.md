# Authentication

The app uses Google Identity Services (GIS) for client-side authentication with JWT tokens for API authorization.

## Authentication Flow

### Development Mode

```bash
FLASK_ENV=development
```

In development mode:
- All auth is skipped
- Requests are authenticated as "local@localhost" user
- No Google Sign-In required

### Production Mode

1. **Frontend loads GIS library** and renders "Sign in with Google" button
2. **User clicks** → Google popup opens
3. **Google returns ID token** to frontend
4. **Frontend sends token** to `POST /auth/google`
5. **Backend validates token** via Google's tokeninfo endpoint
6. **Backend checks email whitelist**, returns JWT
7. **Frontend stores JWT** for subsequent API calls
8. **Frontend schedules automatic token refresh** before expiration

## JWT Token Handling

### Token Lifecycle

- **Expiration**: 7 days (`JWT_EXPIRATION_SECONDS = SECONDS_PER_WEEK`)
- **Auto-refresh**: Frontend refreshes when less than 2 days remain
- **Refresh window**: 48-hour window ensures users can skip a day without getting logged out
- **Page load**: `checkAuth()` validates token and schedules refresh
- **Refresh endpoint**: `POST /auth/refresh`

### Token Security

- In production, `JWT_SECRET_KEY` must be at least 32 characters
- Config validation fails startup if secret is too short
- Tokens are signed with HS256 algorithm
- Tokens include user ID and expiration timestamp

### Error Codes

The backend returns distinct error codes for authentication failures:

| Code | Status | Description |
|------|--------|-------------|
| `AUTH_REQUIRED` | 401 | No token provided |
| `AUTH_EXPIRED` | 401 | Token has expired → prompts user to re-login |
| `AUTH_INVALID` | 401 | Token is malformed or signature is invalid |
| `AUTH_FORBIDDEN` | 403 | Valid auth but not authorized for resource |

### Frontend Error Handling

The `ApiError` class provides semantic properties for authentication errors:

```typescript
if (error instanceof ApiError) {
  if (error.isTokenExpired) {
    // Show "Your session has expired. Please sign in again."
    // Redirect to login
  } else if (error.isAuthError) {
    // Handle other auth errors (invalid, missing, etc.)
  }
}
```

**Properties:**
- `ApiError.isTokenExpired`: True when backend returns `AUTH_EXPIRED`
- `ApiError.isAuthError`: True for any 401 or auth-related error code

## @require_auth Decorator

The `@require_auth` decorator injects the authenticated `User` as the first argument to route handlers. This eliminates the need for `get_current_user()` calls and makes the contract explicit in the function signature.

### Usage Pattern

```python
@api.route("/endpoint", methods=["GET"])
@require_auth
def my_endpoint(user: User) -> dict:
    # user is guaranteed to be a valid User - decorator handles auth errors
    return {"user_id": user.id}
```

### With @validate_request

When combined with `@validate_request`, user comes first, then validated data:

```python
@api.route("/endpoint", methods=["POST"])
@require_auth
@validate_request(MySchema)
def my_endpoint(user: User, data: MySchema) -> dict:
    # user from @require_auth, data from @validate_request
    return {"user_id": user.id, "value": data.value}
```

**Decorator order matters** (applied bottom-to-top):
1. `@validate_request` validates JSON, appends data after user
2. `@require_auth` checks auth, injects user
3. Auth errors return before validation is attempted

## Email Whitelist

Access is controlled via email whitelist in configuration:

```bash
# .env
EMAIL_WHITELIST=user1@example.com,user2@example.com
```

- Only whitelisted emails can authenticate
- Checked after Google token validation
- Returns `AUTH_FORBIDDEN` for non-whitelisted users

## Configuration

```bash
# .env
GOOGLE_CLIENT_ID=your-google-client-id           # For Sign-In (different from Calendar client)
JWT_SECRET_KEY=your-secret-key-min-32-chars       # JWT signing key (min 32 chars in prod)
JWT_EXPIRATION_SECONDS=604800                     # 7 days (default)
EMAIL_WHITELIST=user1@example.com,user2@example.com
FLASK_ENV=development                             # Skip auth in dev mode
```

## Key Files

### Backend

- [jwt_auth.py](../../src/auth/jwt_auth.py) - Token creation, validation, `decode_token_with_status()`, `@require_auth` decorator
- [google_auth.py](../../src/auth/google_auth.py) - Google token verification, email whitelist checking
- [routes/auth.py](../../src/api/routes/auth.py) - `/auth/google`, `/auth/refresh` endpoints
- [config.py](../../src/config.py) - Auth configuration constants

### Frontend

- [google.ts](../../web/src/auth/google.ts) - `scheduleTokenRefresh()`, `checkAuth()`, `performTokenRefresh()`
- [client.ts](../../web/src/api/client.ts) - `ApiError` with `isTokenExpired` and `isAuthError` properties
- [init.ts](../../web/src/core/init.ts) - Auth initialization, login/logout handlers

## Testing

- **Backend unit tests**: [test_jwt_auth.py](../../tests/unit/test_jwt_auth.py) - JWT token handling
- **Backend unit tests**: [test_google_auth.py](../../tests/unit/test_google_auth.py) - Google token verification
- **Backend integration tests**: [test_routes_auth.py](../../tests/integration/test_routes_auth.py) - Auth endpoints
- **E2E tests**: [auth.spec.ts](../../web/tests/e2e/auth.spec.ts) - Authentication flow

## See Also

- [Rate Limiting](api-design.md#rate-limiting) - Per-user rate limiting using authenticated user ID
- [Integrations](../features/integrations.md) - OAuth flows for Todoist and Google Calendar (separate from Sign-In)
- [Error Handling](api-design.md#error-handling) - Auth error responses
