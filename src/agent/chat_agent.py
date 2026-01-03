"""Chat agent with tool support using LangGraph.

This module implements an agentic chat loop using LangGraph that supports tool calling.
The agent can use web search and URL fetching tools to answer questions about current events.

Architecture:
    The agent uses a cyclic graph pattern for tool calling:

    ┌─────────────────────────────────────────────────────┐
    │                                                     │
    │   Entry ──► Chat Node ──► Conditional Edge ──► END  │
    │                │                 │                  │
    │                │           (has tool calls?)        │
    │                │                 │                  │
    │                │                 ▼                  │
    │                └─────────── Tool Node               │
    │                                                     │
    └─────────────────────────────────────────────────────┘

Flow:
    1. User message is added to the conversation state
    2. Chat node invokes the LLM with the current messages
    3. If the LLM response contains tool calls:
       - Tool node executes the requested tools
       - Results are added as ToolMessages
       - Control returns to Chat node (step 2)
    4. If no tool calls, the response is returned to the user

Components:
    - AgentState: TypedDict holding conversation messages
    - ChatAgent: Main class with chat_batch() and stream_chat() methods
    - SYSTEM_PROMPT: Instructions for when to use web tools
    - extract_text_content(): Helper to handle Gemini's varied response formats:
        * str: Plain text responses (most common)
        * dict: Structured content like {'type': 'text', 'text': '...'}
        * list: Multi-part responses with tool calls, e.g.,
          [{'type': 'text', 'text': '...'}, {'type': 'tool_use', ...}]
          Also includes metadata like 'extras', 'signature' which are skipped
"""

import contextvars
import json
import re
from collections.abc import Generator
from datetime import datetime
from typing import Annotated, Any, Literal, TypedDict, cast

from google.api_core.exceptions import GoogleAPIError
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode as BaseToolNode

from src.agent.tools import TOOLS
from src.config import Config
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)


def strip_full_result_from_tool_content(content: str) -> str:
    """Strip the _full_result field from tool result JSON to avoid sending large data to LLM.

    The generate_image tool returns image data in a _full_result field that should be
    extracted server-side but not sent back to the LLM (to avoid ~650K tokens of base64).

    Args:
        content: The tool result content (JSON string)

    Returns:
        The content with _full_result removed, or original content if not JSON
    """
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "_full_result" in data:
            # Remove the _full_result field before sending to LLM
            data_for_llm = {k: v for k, v in data.items() if k != "_full_result"}
            return json.dumps(data_for_llm)
        return content
    except (json.JSONDecodeError, TypeError):
        return content


# Contextvar to hold the current request ID for tool result capture
# This allows us to capture full results per-request without passing request_id through the graph
_current_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_request_id", default=None
)

# Global storage for full tool results before stripping (keyed by thread/request)
# This allows us to capture the full results for server-side extraction while
# still stripping them before sending to the LLM
_full_tool_results: dict[str, list[dict[str, Any]]] = {}


def set_current_request_id(request_id: str | None) -> None:
    """Set the current request ID for tool result capture."""
    _current_request_id.set(request_id)


def get_full_tool_results(request_id: str) -> list[dict[str, Any]]:
    """Get and clear full tool results for a request."""
    return _full_tool_results.pop(request_id, [])


def create_tool_node(tools: list[Any]) -> Any:
    """Create a tool node that strips large data from results before sending to LLM.

    This prevents the ~650K token cost of sending generated images back to the model.
    The full tool results are still captured separately for server-side extraction.

    The request ID is read from the _current_request_id contextvar at runtime,
    allowing per-request capture while using a single shared graph instance.

    Args:
        tools: List of tools to use
    """
    base_tool_node = BaseToolNode(tools)

    def tool_node_with_stripping(state: AgentState) -> dict[str, Any]:
        """Execute tools and strip _full_result from results."""
        logger.debug("tool_node_with_stripping starting")

        # Get the current request ID from contextvar
        request_id = _current_request_id.get()

        # Call the base ToolNode
        result: dict[str, Any] = base_tool_node.invoke(state)

        # Capture full tool results BEFORE stripping, then strip for LLM
        if "messages" in result:
            for msg in result["messages"]:
                if isinstance(msg, ToolMessage) and isinstance(msg.content, str):
                    # Store the ORIGINAL content for server-side extraction
                    if request_id is not None:
                        if request_id not in _full_tool_results:
                            _full_tool_results[request_id] = []
                        _full_tool_results[request_id].append(
                            {"type": "tool", "content": msg.content}
                        )

                    # Now strip _full_result for the LLM
                    content_len_before = len(msg.content)
                    msg.content = strip_full_result_from_tool_content(msg.content)
                    content_len_after = len(msg.content)
                    if content_len_before != content_len_after:
                        logger.info(
                            "Stripped _full_result from tool message",
                            extra={
                                "content_len_before": content_len_before,
                                "content_len_after": content_len_after,
                                "bytes_saved": content_len_before - content_len_after,
                            },
                        )

        logger.debug("tool_node_with_stripping completed")
        return result

    return tool_node_with_stripping


BASE_SYSTEM_PROMPT = """You are a helpful, harmless, and honest AI assistant.

# Core Principles
- Be direct and confident in your responses. Avoid unnecessary hedging or filler phrases.
- If you don't know something, say so clearly rather than making things up.
- When asked for opinions, you can share perspectives while noting they're your views.
- Match the user's tone and level of formality.
- For complex questions, think step-by-step before answering.

# Response Format
- Use markdown formatting when it improves readability (headers, lists, code blocks).
- Keep responses concise unless the user asks for detail.
- For code: include brief comments, use consistent style, handle edge cases.
- When showing multiple options, use numbered lists with pros/cons.

# Safety & Ethics
- Never help with illegal activities, harm, or deception.
- Protect user privacy; don't ask for unnecessary personal information.
- For medical, legal, or financial questions, recommend consulting professionals.
- If a request seems harmful, explain why you can't help and offer alternatives."""

