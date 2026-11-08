"""The shared summary-model call for conversation compaction.

Chat compaction (src/agent/conversation_compaction.py) summarizes long
histories - for chat turns and agent runs alike - through run_summary_model.
The old destructive agent compaction (it deleted all but the last messages)
is gone: one non-destructive compaction for every conversation.
"""

from __future__ import annotations

from google.genai.types import GenerateContentConfig, ThinkingConfig, ThinkingLevel

from src.agent.gemini_clients import shared_genai_client
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


def run_summary_model(prompt: str) -> str | None:
    """Run the fast summarization model on a prompt.

    Returns the stripped summary text, or None if the model returned nothing
    or raised. Callers supply their own fallback text.
    """
    try:
        client = shared_genai_client()
        response = client.models.generate_content(
            model=Config.AI_ASSIST_MODEL,
            contents=prompt,
            config=GenerateContentConfig(
                temperature=0.3,  # More deterministic for summaries
                # Summaries are extraction, not reasoning: on production
                # conversations LOW kept fact recall (81-92% vs 74-88% at the
                # API default) at ~30% lower cost - thinking tokens were ~85%
                # of the summarizer's output spend.
                thinking_config=ThinkingConfig(thinking_level=ThinkingLevel.LOW),
            ),
        )
        if response.text:
            return response.text.strip()
        # No text without an exception is usually a blocked response (safety,
        # recitation) - record why, it is otherwise invisible
        candidate = response.candidates[0] if response.candidates else None
        logger.warning(
            "Summary model returned no text",
            extra={
                "finish_reason": str(getattr(candidate, "finish_reason", None)),
                "block_reason": str(getattr(response.prompt_feedback, "block_reason", None)),
            },
        )
        return None
    except Exception as e:  # compaction is best-effort; the next turn retries
        logger.exception("Failed to generate conversation summary", extra={"error": str(e)})
        return None
