"""Routes validated with @validate_request document their request body.

The OpenAPI spec is the source of the frontend's generated types; a route whose
body schema is missing from it forces a hand-written request type that drifts.
"""

from flask import Flask


def _operation(app: Flask, path: str, method: str) -> dict:
    return app.spec["paths"][path][method]  # type: ignore[attr-defined,no-any-return]


def test_a_validated_body_appears_in_the_spec(app: Flask) -> None:
    body = _operation(app, "/api/ai-assist/parse-schedule", "post")["requestBody"]
    schema = body["content"]["application/json"]["schema"]
    assert schema == {"$ref": "#/components/schemas/ParseScheduleRequest"}
    fields = app.spec["components"]["schemas"]["ParseScheduleRequest"]["properties"]  # type: ignore[attr-defined]
    assert "natural_language" in fields


def test_every_validated_route_documents_its_body(app: Flask) -> None:
    missing = []
    for rule in app.url_map.iter_rules():
        view = app.view_functions[rule.endpoint]
        if getattr(view, "_validated_body", None) is None:
            continue
        for method in rule.methods - {"HEAD", "OPTIONS"}:  # type: ignore[operator]
            path = "/".join(
                "{" + part[1:-1].split(":")[-1] + "}" if part.startswith("<") else part
                for part in rule.rule.split("/")
            )
            operation = app.spec["paths"].get(path, {}).get(method.lower(), {})  # type: ignore[attr-defined]
            if "requestBody" not in operation:
                missing.append(f"{method} {rule.rule}")
    assert not missing, missing
