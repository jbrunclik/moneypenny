---
paths:
  - "src/api/**"
---

# API conventions

Adding an endpoint:

1. Request/response Pydantic schemas in [src/api/schemas.py](../../src/api/schemas.py) — the source of the OpenAPI spec. Backend enums are `str, Enum` there.
2. Handler in the feature's module in [src/api/routes/](../../src/api/routes/): `@api.output(Schema)`, `@api.doc(responses=[...])`, `@require_auth` (injects `user`), `@validate_request(Schema)` from `src/api/validation.py` (injects `data`).
3. Errors via `raise_*_error()` from [src/api/errors.py](../../src/api/errors.py) (e.g. `raise_not_found_error("Conversation")`, `raise_conflict_error(message, details)`), never raw exceptions.
4. SQL only in [src/db/models/](../../src/db/models/); routes stay thin (no business logic that belongs in `src/agent/` or a helper).
5. `make openapi && make types`, then a client method in [web/src/api/client.ts](../../web/src/api/client.ts).
6. Integration test in `tests/integration/test_routes_<feature>.py` with the `client`, `test_user`, `auth_headers` fixtures.

- **Do not hand-edit** `static/openapi.json` — it is generated (a hook blocks it).
- See [docs/architecture/api-design.md](../../docs/architecture/api-design.md).