TOOLS_SYSTEM_PROMPT = """
# Tools Available
You have access to the following tools:

## Web Tools
- **web_search**: Search the web for current information, news, prices, events, etc. Returns JSON with results.
- **fetch_url**: Fetch and read the content of a specific web page.

## Image Generation
- **generate_image**: Generate images from text descriptions OR edit/modify uploaded images.
  - For text-to-image: Just provide a prompt
  - For image editing: If the user uploaded an image and wants it modified, use reference_images="all" to include it

## Code Execution
- **execute_code**: Execute Python code in a secure sandbox. Use for calculations, data processing, generating files/charts.
  - Pre-installed: numpy, pandas, matplotlib, scipy, sympy, pillow, reportlab, fpdf2
  - Save files to `/output/` directory to return them (e.g., PDFs, images)
  - NO network access, NO access to user's local files
  - 30 second timeout, 512MB memory limit
  - **For PDFs with non-ASCII text (accents, diacritics, Czech/Polish/etc.)**: Use fpdf2 with DejaVu font:
    ```python
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font('DejaVu', '', _get_dejavu_font())  # Use helper function
    pdf.set_font('DejaVu', size=12)
    pdf.cell(0, 10, 'Příliš žluťoučký kůň')  # Czech text works!
    pdf.output('/output/document.pdf')
    ```

# CRITICAL: How to Use Tools Correctly
You have function calling capabilities. To use a tool:
1. Call the tool function directly (NOT by writing JSON in your text response)
2. The tool will execute and return results
3. Then write your natural language response to the user

WRONG (do NOT do this):
```
{"action": "generate_image", "action_input": {"prompt": "..."}}
```

RIGHT: Call the tool function directly, then write a response like:
"Here's the image I created for you..."

IMPORTANT RULES:
- NEVER write tool calls as JSON text in your response
- You MUST ALWAYS include a natural language response that the user can see
- After ANY tool call completes, you MUST write text to explain what happened
- If generating an image, ALWAYS respond with text like "Here's the image I created for you..." or "I've generated..."
- NEVER leave the response empty after using a tool - the user needs to see what you did

# When to Use Web Tools
ALWAYS use web_search first when the user asks about:
- Current events, news, "what happened today/recently"
- Real-time data: stock prices, crypto, weather, sports scores
- Recent releases, updates, or announcements
- Anything that might have changed since your training cutoff
- Facts you're uncertain about (verify before answering)

After searching, use fetch_url to read specific pages for more details if needed.
Do NOT rely on training data for time-sensitive information.

# When to Use Image Generation
Use generate_image when the user:
- Asks you to create, generate, draw, make, or produce an image
- Wants a visualization, illustration, or artwork
- Requests modifications to a previously generated image (describe the full desired result)
- **Uploads an image and asks you to modify/edit it** (use reference_images parameter)

For image prompts, be specific and detailed:
- Include style (photorealistic, cartoon, watercolor, oil painting, etc.)
- Describe colors, lighting, composition, mood, and atmosphere
- If text should appear in the image, specify it clearly
- For modifications, describe the complete desired result, not just the changes

**Image Editing (with uploaded images):**
When the user uploads an image and asks you to modify it:
- Use reference_images="all" to include the uploaded image(s) as reference
- Or use reference_images="0" for the first image, "0,1" for first two, etc.
- The prompt should describe the desired modification or transformation
- Example: User uploads a photo and says "make me look like a wizard"
  → Call generate_image(prompt="Transform the person in the photo into a wizard with a magical hat, robes, and mystical aura", reference_images="all")

# When to Use Code Execution
Use execute_code when the user needs:
- **Mathematical calculations**: Complex math, statistics, solving equations
- **Data analysis**: Processing numbers, computing statistics, analyzing datasets
- **Charts and plots**: Line graphs, bar charts, scatter plots, histograms (use matplotlib)
- **Document generation**: Creating PDFs, reports, formatted documents (use reportlab)
- **Data transformation**: Converting between formats (CSV, JSON, etc.)
- **Symbolic math**: Algebra, calculus, equation solving (use sympy)
- **Scientific computing**: Matrix operations, signal processing (use numpy, scipy)

Code execution examples:
- "Calculate the compound interest on $10,000 at 5% for 10 years"
- "Create a bar chart comparing these sales numbers"
- "Generate a PDF invoice with these details"
- "Solve this quadratic equation: x² + 5x + 6 = 0"
- "Analyze this CSV data and find the average"

IMPORTANT for file generation:
- Save generated files to `/output/` directory (e.g., `/output/report.pdf`)
- Files saved there will be returned to the user as downloadable attachments
- Always tell the user what files were generated

# Knowledge Cutoff
Your training data has a cutoff date. For anything after that, use web_search.

# Response Metadata
When you use ANY tools, you MUST append a SINGLE metadata block at the very end of your response.
IMPORTANT: There must be only ONE metadata block per response, even if you use multiple different tools.

Use this exact format with the special markers:
<!-- METADATA:
{"sources": [...], "generated_images": [...]}
-->

## Rules for Sources (web_search, fetch_url)
- Include ALL sources you referenced: both from web_search results AND any URLs you fetched with fetch_url
- Only include sources you actually used information from in your response
- Each source needs "title" and "url" fields
- For fetch_url sources, use the page title (or URL domain if unknown) as the title

## Rules for Generated Images (generate_image)
- Include the exact prompt you used to generate the image
- Each generated_images entry needs: {"prompt": "the exact prompt you used"}

## General Metadata Rules
- Do NOT include this section if you didn't use any tools
- The JSON must be valid - use double quotes, escape special characters
- If you used BOTH web tools AND generate_image, include BOTH "sources" and "generated_images" arrays in the SAME metadata block
- Do NOT create separate metadata blocks for different tools - combine everything into ONE block

Example with both sources and generated images:
<!-- METADATA:
{"sources": [{"title": "Wikipedia", "url": "https://en.wikipedia.org/..."}], "generated_images": [{"prompt": "a majestic mountain sunset, photorealistic, golden hour lighting"}]}
-->

Example with only sources:
<!-- METADATA:
{"sources": [{"title": "Wikipedia", "url": "https://en.wikipedia.org/..."}]}
-->

Example with only generated images:
<!-- METADATA:
{"generated_images": [{"prompt": "a majestic mountain sunset, photorealistic, golden hour lighting"}]}
-->"""

CUSTOM_INSTRUCTIONS_PROMPT = """
# User's Custom Instructions
The user has provided these custom instructions for how you should respond:

{instructions}

Follow these instructions while still adhering to safety guidelines."""

