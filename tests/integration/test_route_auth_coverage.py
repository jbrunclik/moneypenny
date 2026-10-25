"""Every route requires auth unless it is on the explicit public list (S4).

A new route without @require_auth would serve anyone; this walks the whole
URL map so it can't be forgotten. Two checks per route: the view goes
through require_auth, and an anonymous request is refused with 401.
"""

import re
from collections.abc import Callable
from typing import Any

from flask import Flask
from flask.testing import FlaskClient

# Public by design - each needs a reason
PUBLIC_ENDPOINTS = {
    "index": "the app shell; the frontend handles sign-in",
    "static": "built assets",
    "static_files": "built assets and PWA files",
    "service_worker": "push service worker, must load before sign-in",
    "artifact_frame": "sandboxed artifact frame; holds no user data",
    "privacy_policy": "public policy page",
    "auth.google_auth": "the sign-in endpoint itself (rate-limited)",
    "auth.get_client_id": "the Google client id the sign-in button needs",
    "system.health_check": "deploy health gate",
    "system.readiness_check": "deploy health gate",
    "system.get_version": "deploy-version check by open clients",
    # S10: served in development and tests only
    "openapi.spec": "API schema",
    "openapi.docs": "API docs UI",
    "openapi.swagger_ui_oauth_redirect": "API docs UI",
}

# APIFlask's @api.input validates the body before require_auth runs, so an
# anonymous request with no body gets 400, not 401. B4 moves these to
# @validate_request; remove each entry as it moves (the list only shrinks).
INPUT_BEFORE_AUTH = {
    "agents.create_agent",
    "agents.update_agent",
    "agents.enhance_prompt",
    "agents.parse_schedule",
    "kv_store.set_value",
    "memory.update_memory_protection",
}


def _goes_through_require_auth(view: Callable[..., Any]) -> bool:
    fn: Any = view
    while fn is not None:
        # wraps() copies __qualname__ from the wrapped view; the code object
        # keeps the decorator's own name
        code = getattr(fn, "__code__", None)
        if code is not None and code.co_qualname.startswith("require_auth."):
            return True
        fn = getattr(fn, "__wrapped__", None)
    return False


def _sample_url(rule: str) -> str:
    rule = re.sub(r"<int:[^<>]+>", "1", rule)
    return re.sub(r"<(?:[^:<>]+:)?[^<>]+>", "x", rule)


def test_every_private_route_goes_through_require_auth(app: Flask) -> None:
    unguarded = sorted(
        rule.endpoint
        for rule in app.url_map.iter_rules()
        if rule.endpoint not in PUBLIC_ENDPOINTS
        and not _goes_through_require_auth(app.view_functions[rule.endpoint])
    )
    assert unguarded == [], (
        f"routes without @require_auth (or add to PUBLIC_ENDPOINTS): {unguarded}"
    )


def test_anonymous_requests_are_refused(app: Flask, client: FlaskClient) -> None:
    served = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint in PUBLIC_ENDPOINTS:
            continue
        for method in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
            status = client.open(_sample_url(rule.rule), method=method).status_code
            expected = {400, 401} if rule.endpoint in INPUT_BEFORE_AUTH else {401}
            if status not in expected:
                served.append(f"{method} {rule.rule} -> {status}")
    assert served == []


def test_allow_lists_name_real_endpoints(app: Flask) -> None:
    """A renamed or removed endpoint must leave the lists too."""
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
    assert set(PUBLIC_ENDPOINTS) - endpoints == set()
    assert INPUT_BEFORE_AUTH - endpoints == set()
