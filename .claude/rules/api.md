---
paths:
  - "src/api/**"
---

# API conventions

- **Add a new endpoint**: use the `api-endpoint` agent, or manually add to the appropriate module in [src/api/routes/](../../src/api/routes/). Use `@api.output()` for the response schema.
- **Schemas**: Pydantic request/response schemas live in [src/api/schemas.py](../../src/api/schemas.py) — they are the source of the OpenAPI spec.
- **Enums (backend)**: `str, Enum` in `schemas.py`.
- See [docs/architecture/api-design.md](../../docs/architecture/api-design.md) for the full design.
- **Do not hand-edit** `static/openapi.json` — it is generated. Run `make openapi` to regenerate it.