MEMORY_SYSTEM_PROMPT = """
# User Memory System
You have access to a memory system that stores facts about the user for personalization.

## Memory Operations (in metadata block)
Include memory_operations in your metadata block when you want to modify the user's memories:
```json
{{"memory_operations": [
  {{"action": "add", "content": "Has a golden retriever named Max, adopted in 2020", "category": "fact"}},
  {{"action": "update", "id": "mem-xxx", "content": "Updated and consolidated fact about the user"}},
  {{"action": "delete", "id": "mem-xxx"}}
]}}
```

## Categories
- **preference**: Preferences and choices that affect recommendations (e.g., "Prefers Python for backend work due to its readability; uses TypeScript for frontend")
- **fact**: Personal and family facts - names, relationships, birthdays, pets, locations (e.g., "Wife's name is Sarah, birthday is March 15th")
- **context**: Work/life situation (e.g., "Works as a senior software engineer at a fintech startup, focusing on payment systems")
- **goal**: Ongoing projects, learning goals, aspirations (e.g., "Learning Spanish for a planned trip to Argentina in summer 2025")

## Core Principles

### 1. Write Complete, Context-Rich Memories
Don't be overly brief. Include relevant context that makes the memory useful:
- BAD: "Likes coffee"
- GOOD: "Prefers strong black coffee in the morning, usually has 2 cups before noon"
- BAD: "Has kids"
- GOOD: "Has two children: Emma (born 2018) and Jack (born 2021)"

### 2. Consolidate Related Information
Group facts about the same topic into a single comprehensive memory. Before adding a new memory, check if it should UPDATE an existing one instead:
- BAD: Three separate memories: "Has a dog", "Dog's name is Max", "Max is a golden retriever"
- GOOD: One memory: "Has a golden retriever named Max, adopted as a puppy in 2020, loves playing fetch"
- BAD: Separate memories for each family member's detail
- GOOD: One memory per family member with all their relevant details consolidated

### 3. Protect Essential Facts (Never Delete)
Some information is fundamental and should NEVER be deleted, only updated with more detail:
- Family member names, relationships, and birthdays
- Partner/spouse information
- Children's names and birth dates
- Core identity facts (profession, hometown, native language)
- Long-term health conditions or dietary restrictions (e.g., "Vegetarian since 2015", "Allergic to shellfish")
- Pet names and basic info

### 4. Actively Manage Memory Space
When near the limit ({warning_threshold}+ memories), prioritize keeping space:
- KEEP: Essential facts (family, identity), active goals, strong preferences
- CONSOLIDATE: Multiple related memories into one comprehensive entry
- REMOVE: Completed goals, outdated projects, stale context that no longer applies
- UPDATE rather than create new: If a memory about the same topic exists, update it with new info

## What to Memorize
- Family members: names, relationships, birthdays, and key facts about each
- Strong preferences that help personalize responses (with reasoning when known)
- Professional context: job, industry, tech stack, work style
- Ongoing projects or goals with relevant deadlines or context
- Corrections and clarifications the user makes about themselves
- Important life events and milestones

## What NOT to Memorize
- Temporary, one-off requests (e.g., "help me write this email")
- Information they're asking about (external facts, not about them)
- Sensitive credentials (passwords, API keys, financial account numbers)
- Highly personal medical details beyond dietary/allergy needs
- Trivial facts that don't aid personalization"""


def get_user_memories_prompt(user_id: str) -> str:
    """Build the user memories section for the system prompt.

    Args:
        user_id: The user ID to fetch memories for

    Returns:
        Formatted string with memory instructions and current memories
    """
    memories = db.list_memories(user_id)
    memory_count = len(memories)
    limit = Config.USER_MEMORY_LIMIT
    warning_threshold = Config.USER_MEMORY_WARNING_THRESHOLD

    # Build the prompt with current memories
    prompt_parts = [
        MEMORY_SYSTEM_PROMPT.format(warning_threshold=warning_threshold),
        f"\n\n## Current Memories ({memory_count}/{limit})",
    ]

    if memory_count >= warning_threshold:
        prompt_parts.append(
            "\n**WARNING**: Near memory limit! Consider consolidating or removing outdated memories."
        )

    if memories:
        prompt_parts.append("\n")
        for mem in memories:
            category_str = f"[{mem.category}]" if mem.category else ""
            created_date = mem.created_at.strftime("%Y-%m-%d")
            prompt_parts.append(
                f"- {category_str} {mem.content} (id: {mem.id}, created: {created_date})"
            )
    else:
        prompt_parts.append("\nNo memories stored yet.")

    return "\n".join(prompt_parts)


def get_force_tools_prompt(force_tools: list[str]) -> str:
    """Build a prompt instructing the LLM to use specific tools.

    Args:
        force_tools: List of tool names to force (e.g., ["web_search"])

    Returns:
        A formatted instruction string
    """
    tool_list = "\n".join(f"- {tool}" for tool in force_tools)
    return f"""
# IMPORTANT: Mandatory Tool Usage
Before responding to this query, you MUST use the following tools:
{tool_list}

Call each required tool first, then provide your response based on the results. Do not skip this step."""


def get_user_context(user_name: str | None = None) -> str:
    """Build user context for the system prompt based on configuration.

    Includes location and other contextual information that helps the assistant
    provide more relevant, personalized responses.

    Args:
        user_name: The user's name from JWT authentication

    Returns:
        User context string, or empty string if no context is configured.
    """
    context_parts: list[str] = []

    # User name context
    if user_name:
        context_parts.append(f"""## User
The user's name is {user_name}. Use it naturally when appropriate (greetings, personalized responses), but don't overuse it.""")

    # Location context
    location = Config.USER_LOCATION
    if location:
        context_parts.append(f"""## Location
The user is located in {location}. Use this to:
- Use appropriate measurement units (metric vs imperial) based on local conventions
- Prefer local currency when discussing prices or costs
- Recommend locally available retailers, services, or resources when relevant
- Consider local regulations, holidays, customs, and cultural context
- Use appropriate date/time formats for the locale
- When suggesting products, consider regional availability""")

    if not context_parts:
        return ""

    return "\n\n# User Context\n" + "\n\n".join(context_parts)


