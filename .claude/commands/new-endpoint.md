---
description: Add an API endpoint end to end - schema, route, OpenAPI, TS client, tests
---

Add an API endpoint: $ARGUMENTS

The backend conventions are in `.claude/rules/api.md`; the layering and error
rules (B1, B3-B5) in `docs/conventions.md`.

1. **Test first.** `tests/integration/test_routes_<feature>.py` with the
   `client`, `test_user` and `auth_headers` fixtures: the happy path, a
   missing/invalid body (400), another user's resource (404), no token (401).
2. **Schemas.** Request/response Pydantic models in the feature module of
   `src/api/schemas/`: requests inherit `RequestModel`, responses `ResponseModel`
   (`src/api/schemas/base.py`). Query parameters get a schema too (B4).
3. **Route.** In the feature module of `src/api/routes/`: `@api.output`,
   `@api.doc(responses=[...])`, `@require_auth`, `@validate_request`. Keep it
   thin (B3): logic goes to `src/api/helpers/`, `src/agent/` or
   `src/db/models/` (SQL lives only there). Errors via `raise_*_error()`.
   A public endpoint (no `@require_auth`) needs a stated reason (S4).
4. **Ownership.** Every DB read of a user's resource is scoped by `user.id`.
5. **Contract.** `make openapi && make types`, then a method in the matching
   module of `web/src/api/`. Use the generated types (F6); don't hand-copy them.
6. **Frontend** (if the endpoint has UI): an E2E test in `web/tests/e2e/`
   (rebuild first) and a mock route in `tests/e2e-server.py` if the E2E server
   needs one.
7. **Docs.** The feature's `docs/features/` page lists its endpoints.
8. **Verify.** `make lint` and `make test-all`, exit codes checked.
