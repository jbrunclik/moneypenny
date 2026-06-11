"""Sports tracking routes: programs and trainer conversations.

All five endpoints come from the shared program-routes factory
(src/api/routes/programs.py); this module only supplies the
sports-specific configuration.
"""

from apiflask import APIBlueprint

from src.api.routes.programs import ProgramRoutesConfig, register_program_routes
from src.api.schemas import (
    CreateSportsProgramRequest,
    SportsConversationResponse,
    SportsProgramsResponse,
    SportsResetResponse,
    StatusResponse,
)

api = APIBlueprint("sports", __name__, url_prefix="/api", tag="Sports")

register_program_routes(
    api,
    ProgramRoutesConfig(
        namespace="sports",
        display_name="Sports",
        kv_suffixes=("goals", "preferences", "routine", "progress", "last_session"),
        programs_response=SportsProgramsResponse,
        conversation_response=SportsConversationResponse,
        reset_response=SportsResetResponse,
        status_response=StatusResponse,
        create_request=CreateSportsProgramRequest,
    ),
)