def get_system_prompt(
    with_tools: bool = True,
    force_tools: list[str] | None = None,
    user_name: str | None = None,
    user_id: str | None = None,
    custom_instructions: str | None = None,
) -> str:
    """Build the system prompt, optionally including tool instructions.

    Args:
        with_tools: Whether tools are available
        force_tools: List of tool names that must be used (e.g., ["web_search", "image_generation"])
        user_name: The user's name from JWT authentication
        user_id: The user's ID for memory retrieval
        custom_instructions: User-provided custom instructions for LLM behavior
    """
    date_context = f"\n\nCurrent date and time: {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    prompt = BASE_SYSTEM_PROMPT

    # Add user context if configured
    prompt += get_user_context(user_name)

    if with_tools and TOOLS:
        prompt += TOOLS_SYSTEM_PROMPT

    # Add custom instructions if provided
    if custom_instructions and custom_instructions.strip():
        prompt += "\n\n" + CUSTOM_INSTRUCTIONS_PROMPT.format(
            instructions=custom_instructions.strip()
        )

    # Add user memories if user_id is provided
    if user_id:
        prompt += "\n\n" + get_user_memories_prompt(user_id)

    # Add force tools instruction if specified
    if force_tools:
        prompt += get_force_tools_prompt(force_tools)

    return prompt + date_context


def extract_text_content(content: str | list[Any] | dict[str, Any]) -> str:
    """Extract text from message content, handling various formats from Gemini."""
    if isinstance(content, str):
        return content

    # Handle dict format (e.g., {'type': 'text', 'text': '...'})
    if isinstance(content, dict):
        if content.get("type") == "text":
            return str(content.get("text", ""))
        # If it has a 'text' key directly, use that
        if "text" in content:
            return str(content["text"])
        # Otherwise skip non-text content
        return ""

    # Handle list format from Gemini (e.g., [{'type': 'text', 'text': '...'}])
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict):
                # Extract text from dict, skip 'extras' and other metadata
                if part.get("type") == "text":
                    text_parts.append(str(part.get("text", "")))
                elif "text" in part and "type" not in part:
                    text_parts.append(str(part["text"]))
                # Skip parts with 'extras', 'signature', etc.
            elif isinstance(part, str):
                text_parts.append(part)
        return "".join(text_parts)

    return str(content)


def extract_thinking_and_text(
    content: str | list[Any] | dict[str, Any],
) -> tuple[str | None, str]:
    """Extract thinking content and regular text from message content.

    Gemini thinking models return content with parts that have 'thought': true.

    Args:
        content: The message content (string, dict, or list of parts)

    Returns:
        Tuple of (thinking_text, regular_text)
        - thinking_text: The model's reasoning/thinking (None if not present)
        - regular_text: The regular response text
    """
    if isinstance(content, str):
        return None, content

    # Handle dict format
    if isinstance(content, dict):
        # Check if this is a thought part (old format: {'thought': true, 'text': '...'})
        if content.get("thought"):
            return str(content.get("text", "")), ""
        # Check for thinking content (Gemini format: {'type': 'thinking', 'thinking': '...'})
        if content.get("type") == "thinking":
            return str(content.get("thinking", "")), ""
        if content.get("type") == "text":
            return None, str(content.get("text", ""))
        if "text" in content:
            return None, str(content["text"])
        return None, ""

    # Handle list format - separate thought parts from regular text parts
    if isinstance(content, list):
        thinking_parts = []
        text_parts = []
        for part in content:
            if isinstance(part, dict):
                # Check for thought content (old format: {'thought': true, 'text': '...'})
                if part.get("thought"):
                    thinking_parts.append(str(part.get("text", "")))
                # Check for thinking content (Gemini format: {'type': 'thinking', 'thinking': '...'})
                elif part.get("type") == "thinking":
                    thinking_parts.append(str(part.get("thinking", "")))
                elif part.get("type") == "text":
                    text_parts.append(str(part.get("text", "")))
                elif "text" in part and "type" not in part:
                    text_parts.append(str(part["text"]))
                # Skip parts with 'extras', 'signature', etc.
            elif isinstance(part, str):
                text_parts.append(part)

        thinking = "".join(thinking_parts) if thinking_parts else None
        text = "".join(text_parts)
        return thinking, text

    return None, str(content)


# Pattern to match metadata block: <!-- METADATA:\n{...}\n-->
METADATA_PATTERN = re.compile(
    r"<!--\s*METADATA:\s*\n(.*?)\n\s*-->",
    re.DOTALL | re.IGNORECASE,
)


# Pattern to match Gemini's tool call JSON format that sometimes leaks into response text
# This happens when the model outputs the tool call description as text alongside the actual tool call
# Format: {"action": "tool_name", "action_input": "..."} or {"action": "tool_name", "action_input": {...}}
# Note: Properly handles escaped quotes in string values. For object values, matches balanced braces
# up to 2 levels deep (sufficient for typical tool call artifacts like {"prompt": "..."}).
# The pattern is specific enough (requires "action" and "action_input" keys) to avoid false matches.
TOOL_CALL_JSON_PATTERN = re.compile(
    r'\n*\{\s*"action":\s*"(?:[^"\\]|\\.)+"\s*,\s*"action_input":\s*(?:"(?:[^"\\]|\\.)*"|\{(?:[^{}]|\{[^}]*\})*\})\s*\}',
    re.DOTALL,
)


def clean_tool_call_json(response: str) -> str:
    """Remove tool call JSON artifacts that sometimes leak into LLM response text.

    Gemini may output tool call descriptions as text alongside actual function calls.
    This removes those JSON blocks to keep only natural language content.

    Args:
        response: The LLM response text

    Returns:
        Response with tool call JSON removed
    """
    return TOOL_CALL_JSON_PATTERN.sub("", response).strip()


def _find_json_object_end(text: str, start_pos: int) -> int | None:
    """Find the end position of a complete JSON object starting at start_pos.

    Returns the position after the closing brace, or None if not found.
    """
    brace_count = 0
    in_string = False
    escape_next = False

    for i in range(start_pos, len(text)):
        char = text[i]

        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            brace_count += 1
        elif char == "}":
            brace_count -= 1
            if brace_count == 0:
                return i + 1

    return None


