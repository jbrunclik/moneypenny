"""Pydantic schemas for API request and response validation (the OpenAPI source).

Import from the feature module (``from src.api.schemas.agents import ...``);
this package deliberately re-exports nothing. Request schemas validate request
structure, types and constraints; response schemas document and validate
responses.

For file content validation (base64 decoding, size limits), see validate_files()
in src/utils/files.py which handles the content-level validation after Pydantic
validates the structure.
"""
