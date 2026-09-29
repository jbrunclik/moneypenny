"""Conversation title generation."""

from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from src.agent.content import extract_text_content
from src.config import Config
from src.utils.logging import get_logger

logger = get_logger(__name__)


def generate_title(user_message: str, assistant_response: str) -> str | None:
    """
    Generate a concise title for a conversation using Gemini.

    Args:
        user_message: The first user message
        assistant_response: The assistant's response

    Returns:
        A short, descriptive title (max ~50 chars), or None if generation
        failed. Callers should leave the existing title untouched on None so
        it can be retried opportunistically on the next user message.
    """
    logger.debug("Generating conversation title")
    # Use Flash model for fast, cheap title generation
    model = ChatGoogleGenerativeAI(
        model=Config.TITLE_GENERATION_MODEL,
        google_api_key=Config.GEMINI_API_KEY,
        temperature=Config.TITLE_GENERATION_TEMPERATURE,
    )

    # Truncate context to avoid sending too much data
    max_context = Config.TITLE_CONTEXT_MAX_LENGTH
    prompt = f"""Generate a very short, concise title (3-6 words max) for this conversation.
The title MUST start with a single relevant emoji followed by a space.
The title should capture the main topic or intent.
Write the title in the same language the user writes in.
Do NOT use quotes around the title.
Do NOT include prefixes like "Title:" or "Topic:".
Just output the emoji and title text directly.

Example format: 🐍 Python List Sorting

User: {user_message[:max_context]}
Assistant: {assistant_response[:max_context]}

Title:"""

    try:
        response = model.invoke([HumanMessage(content=prompt)])
        title = extract_text_content(response.content).strip()
        # Clean up any quotes or prefixes that slipped through
        title = title.strip("\"'")
        if title.lower().startswith("title:"):
            title = title[6:].strip()
        # Truncate if too long
        if len(title) > Config.TITLE_MAX_LENGTH:
            title = title[: Config.TITLE_TRUNCATE_LENGTH] + "..."
        final_title = title or f"💬 {user_message[: Config.TITLE_FALLBACK_LENGTH]}"
        logger.debug("Title generated", extra={"title": final_title})
        return final_title
    except Exception as e:
        # Catch broadly: provider SDKs wrap errors in their own exception types
        # (e.g. ChatGoogleGenerativeAIError on 429), and title generation must
        # never break the surrounding message-save flow. Returning None tells
        # the caller to leave the default title in place so the next user
        # message will retry opportunistically.
        logger.warning(
            "Title generation failed",
            extra={"error": str(e), "error_type": type(e).__name__},
        )
        return None