def extract_metadata_from_response(response: str) -> tuple[str, dict[str, Any]]:
    """Extract metadata from LLM response and return clean content.

    The LLM is instructed to append metadata at the end of responses in the format:
    <!-- METADATA:
    {"sources": [...]}
    -->

    However, sometimes the LLM outputs plain JSON without the HTML comment wrapper,
    or outputs it in both formats. This function prefers the HTML comment format,
    but removes both if they both exist.

    Also removes any tool call JSON artifacts that leaked into the response.

    Args:
        response: The raw LLM response text

    Returns:
        Tuple of (clean_content, metadata_dict)
        - clean_content: Response with metadata block and tool call JSON removed
        - metadata_dict: Parsed metadata (empty dict if none found or parse error)
    """
    response = clean_tool_call_json(response)
    metadata: dict[str, Any] = {}
    clean_content = response

    # Try HTML comment format first (preferred format)
    match = METADATA_PATTERN.search(clean_content)
    if match:
        try:
            metadata = json.loads(match.group(1).strip())
            clean_content = clean_content[: match.start()].rstrip()
        except (json.JSONDecodeError, AttributeError):
            # If parsing fails, continue to check for plain JSON
            pass

    # Also check for plain JSON metadata and remove it (even if we already found HTML comment)
    # This ensures we remove both if the LLM outputs metadata in both formats
    # Search backwards for JSON objects that might contain metadata
    # We need to find the outermost object, so we search from the end
    search_start = len(clean_content)
    while True:
        # Find the last opening brace before our search start
        last_brace = clean_content.rfind("{", 0, search_start)
        if last_brace == -1:
            break

        end_pos = _find_json_object_end(clean_content, last_brace)
        if end_pos:
            try:
                parsed = json.loads(clean_content[last_brace:end_pos])
                if "sources" in parsed or "generated_images" in parsed:
                    # Only use this metadata if we didn't already get it from HTML comment
                    if not metadata:
                        metadata = parsed
                    # Remove the JSON from response regardless
                    clean_content = clean_content[:last_brace].rstrip()
                    break
            except (json.JSONDecodeError, ValueError):
                pass

        # Continue searching backwards from before this brace
        search_start = last_brace

    return clean_content.rstrip(), metadata


class AgentState(TypedDict):
    """State for the chat agent."""

    messages: Annotated[list[BaseMessage], add_messages]


def create_chat_model(
    model_name: str, with_tools: bool = True, include_thoughts: bool = False
) -> ChatGoogleGenerativeAI:
    """Create a Gemini chat model, optionally with tools bound.

    Args:
        model_name: The Gemini model to use
        with_tools: Whether to bind tools to the model
        include_thoughts: Whether to include thinking/reasoning summaries in responses
    """
    model = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=Config.GEMINI_API_KEY,
        temperature=Config.GEMINI_DEFAULT_TEMPERATURE,
        convert_system_message_to_human=True,
        include_thoughts=include_thoughts,
    )

    if with_tools and TOOLS:
        return model.bind_tools(TOOLS)  # type: ignore[return-value]

    return model


def should_continue(state: AgentState) -> Literal["tools", "end"]:
    """Decide whether to continue to tools or end the conversation."""
    messages = state["messages"]
    last_message = messages[-1]

    # If the last message has tool calls, continue to tools
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"

    return "end"


