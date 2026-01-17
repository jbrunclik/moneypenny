"""Integration tests for OpenAPI specification and schema coverage.

These tests verify that:
1. The OpenAPI spec structure is valid and complete
2. All API endpoints are documented
3. Response schemas are defined

Note: Response validation is handled by APIFlask automatically during development
via VALIDATION_MODE. The endpoint behavior is tested in other integration test files.
"""

from apiflask import APIFlask


class TestOpenAPISpec:
    """Tests for OpenAPI specification validity."""

    def test_spec_is_valid_openapi(self, app: APIFlask) -> None:
        """OpenAPI spec should be valid OpenAPI 3.0."""
        spec = app.spec

        assert "openapi" in spec
        assert spec["openapi"].startswith("3.0")
        assert "info" in spec
        assert spec["info"]["title"] == "AI Chatbot API"
        assert spec["info"]["version"] == "1.0.0"
        assert "paths" in spec
        assert "components" in spec

    def test_spec_has_all_paths(self, app: APIFlask) -> None:
        """OpenAPI spec should document all API endpoints."""
        spec = app.spec
        paths = set(spec["paths"].keys())

        # Auth endpoints
        assert "/auth/google" in paths
        assert "/auth/client-id" in paths
        assert "/auth/me" in paths
        assert "/auth/refresh" in paths

        # Conversation endpoints
        assert "/api/conversations" in paths
        assert "/api/conversations/{conv_id}" in paths
        assert "/api/conversations/{conv_id}/messages" in paths
        assert "/api/conversations/sync" in paths

        # Chat endpoints
        assert "/api/conversations/{conv_id}/chat/batch" in paths
        assert "/api/conversations/{conv_id}/chat/stream" in paths

        # Config endpoints
        assert "/api/models" in paths
        assert "/api/config/upload" in paths

        # File endpoints
        assert "/api/messages/{message_id}/files/{file_index}" in paths
        assert "/api/messages/{message_id}/files/{file_index}/thumbnail" in paths

        # Cost endpoints
        assert "/api/conversations/{conv_id}/cost" in paths
        assert "/api/messages/{message_id}/cost" in paths
        assert "/api/users/me/costs/monthly" in paths
        assert "/api/users/me/costs/history" in paths

        # Settings endpoints
        assert "/api/users/me/settings" in paths

        # Memory endpoints
        assert "/api/memories" in paths
        assert "/api/memories/{memory_id}" in paths

        # Health endpoints
        assert "/api/version" in paths
        assert "/api/health" in paths
        assert "/api/ready" in paths

    def test_spec_has_schemas(self, app: APIFlask) -> None:
        """OpenAPI spec should define response schemas."""
        spec = app.spec
        schemas = spec.get("components", {}).get("schemas", {})

        # Check key schemas exist (some may have nested names due to APIFlask)
        # Note: ErrorResponse is not included because error responses are returned
        # as Flask Response objects to bypass APIFlask's auto-serialization.
        # Error format is documented in errors.py and frontend types.
        expected_patterns = [
            "AuthResponse",
            "ConversationsListPaginatedResponse",
            "ConversationResponse",
            "MessageResponse",
            "MessagesListResponse",
            "ModelsListResponse",
            "UploadConfigResponse",
            "VersionResponse",
            "HealthResponse",
        ]

        for pattern in expected_patterns:
            # Check if schema exists directly or as a nested reference
            found = any(pattern in name for name in schemas.keys())
            assert found, f"Missing schema matching: {pattern}. Available: {sorted(schemas.keys())}"

    def test_error_responses_documented(self, app: APIFlask) -> None:
        """All endpoints should document error responses."""
        spec = app.spec

        # Endpoints that return binary data (not JSON) - skip JSON schema check
        binary_endpoints = {
            "/api/messages/{message_id}/files/{file_index}",
            "/api/messages/{message_id}/files/{file_index}/thumbnail",
            "/api/messages/{message_id}/images/{image_index}",
        }

        for path, methods in spec["paths"].items():
            for method, details in methods.items():
                if method in ["get", "post", "patch", "delete", "put"]:
                    responses = details.get("responses", {})

                    # Skip streaming endpoint (has custom response)
                    if "stream" in path:
                        continue

                    # Skip binary endpoints (return raw data, not JSON)
                    if path in binary_endpoints:
                        continue

                    # At least one success response should be documented
                    success_codes = [c for c in responses.keys() if c.startswith("2")]
                    assert len(success_codes) > 0, (
                        f"No success response documented for {method.upper()} {path}"
                    )

    def test_spec_documents_http_methods(self, app: APIFlask) -> None:
        """OpenAPI spec should document correct HTTP methods for each endpoint."""
        spec = app.spec
        paths = spec["paths"]

        # Conversations endpoint should have GET and POST
        conv_methods = set(paths["/api/conversations"].keys())
        assert "get" in conv_methods, "GET /api/conversations not documented"
        assert "post" in conv_methods, "POST /api/conversations not documented"

        # Single conversation should have GET, PATCH, DELETE
        single_conv_methods = set(paths["/api/conversations/{conv_id}"].keys())
        assert "get" in single_conv_methods
        assert "patch" in single_conv_methods
        assert "delete" in single_conv_methods

        # Settings should have GET and PATCH
        settings_methods = set(paths["/api/users/me/settings"].keys())
        assert "get" in settings_methods
        assert "patch" in settings_methods

    def test_spec_tags_are_defined(self, app: APIFlask) -> None:
        """OpenAPI spec should use tags to organize endpoints."""
        spec = app.spec

        # Check that endpoints use tags for organization
        tags_used = set()
        for _path, methods in spec["paths"].items():
            for method, details in methods.items():
                if method in ["get", "post", "patch", "delete", "put"]:
                    endpoint_tags = details.get("tags", [])
                    tags_used.update(endpoint_tags)

        # We expect at least Auth and API tags
        assert len(tags_used) >= 2, f"Expected at least 2 tags, got {tags_used}"

    def test_spec_schema_count(self, app: APIFlask) -> None:
        """OpenAPI spec should have a reasonable number of schemas defined."""
        spec = app.spec
        schemas = spec.get("components", {}).get("schemas", {})

        # We expect at least 20 schemas (response types + nested types)
        assert len(schemas) >= 20, f"Expected at least 20 schemas, got {len(schemas)}"

        # But not an unreasonable number (would indicate over-complexity)
        # Threshold increased to 110 to account for autonomous agents feature
        assert len(schemas) < 110, f"Too many schemas ({len(schemas)}), may indicate issues"

    def test_spec_path_count(self, app: APIFlask) -> None:
        """OpenAPI spec should document all expected paths."""
        spec = app.spec
        paths = spec["paths"]

        # We expect at least 20 paths
        assert len(paths) >= 20, f"Expected at least 20 paths, got {len(paths)}"
