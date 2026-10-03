"""Turn setup shared by the batch and streaming chat endpoints.

Both endpoints validate the request, save the user message, build history and
set up per-turn agent context the same way. They used to carry separate copies
that drifted: batch mode built interactive-agent goals without
resolve_agent_system_prompt(), never cleared the request contextvars when the
turn raised, and the streaming producer thread re-set a hand-picked subset of
them.

- prepare_turn(): request validation + user message persistence + history.
- build_turn_context(): program/agent context and compacted history, as a
  TurnContext whose apply()/clear() own every per-turn contextvar. Contextvars
  don't cross threads, so the streaming producer calls apply() again.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from src.agent.agent import ChatAgent, _planner_dashboard_context
from src.agent.deep_research.offer import PlanError
from src.agent.deep_research.plan import (
    DeepResearchPlan,
    OfferConflict,
    OfferNotFound,
    start_plan,
)
from src.agent.executor import AgentContext, clear_agent_context, set_agent_context
from src.agent.gemini_files import attach_gemini_file_uris
from src.agent.history import enrich_history
from src.agent.interjection import clear_interjection
from src.agent.tool_results import set_current_request_id
from src.agent.tools import (
    set_conversation_context,
    set_current_message_files,
    set_language_context,
    set_location_context,
    set_sports_context,
)
from src.api.errors import raise_conflict_error, raise_not_found_error, raise_validation_error
from src.api.helpers.program_context import load_language_context, load_sports_context
from src.api.schemas.chat import ChatRequest, DeepResearchStart
from src.api.schemas.common import MessageRole
from src.config import Config
from src.db.models import Conversation, Message, User, db
from src.utils.background_thumbnails import (
    mark_files_for_thumbnail_generation,
    queue_pending_thumbnails,
)
from src.utils.files import validate_files
from src.utils.logging import get_logger, log_payload_snippet

logger = get_logger(__name__)

_CONTINUE_INSTRUCTION = (
    "Continue your previous response from exactly where it left off. "
    "Do not repeat or summarize content you already wrote - just keep going."
)


@dataclass
class PreparedTurn:
    """A validated chat request whose user message is saved."""

    conv: Conversation
    user_msg: Message
    message_text: str
    files: list[dict[str, Any]]
    history: list[dict[str, Any]]
    force_tools: list[str] | None
    anonymous_mode: bool
    client_location: dict[str, Any] | None
    deep_research: DeepResearchPlan | None = None


def prepare_turn(user: User, data: ChatRequest, conv_id: str) -> PreparedTurn:
    """Validate a chat request, save the user message, build enriched history.

    A re-run (regenerate/continue) inserts no new user message: the existing
    message it anchors on stands in for it in responses and stream events.
    """
    conv = _get_chat_conversation(user, conv_id)
    message_text = data.message.strip()
    # OR the persisted flag with the request flag: a conversation marked
    # anonymous stays anonymous even if a stale client omits the flag, and a
    # brand-new conversation can be anonymous before the toggle is persisted.
    anonymous_mode = conv.anonymous_mode or data.anonymous_mode
    if data.anonymous_mode and not conv.anonymous_mode:
        db.set_conversation_anonymous_mode(conv_id, user.id, True)
    files = _validate_files(user, conv_id, [f.model_dump() for f in data.files])
    log_payload_snippet(
        logger,
        {
            "message_length": len(message_text),
            "file_count": len(files),
            "force_tools": data.force_tools,
            "anonymous_mode": anonymous_mode,
        },
    )

    # Validated (and the offer marked started) before the user message is
    # saved: an unrunnable plan must leave nothing behind
    plan = _start_deep_research(conv_id, data.deep_research) if data.deep_research else None

    if data.rerun_mode:
        message_text, history_messages, user_msg = _resolve_rerun(conv_id, data.rerun_mode)
    else:
        user_msg = _save_user_message(conv_id, message_text, files, data.client_message_id)
        history_messages = db.get_messages(conv_id)[:-1]  # Exclude the just-added message

    # A stale interjection from a previous turn must never steer this one
    clear_interjection(user.id, conv_id)

    # File DATA is left out of history (only metadata: name, type, message_id,
    # file_index) so large base64 isn't re-sent; tools fetch it on demand.
    return PreparedTurn(
        conv=conv,
        user_msg=user_msg,
        message_text=message_text,
        files=files,
        history=enrich_history(history_messages),
        force_tools=data.force_tools,
        anonymous_mode=anonymous_mode,
        client_location=data.client_location.model_dump() if data.client_location else None,
        deep_research=plan,
    )


def _start_deep_research(conv_id: str, start: DeepResearchStart) -> DeepResearchPlan:
    """The run's plan, or the matching API error."""
    try:
        return start_plan(conv_id, start.offer_message_id, start.sub_questions, start.context)
    except PlanError as e:
        raise_validation_error(str(e), field="deep_research")
    except OfferNotFound:
        raise_not_found_error("Research offer")
    except OfferConflict as e:
        raise_conflict_error(str(e))