def chat_node(state: AgentState, model: ChatGoogleGenerativeAI) -> dict[str, list[BaseMessage]]:
    """Process messages and generate a response."""
    messages = state["messages"]
    message_count = len(messages)
    logger.debug(
        "Invoking LLM",
        extra={
            "message_count": message_count,
            "model": model.model_name if hasattr(model, "model_name") else "unknown",
        },
    )
    response = model.invoke(messages)

    # Log tool calls if present
    if isinstance(response, AIMessage) and response.tool_calls:
        tool_names = [tc.get("name", "unknown") for tc in response.tool_calls]
        logger.info(
            "LLM requested tool calls",
            extra={"tool_calls": tool_names, "count": len(response.tool_calls)},
        )
    else:
        logger.debug("LLM response received", extra={"has_content": bool(response.content)})

    # Log usage metadata if available
    # Note: usage_metadata is a direct attribute, not in response_metadata
    if isinstance(response, AIMessage):
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage = response.usage_metadata
            logger.debug(
                "Usage metadata captured",
                extra={
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
            )
        else:
            logger.debug("No usage_metadata attribute found on AIMessage")

    return {"messages": [response]}


def create_chat_graph(
    model_name: str, with_tools: bool = True, include_thoughts: bool = False
) -> StateGraph[AgentState]:
    """Create a chat graph with optional tool support.

    Args:
        model_name: The Gemini model to use
        with_tools: Whether to bind tools to the model
        include_thoughts: Whether to include thinking/reasoning summaries
    """
    model = create_chat_model(model_name, with_tools=with_tools, include_thoughts=include_thoughts)

    # Define the graph
    graph: StateGraph[AgentState] = StateGraph(AgentState)

    # Add the chat node
    graph.add_node("chat", lambda state: chat_node(state, model))

    if with_tools and TOOLS:
        # Add tool node with stripping of large results
        tool_node = create_tool_node(TOOLS)
        graph.add_node("tools", tool_node)

        # Set entry point
        graph.set_entry_point("chat")

        # Add conditional edge based on whether to use tools
        graph.add_conditional_edges("chat", should_continue, {"tools": "tools", "end": END})

        # After tools, go back to chat
        graph.add_edge("tools", "chat")
    else:
        # Simple graph without tools
        graph.set_entry_point("chat")
        graph.add_edge("chat", END)

    return graph


class ChatAgent:
    """Agent for handling chat conversations with tool support."""

    def __init__(
        self,
        model_name: str = Config.DEFAULT_MODEL,
        with_tools: bool = True,
        include_thoughts: bool = False,
    ) -> None:
        self.model_name = model_name
        self.with_tools = with_tools
        self.include_thoughts = include_thoughts
        logger.debug(
            "Creating ChatAgent",
            extra={
                "model": model_name,
                "with_tools": with_tools,
                "include_thoughts": include_thoughts,
            },
        )
        self.graph = create_chat_graph(
            model_name, with_tools=with_tools, include_thoughts=include_thoughts
        ).compile()

    def _build_message_content(
        self, text: str, files: list[dict[str, Any]] | None = None
    ) -> str | list[str | dict[Any, Any]]:
        """Build message content for LangChain.

        Args:
            text: Plain text message
            files: Optional list of file attachments

        Returns:
            For text-only: the string
            For multimodal: list of content blocks for LangChain
        """
        if not files:
            return text

        # Build multimodal content blocks
        blocks: list[str | dict[Any, Any]] = []

        # Add text block if present
        if text:
            blocks.append({"type": "text", "text": text})

        # Add file blocks
        for file in files:
            mime_type = file.get("type", "application/octet-stream")
            data = file.get("data", "")

            if mime_type.startswith("image/"):
                # Image block for Gemini
                blocks.append(
                    {
                        "type": "image",
                        "base64": data,
                        "mime_type": mime_type,
                    }
                )
            elif mime_type == "application/pdf":
                # PDF - Gemini supports inline PDFs
                blocks.append(
                    {
                        "type": "image",  # LangChain uses image type for PDFs too
                        "base64": data,
                        "mime_type": mime_type,
                    }
                )
            else:
                # Text files - include as text block
                try:
                    import base64
                    import binascii

                    decoded = base64.b64decode(data).decode("utf-8")
                    file_name = file.get("name", "file")
                    blocks.append(
                        {
                            "type": "text",
                            "text": f"\n--- Content of {file_name} ---\n{decoded}\n--- End of {file_name} ---\n",
                        }
                    )
                except (binascii.Error, UnicodeDecodeError):
                    # If decoding fails (invalid base64 or non-UTF-8), skip the file
                    pass

        return blocks if blocks else text

    def _build_messages(
        self,
        text: str,
        files: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        force_tools: list[str] | None = None,
        user_name: str | None = None,
        user_id: str | None = None,
        custom_instructions: str | None = None,
    ) -> list[BaseMessage]:
        """Build the messages list from history and user message."""
        messages: list[BaseMessage] = []

        # Always add system prompt (with tool instructions if tools are enabled)
        messages.append(
            SystemMessage(
                content=get_system_prompt(
                    self.with_tools,
                    force_tools=force_tools,
                    user_name=user_name,
                    user_id=user_id,
                    custom_instructions=custom_instructions,
                )
            )
        )

        if history:
            for msg in history:
                if msg["role"] == "user":
                    content = self._build_message_content(msg["content"], msg.get("files"))
                    messages.append(HumanMessage(content=content))
                elif msg["role"] == "assistant":
                    # Assistant messages are always text
                    messages.append(AIMessage(content=msg["content"]))

        # Add the current user message
        content = self._build_message_content(text, files)
        messages.append(HumanMessage(content=content))

        return messages

    def chat_batch(
        self,
        text: str,
        files: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        force_tools: list[str] | None = None,
        user_name: str | None = None,
        user_id: str | None = None,
        custom_instructions: str | None = None,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        """
        Send a message and get a response (non-streaming).

        Args:
            text: The user's message text
            files: Optional list of file attachments
            history: Optional list of previous messages with 'role', 'content', and 'files' keys
            force_tools: Optional list of tool names that must be used
            user_name: Optional user name from JWT for personalized responses
            user_id: Optional user ID for memory retrieval and injection
            custom_instructions: Optional user-provided custom instructions for LLM behavior

        Returns:
            Tuple of (response_text, tool_results, usage_info)
        """
        messages = self._build_messages(
            text,
            files,
            history,
            force_tools=force_tools,
            user_name=user_name,
            user_id=user_id,
            custom_instructions=custom_instructions,
        )
        logger.debug(
            "Starting chat_batch",
            extra={
                "model": self.model_name,
                "message_length": len(text),
                "has_files": bool(files),
                "file_count": len(files) if files else 0,
                "force_tools": force_tools,
                "total_messages": len(messages),
            },
        )

        # Run the graph
        result = self.graph.invoke(cast(Any, {"messages": messages}))

        # Extract response (last AI message with actual content)
        response_text = ""
        for msg in reversed(result["messages"]):
            if isinstance(msg, AIMessage):
                text_content = extract_text_content(msg.content)
                if msg.tool_calls and not text_content:
                    continue
                text_content = clean_tool_call_json(text_content)
                if text_content:
                    response_text = text_content
                    break

        # Extract tool results
        tool_results: list[dict[str, Any]] = []
        for msg in result["messages"]:
            if isinstance(msg, ToolMessage):
                tool_results.append({"type": "tool", "content": msg.content})

        if tool_results:
            logger.info("Tool results captured", extra={"tool_result_count": len(tool_results)})

        # Aggregate usage metadata from all AIMessages
        total_input_tokens = 0
        total_output_tokens = 0
        for msg in result["messages"]:
            if isinstance(msg, AIMessage):
                if hasattr(msg, "usage_metadata") and msg.usage_metadata:
                    usage = msg.usage_metadata
                    if isinstance(usage, dict):
                        input_tokens = usage.get("input_tokens", 0)
                        output_tokens = usage.get("output_tokens", 0)
                        if input_tokens > 0 or output_tokens > 0:
                            total_input_tokens += input_tokens
                            total_output_tokens += output_tokens
                            logger.debug(
                                "Found usage metadata in AIMessage",
                                extra={
                                    "input_tokens": input_tokens,
                                    "output_tokens": output_tokens,
                                },
                            )

        usage_info = {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
        }

        if total_input_tokens > 0 or total_output_tokens > 0:
            logger.debug(
                "Usage metadata aggregated",
                extra={
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                },
            )

        return response_text, tool_results, usage_info

    def stream_chat(
        self,
        text: str,
        files: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        force_tools: list[str] | None = None,
        user_name: str | None = None,
        user_id: str | None = None,
        custom_instructions: str | None = None,
    ) -> Generator[str | tuple[str, dict[str, Any], list[dict[str, Any]], dict[str, Any]]]:
        """
        Stream response tokens using LangGraph's stream method.

        Args:
            text: The user's message text
            files: Optional list of file attachments
            history: Optional list of previous messages with 'role', 'content', and 'files' keys
            force_tools: Optional list of tool names that must be used
            user_name: Optional user name from JWT for personalized responses
            user_id: Optional user ID for memory retrieval and injection
            custom_instructions: Optional user-provided custom instructions for LLM behavior

        Yields:
            - str: Text tokens for streaming display
            - tuple: Final (content, metadata, tool_results, usage_info) where:
              - content: Clean response text (metadata stripped)
              - metadata: Extracted metadata dict (sources, generated_images, etc.)
              - tool_results: List of tool message dicts for server-side processing
              - usage_info: Dict with 'input_tokens' and 'output_tokens'
        """
        messages = self._build_messages(
            text,
            files,
            history,
            force_tools=force_tools,
            user_name=user_name,
            user_id=user_id,
            custom_instructions=custom_instructions,
        )

        # Accumulate full response to extract metadata at the end
        full_response = ""
        # Buffer to detect metadata marker - we hold back chars until we're sure
        # they're not part of the metadata marker
        buffer = ""
        metadata_marker = "<!-- METADATA:"
        in_metadata = False
        # Capture tool results for server-side extraction (e.g., generated images)
        tool_results: list[dict[str, Any]] = []
        # Track token counts as we stream (memory efficient - only store numbers, not message objects)
        total_input_tokens = 0
        total_output_tokens = 0
        chunk_count = 0

        # Stream the graph execution with messages mode for token-level streaming
        for event in self.graph.stream(
            cast(Any, {"messages": messages}),
            stream_mode="messages",
        ):
            # event is a tuple of (message_chunk, metadata) in messages mode
            if isinstance(event, tuple) and len(event) >= 1:
                message_chunk = event[0]

                # Capture tool messages (results from tool execution)
                if isinstance(message_chunk, ToolMessage):
                    tool_results.append(
                        {
                            "type": "tool",
                            "content": message_chunk.content,
                        }
                    )
                    continue

                # Only yield content from AI message chunks (not tool calls or tool results)
                if isinstance(message_chunk, AIMessageChunk):
                    # Extract usage metadata immediately (don't store the message object)
                    chunk_count += 1
                    if hasattr(message_chunk, "usage_metadata") and message_chunk.usage_metadata:
                        usage = message_chunk.usage_metadata
                        if isinstance(usage, dict):
                            input_tokens = usage.get("input_tokens", 0)
                            output_tokens = usage.get("output_tokens", 0)
                            if input_tokens > 0 or output_tokens > 0:
                                total_input_tokens += input_tokens
                                total_output_tokens += output_tokens
                                logger.debug(
                                    "Found usage in chunk",
                                    extra={
                                        "input_tokens": input_tokens,
                                        "output_tokens": output_tokens,
                                    },
                                )

                    # Skip chunks that are only tool calls (no text content)
                    if message_chunk.tool_calls or message_chunk.tool_call_chunks:
                        continue
                    if message_chunk.content:
                        content = extract_text_content(message_chunk.content)
                        if content:
                            full_response += content

                            # If we've detected metadata, don't yield anything more
                            if in_metadata:
                                continue

                            # Add to buffer and check for metadata marker
                            buffer += content

                            # Check if buffer contains the start of metadata (HTML comment format)
                            if metadata_marker in buffer:
                                # Yield everything before the marker
                                marker_pos = buffer.find(metadata_marker)
                                if marker_pos > 0:
                                    yield buffer[:marker_pos].rstrip()
                                in_metadata = True
                                buffer = ""
                            elif len(buffer) > len(metadata_marker):
                                # Buffer is longer than marker, safe to yield the excess
                                safe_length = len(buffer) - len(metadata_marker)
                                yield buffer[:safe_length]
                                buffer = buffer[safe_length:]

        # Yield any remaining buffer that's not metadata
        if buffer and not in_metadata:
            # Final check - might end with partial marker or JSON
            clean, _ = extract_metadata_from_response(buffer)
            if clean and clean.strip():
                yield clean

        # Extract metadata and yield final tuple
        clean_content, metadata = extract_metadata_from_response(full_response)

        # Log a warning if we didn't find any usage metadata (should be rare)
        if total_input_tokens == 0 and total_output_tokens == 0 and chunk_count > 0:
            logger.warning(
                "No usage metadata found in streaming chunks",
                extra={
                    "chunk_count": chunk_count,
                    "note": "This is unusual - Gemini streaming chunks typically include usage_metadata. Cost tracking may be inaccurate for this request.",
                },
            )

        usage_info = {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
        }

        if total_input_tokens > 0 or total_output_tokens > 0:
            logger.debug(
                "Usage metadata aggregated from streaming chunks",
                extra={
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "chunk_count": chunk_count,
                },
            )

        # Final yield: (content, metadata, tool_results, usage_info) for server processing
        yield (clean_content, metadata, tool_results, usage_info)

    def stream_chat_events(
        self,
        text: str,
        files: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        force_tools: list[str] | None = None,
        user_name: str | None = None,
        user_id: str | None = None,
        custom_instructions: str | None = None,
    ) -> Generator[dict[str, Any]]:
        """Stream response events including thinking, tool calls, and tokens.

        This method yields structured events that can be sent to the frontend.
        It requires include_thoughts=True on the ChatAgent to receive thinking content.

        Args:
            text: The user's message text
            files: Optional list of file attachments
            history: Optional list of previous messages with 'role', 'content', and 'files' keys
            force_tools: Optional list of tool names that must be used
            user_name: Optional user name from JWT for personalized responses
            user_id: Optional user ID for memory retrieval and injection
            custom_instructions: Optional user-provided custom instructions for LLM behavior

        Yields:
            Events as dicts with 'type' field:
            - {"type": "thinking", "text": "..."} - Model's reasoning/thinking text
            - {"type": "tool_start", "tool": "tool_name"} - Tool execution starting
            - {"type": "tool_end", "tool": "tool_name"} - Tool execution finished
            - {"type": "token", "text": "..."} - Text token for streaming display
            - {"type": "final", "content": "...", "metadata": {...}, "tool_results": [...], "usage_info": {...}}
        """
        messages = self._build_messages(
            text,
            files,
            history,
            force_tools=force_tools,
            user_name=user_name,
            user_id=user_id,
            custom_instructions=custom_instructions,
        )

        # Accumulate full response to extract metadata at the end
        full_response = ""
        # Buffer to detect metadata marker
        buffer = ""
        metadata_marker = "<!-- METADATA:"
        in_metadata = False
        # Capture tool results for server-side extraction
        tool_results: list[dict[str, Any]] = []
        # Track token counts
        total_input_tokens = 0
        total_output_tokens = 0
        chunk_count = 0
        # Track active tool calls to detect when a tool is being executed
        pending_tool_calls: set[str] = set()
        # Accumulate thinking text across chunks
        accumulated_thinking = ""

        # Stream the graph execution with messages mode for token-level streaming
        # Wrapped in try-except to handle executor shutdown gracefully
        try:
            for event in self.graph.stream(
                cast(Any, {"messages": messages}),
                stream_mode="messages",
            ):
                if isinstance(event, tuple) and len(event) >= 1:
                    message_chunk = event[0]

                # Capture tool messages (results from tool execution)
                if isinstance(message_chunk, ToolMessage):
                    tool_results.append(
                        {
                            "type": "tool",
                            "content": message_chunk.content,
                        }
                    )
                    # Signal tool execution ended
                    tool_name = getattr(message_chunk, "name", None)
                    if tool_name and tool_name in pending_tool_calls:
                        pending_tool_calls.discard(tool_name)
                        yield {"type": "tool_end", "tool": tool_name}
                    continue

                # Process AI message chunks
                if isinstance(message_chunk, AIMessageChunk):
                    # Extract usage metadata immediately
                    chunk_count += 1
                    if hasattr(message_chunk, "usage_metadata") and message_chunk.usage_metadata:
                        usage = message_chunk.usage_metadata
                        if isinstance(usage, dict):
                            input_tokens = usage.get("input_tokens", 0)
                            output_tokens = usage.get("output_tokens", 0)
                            if input_tokens > 0 or output_tokens > 0:
                                total_input_tokens += input_tokens
                                total_output_tokens += output_tokens

                    # Check for tool calls starting
                    if message_chunk.tool_calls or message_chunk.tool_call_chunks:
                        # Get tool names and args from tool_calls or tool_call_chunks
                        # tool_calls has complete args as dict, tool_call_chunks has partial args as string
                        tool_infos: list[tuple[str, dict[str, Any]]] = []
                        if message_chunk.tool_calls:
                            for tool_call in message_chunk.tool_calls:
                                tc_name = tool_call.get("name")
                                tc_args = tool_call.get("args", {})
                                if tc_name is not None and isinstance(tc_args, dict):
                                    tool_infos.append((tc_name, tc_args))
                        elif message_chunk.tool_call_chunks:
                            # tool_call_chunks have args as string (partial JSON)
                            # We can only get the tool name here, not args
                            for tc_chunk in message_chunk.tool_call_chunks:
                                chunk_name = tc_chunk.get("name")
                                if chunk_name is not None:
                                    # Empty args dict since chunks don't have complete args
                                    tool_infos.append((chunk_name, {}))

                        for tool_name, tool_args in tool_infos:
                            if tool_name not in pending_tool_calls:
                                pending_tool_calls.add(tool_name)
                                # Include relevant detail based on tool type
                                tool_event: dict[str, Any] = {
                                    "type": "tool_start",
                                    "tool": tool_name,
                                }
                                # Add tool-specific detail (only available from complete tool_calls)
                                if tool_name == "web_search" and "query" in tool_args:
                                    tool_event["detail"] = tool_args["query"]
                                elif tool_name == "fetch_url" and "url" in tool_args:
                                    tool_event["detail"] = tool_args["url"]
                                elif tool_name == "generate_image" and "prompt" in tool_args:
                                    tool_event["detail"] = tool_args["prompt"]
                                elif tool_name == "execute_code" and "code" in tool_args:
                                    # Show first line of code as detail
                                    code_preview = tool_args["code"].split("\n")[0][:50]
                                    tool_event["detail"] = code_preview
                                yield tool_event
                        continue

                    # Process content
                    if message_chunk.content:
                        # Debug: Log raw content structure occasionally
                        if chunk_count <= 5:
                            content_type = type(message_chunk.content).__name__
                            content_preview = str(message_chunk.content)[:200]
                            logger.debug(
                                "Raw chunk content",
                                extra={
                                    "chunk_number": chunk_count,
                                    "content_type": content_type,
                                    "content_preview": content_preview,
                                },
                            )

                        # Extract thinking and text separately
                        thinking, text_content = extract_thinking_and_text(message_chunk.content)

                        # Debug: Log the extracted content
                        if thinking:
                            logger.debug(
                                "Extracted thinking content",
                                extra={
                                    "thinking_length": len(thinking),
                                    "thinking_preview": thinking[:100]
                                    if len(thinking) > 100
                                    else thinking,
                                },
                            )

                        # Accumulate thinking content and yield updates
                        if thinking:
                            accumulated_thinking += thinking
                            yield {"type": "thinking", "text": accumulated_thinking}

                        # Process regular text content
                        if text_content:
                            full_response += text_content

                            # If we've detected metadata, don't yield anything more
                            if in_metadata:
                                continue

                            # Add to buffer and check for metadata marker
                            buffer += text_content

                            # Check if buffer contains the start of metadata
                            if metadata_marker in buffer:
                                marker_pos = buffer.find(metadata_marker)
                                if marker_pos > 0:
                                    yield {"type": "token", "text": buffer[:marker_pos].rstrip()}
                                in_metadata = True
                                buffer = ""
                            elif len(buffer) > len(metadata_marker):
                                safe_length = len(buffer) - len(metadata_marker)
                                yield {"type": "token", "text": buffer[:safe_length]}
                                buffer = buffer[safe_length:]
        except RuntimeError as e:
            # Handle executor shutdown gracefully (e.g., during server restart)
            # Python's ThreadPoolExecutor raises generic RuntimeError with specific messages
            # when submit() is called after shutdown - there's no specific exception class
            error_msg = str(e).lower()
            if "cannot schedule new futures" in error_msg and "shutdown" in error_msg:
                logger.warning(
                    "Streaming interrupted by executor shutdown (likely server restart)",
                    extra={
                        "accumulated_response_length": len(full_response),
                        "has_tool_results": bool(tool_results),
                    },
                )
                # Continue to yield accumulated content and final event
            else:
                # Re-raise other RuntimeErrors
                raise

        # Yield any remaining buffer that's not metadata
        if buffer and not in_metadata:
            clean, _ = extract_metadata_from_response(buffer)
            if clean and clean.strip():
                yield {"type": "token", "text": clean}

        # Extract metadata
        clean_content, metadata = extract_metadata_from_response(full_response)

        usage_info = {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
        }

        # Final yield with all accumulated data
        yield {
            "type": "final",
            "content": clean_content,
            "metadata": metadata,
            "tool_results": tool_results,
            "usage_info": usage_info,
        }


def generate_title(user_message: str, assistant_response: str) -> str:
    """
    Generate a concise title for a conversation using Gemini.

    Args:
        user_message: The first user message
        assistant_response: The assistant's response

    Returns:
        A short, descriptive title (max ~50 chars)
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
The title should capture the main topic or intent.
Do NOT use quotes around the title.
Do NOT include prefixes like "Title:" or "Topic:".
Just output the title text directly.

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
        final_title = title or user_message[: Config.TITLE_FALLBACK_LENGTH]
        logger.debug("Title generated", extra={"title": final_title})
        return final_title
    except (GoogleAPIError, ValueError, TimeoutError) as e:
        # Fallback to truncated message on API or parsing errors
        logger.warning("Title generation failed, using fallback", extra={"error": str(e)})
        fallback_len = Config.TITLE_FALLBACK_LENGTH
        return user_message[:fallback_len] + ("..." if len(user_message) > fallback_len else "")
