"""The program route factory (src/api/routes/programs.py).

Every program feature (sports, language) gets the same endpoints from
`register_program_routes`, differing only in the url segment. The
behavior of each endpoint is tested per feature in test_routes_sports.py
and test_routes_language.py; this checks the contract that keeps them
alike: a feature registered through the factory exposes all of them.
"""

from apiflask import APIBlueprint, APIFlask
from flask import Flask

from src.api.routes.programs import ProgramRoutesConfig, register_program_routes
from src.api.schemas.common import StatusResponse
from src.api.schemas.programs import (
    CreateSportsProgramRequest,
    SportsConversationResponse,
    SportsProgramsResponse,
    SportsResetResponse,
)
from src.db.models.programs import PROGRAM_FEATURES


def _program_endpoints(ns: str) -> set[tuple[str, str]]:
    return {
        ("GET", f"/api/{ns}/programs"),
        ("POST", f"/api/{ns}/programs"),
        ("DELETE", f"/api/{ns}/programs/<program_id>"),
        ("PUT", f"/api/{ns}/programs/<program_id>/quick-actions"),
        ("GET", f"/api/{ns}/<program>/conversation"),
        ("POST", f"/api/{ns}/<program>/reset"),
    }


def _routes(app: Flask) -> set[tuple[str, str]]:
    return {
        (method, rule.rule)
        for rule in app.url_map.iter_rules()
        for method in (rule.methods or set()) - {"HEAD", "OPTIONS"}
    }


def test_the_factory_registers_every_program_endpoint() -> None:
    api = APIBlueprint("hobby", __name__, url_prefix="/api")
    register_program_routes(
        api,
        ProgramRoutesConfig(
            namespace="hobby",
            display_name="Hobby",
            kv_suffixes=("goals",),
            programs_response=SportsProgramsResponse,
            conversation_response=SportsConversationResponse,
            reset_response=SportsResetResponse,
            status_response=StatusResponse,
            create_request=CreateSportsProgramRequest,
        ),
    )
    app = APIFlask(__name__)
    app.register_blueprint(api)

    assert _program_endpoints("hobby") <= _routes(app)


def test_every_program_feature_is_served(app: Flask) -> None:
    routes = _routes(app)
    for ns in PROGRAM_FEATURES:
        missing = _program_endpoints(ns) - routes
        assert missing == set(), f"{ns}: {sorted(missing)}"