def _get_chat_conversation(user: User, conv_id: str) -> Conversation:
    conv = db.get_conversation(conv_id, user.id)
    if not conv:
        logger.warning(
            "Conversation not found for chat",
            extra={"user_id": user.id, "conversation_id": conv_id},
        )
        raise_not_found_error("Conversation")

    # Block sending messages to agent conversations with pending approvals
    if conv.is_agent and conv.agent_id and db.has_pending_approval(conv.agent_id):
        logger.warning(
            "Attempted to send message to agent with pending approval",
            extra={"user_id": user.id, "conversation_id": conv_id, "agent_id": conv.agent_id},
        )
        raise_validation_error(
            "Cannot send messages while an action is awaiting approval. "
            "Please approve or reject the pending action first."
        )
    return conv


def _validate_files(user: User, conv_id: str, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Content validation (base64 decoding, size); Pydantic checked structure."""
    if not files:
        return files
    is_valid, error = validate_files(files)
    if not is_valid:
        logger.warning(
            "File validation failed",
            extra={
                "user_id": user.id,
                "conversation_id": conv_id,
                "error": error,
                "file_count": len(files),
            },
        )
        raise_validation_error(error or "File validation failed", field="files")
    return mark_files_for_thumbnail_generation(files)


def _dedupe_client_message_id(conv_id: str, client_message_id: str | None) -> None:
    """Make sends idempotent: reject a retry whose original POST already landed.

    409 tells the client the message exists (reconcile, don't re-send); a hit in
    another conversation means an ID collision and is a plain validation error.
    """
    if not client_message_id:
        return
    existing = db.get_message_by_id(client_message_id)
    if existing is None:
        return
    if existing.conversation_id == conv_id:
        raise_conflict_error("Message already received", details={"message_id": client_message_id})
    raise_validation_error("client_message_id is already in use", field="client_message_id")


def _save_user_message(
    conv_id: str,
    message_text: str,
    files: list[dict[str, Any]],
    client_message_id: str | None,
) -> Message:
    _dedupe_client_message_id(conv_id, client_message_id)
    user_msg = db.add_message(
        conv_id,
        MessageRole.USER,
        message_text,
        files=files if files else None,
        message_id=client_message_id,
    )
    if files:
        queue_pending_thumbnails(user_msg.id, files)
        # Upload videos to the Gemini Files API and annotate files with URIs
        # (annotations are transient: the message was already saved without them)
        attach_gemini_file_uris(user_msg.id, files)
    return user_msg


def _resolve_rerun(conv_id: str, rerun_mode: str) -> tuple[str, list[Message], Message]:
    """Inputs for a re-run turn: no new user message is inserted.

    Returns (message_text, history_messages, anchor_msg). anchor_msg is the
    existing message that stands in for the "current user message" in
    response payloads/stream events.
    """
    existing = db.get_messages(conv_id)
    if not existing:
        raise_validation_error("Nothing to re-run in an empty conversation")
    last = existing[-1]
    if rerun_mode == "regenerate":
        if last.role != MessageRole.USER:
            raise_validation_error(
                "Regenerate requires the conversation to end with a user message "
                "(delete the assistant response first)"
            )
        return last.content, existing[:-1], last
    if last.role != MessageRole.ASSISTANT:
        raise_validation_error(
            "Nothing to continue - the last message is not an assistant response"
        )
    return _CONTINUE_INSTRUCTION, existing, last


@dataclass
class TurnContext:
    """Everything the agent needs for one turn, plus the contextvars tools read."""

    request_id: str
    conv_id: str
    user_id: str
    message_text: str
    user_name: str | None = None
    custom_instructions: str | None = None
    model: str = Config.DEFAULT_MODEL
    conversation_title: str | None = None
    files: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    force_tools: list[str] | None = None
    anonymous_mode: bool = False
    client_location: dict[str, Any] | None = None
    is_planning: bool = False
    dashboard_data: dict[str, Any] | None = None
    sports_program: str | None = None
    sports_context: dict[str, Any] | None = None
    language_program: str | None = None
    language_context: dict[str, Any] | None = None
    # Interactive agent conversation: tool filtering for the ChatAgent, and
    # the AgentContext permission checks and kv_store read
    agent_context: dict[str, Any] | None = None
    agent_execution_context: AgentContext | None = None
    # Set for a deep-research turn (the stream producer runs the pipeline)
    deep_research: DeepResearchPlan | None = None

    @property
    def timeout_seconds(self) -> int:
        """How long this turn may run (a deep-research run outlasts a chat turn)."""
        return (
            Config.DEEP_RESEARCH_RUN_TIMEOUT_SECONDS if self.deep_research else Config.CHAT_TIMEOUT
        )

    @property
    def is_autonomous(self) -> bool:
        return self.agent_execution_context is not None

    def apply(self) -> None:
        """Set this turn's contextvars in the current thread."""
        set_current_request_id(self.request_id)
        set_current_message_files(self.files if self.files else None)
        set_conversation_context(self.conv_id, self.user_id)
        set_location_context(self.client_location)
        if self.dashboard_data is not None:
            # Initial dashboard for potential refresh_planner_dashboard calls
            _planner_dashboard_context.set(self.dashboard_data)
        if self.agent_execution_context is not None:
            set_agent_context(self.agent_execution_context)
        if self.sports_program:
            set_sports_context(self.sports_program)
        if self.language_program:
            set_language_context(self.language_program)

    def clear(self) -> None:
        """Reset every contextvar apply() set (threads are reused across requests)."""
        set_current_request_id(None)
        set_current_message_files(None)
        set_conversation_context(None, None)
        set_location_context(None)
        if self.dashboard_data is not None:
            _planner_dashboard_context.set(None)
        if self.agent_execution_context is not None:
            clear_agent_context()
        if self.sports_program:
            set_sports_context(None)
        if self.language_program:
            set_language_context(None)

    def create_agent(self, include_thoughts: bool = False) -> ChatAgent:
        return ChatAgent(
            model_name=self.model,
            include_thoughts=include_thoughts,
            anonymous_mode=self.anonymous_mode,
            is_planning=self.is_planning,
            is_autonomous=self.is_autonomous,
            agent_context=self.agent_context,
            is_sports=self.sports_program is not None,
            sports_context=self.sports_context,
            is_language=self.language_program is not None,
            language_context=self.language_context,
        )

    def agent_call_kwargs(self) -> dict[str, Any]:
        """Arguments for ChatAgent.chat_batch / stream_chat_events."""
        return {
            "text": self.message_text,
            "files": self.files,
            "history": self.history,
            "force_tools": self.force_tools,
            "user_name": self.user_name,
            "user_id": self.user_id,
            "custom_instructions": self.custom_instructions,
            "is_planning": self.is_planning,
            "dashboard_data": self.dashboard_data,
            "conversation_id": self.conv_id,
            "is_sports": self.sports_program is not None,
            "sports_context": self.sports_context,
            "is_language": self.language_program is not None,
            "language_context": self.language_context,
            "conversation_title": self.conversation_title,
        }


def build_turn_context(user: User, turn: PreparedTurn, request_id: str) -> TurnContext:
    """Load program/agent context and compact history for this turn."""
    conv = turn.conv
    ctx = TurnContext(
        request_id=request_id,
        conv_id=conv.id,
        user_id=user.id,
        message_text=turn.message_text,
        user_name=user.name,
        custom_instructions=user.custom_instructions,
        model=conv.model,
        conversation_title=conv.title,
        files=turn.files,
        history=turn.history,
        force_tools=turn.force_tools,
        anonymous_mode=turn.anonymous_mode,
        client_location=turn.client_location,
        deep_research=turn.deep_research,
        is_planning=conv.is_planning,
    )
    if conv.is_planning:
        ctx.dashboard_data = _load_planner_dashboard(user)
    if conv.is_sports and conv.sports_program:
        ctx.sports_program = conv.sports_program
        ctx.sports_context = load_sports_context(user.id, conv.sports_program)
    if conv.is_language and conv.language_program:
        ctx.language_program = conv.language_program
        ctx.language_context = load_language_context(user.id, conv.language_program)
    if conv.is_agent and conv.agent_id:
        _attach_agent_context(ctx, user, conv.agent_id)

    # Compact long histories for regular (non-agent) conversations to bound
    # per-turn input cost. Agent conversations use their own destructive
    # compaction, so they are left untouched.
    if not ctx.is_autonomous:
        from src.agent.conversation_compaction import build_compacted_history

        ctx.history = build_compacted_history(user.id, conv.id, ctx.history)
    return ctx


def _load_planner_dashboard(user: User) -> dict[str, Any]:
    from src.api.routes.calendar import _get_valid_calendar_access_token
    from src.utils.planner_data import build_planner_dashboard

    # Refresh calendar token if needed (expires hourly)
    calendar_token = _get_valid_calendar_access_token(user)
    dashboard = build_planner_dashboard(
        todoist_token=user.todoist_access_token,
        calendar_token=calendar_token,
        garmin_token=user.garmin_token,
        user_id=user.id,
        force_refresh=False,
        db=db,
    )
    return asdict(dashboard)


def _attach_agent_context(ctx: TurnContext, user: User, agent_id: str) -> None:
    """Apply an interactive agent conversation's tool permissions and goals."""
    from src.agent.daily_briefing import resolve_agent_system_prompt

    agent_record = db.get_agent(agent_id, user.id)
    if not agent_record:
        return
    logger.debug(
        "Interactive agent conversation - applying tool permissions",
        extra={
            "user_id": user.id,
            "conversation_id": ctx.conv_id,
            "agent_id": agent_record.id,
            "tool_permissions": agent_record.tool_permissions,
        },
    )
    ctx.agent_execution_context = AgentContext(
        agent=agent_record, user=user, trigger_chain=[agent_record.id]
    )
    # tool_permissions=None means all tools, [] means no tools
    ctx.agent_context = {
        "name": agent_record.name,
        "description": agent_record.description,
        "schedule": agent_record.schedule,
        "timezone": agent_record.timezone,
        "goals": resolve_agent_system_prompt(agent_record),
        "tools": agent_record.tool_permissions,
        "trigger_type": "interactive",
    }
