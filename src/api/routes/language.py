"""Language learning routes: programs and tutor conversations.

All five endpoints come from the shared program-routes factory
(src/api/routes/programs.py); this module only supplies the
language-specific configuration.
"""

from apiflask import APIBlueprint

from src.api.routes.programs import ProgramRoutesConfig, register_program_routes
from src.api.schemas import (
    CreateLanguageProgramRequest,
    LanguageConversationResponse,
    LanguageProgramsResponse,
    LanguageResetResponse,
    StatusResponse,
)

api = APIBlueprint("language", __name__, url_prefix="/api", tag="Language")

register_program_routes(
    api,
    ProgramRoutesConfig(
        namespace="language",
        display_name="Language",
        kv_suffixes=(
            "profile",
            "assessment",
            "vocabulary",
            "grammar",
            "weak_points",
            "session_history",
            "last_session",
            "stats",
        ),
        programs_response=LanguageProgramsResponse,
        conversation_response=LanguageConversationResponse,
        reset_response=LanguageResetResponse,
        status_response=StatusResponse,
        create_request=CreateLanguageProgramRequest,
    ),
)
