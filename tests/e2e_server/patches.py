"""The `src` patch targets: every external service the app would call."""

import contextlib
from unittest.mock import patch

from tests.e2e_server.deep_research_fake import mock_run_deep_research
from tests.e2e_server.integration_fakes import (
    create_mock_gemini_files_client,
    create_mock_genai,
    create_mock_google_tokeninfo,
    create_mock_httpx,
    mock_search_web,
    mock_search_web_detailed,
)
from tests.e2e_server.llm_fakes import (
    create_mock_llm,
    create_mock_stream_chat,
    create_mock_stream_chat_events,
    mock_check_grounding,
    mock_should_check,
)


def apply_service_patches(stack: contextlib.ExitStack) -> None:
    """Apply external service mocks; they stay active while `stack` is open."""
    stack.enter_context(patch("src.agent.graph.ChatGoogleGenerativeAI", create_mock_llm()))
    stack.enter_context(patch("src.agent.gemini_clients.ChatGoogleGenerativeAI", create_mock_llm()))
    stack.enter_context(patch("src.agent.tools.web.search_web_detailed", mock_search_web_detailed))
    stack.enter_context(patch("src.agent.tools.research.search_web", mock_search_web))
    stack.enter_context(patch("src.agent.tools.web.httpx.Client", create_mock_httpx()))
    stack.enter_context(patch("src.agent.gemini_clients.genai.Client", create_mock_genai()))
    stack.enter_context(
        patch("src.agent.gemini_files._get_client", create_mock_gemini_files_client())
    )
    # Conversation compaction summarizes long histories via a separate
    # google-genai client (not the langchain mock above). Stub it so the
    # real compaction path runs without a network call when a seeded
    # conversation exceeds CONVERSATION_COMPACTION_THRESHOLD.
    stack.enter_context(
        patch("src.agent.compaction.run_summary_model", return_value="[mock summary]")
    )
    stack.enter_context(patch("src.auth.google_auth.httpx.get", create_mock_google_tokeninfo()))
    stack.enter_context(patch("src.agent.grounding_check.should_check", mock_should_check))
    stack.enter_context(patch("src.agent.grounding_check.check_grounding", mock_check_grounding))
    stack.enter_context(patch("src.agent.agent.ChatAgent.stream_chat", create_mock_stream_chat()))
    stack.enter_context(
        patch("src.api.helpers.stream_producer.run_deep_research", mock_run_deep_research)
    )
    stack.enter_context(
        patch(
            "src.agent.agent.ChatAgent.stream_chat_events",
            create_mock_stream_chat_events(),
        )
    )
