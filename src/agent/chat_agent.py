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
    - ChatAgent: Main class with chat() and chat_with_state() methods
    - SYSTEM_PROMPT: Instructions for when to use web tools
    - extract_text_content(): Helper to handle Gemini's varied response formats:
        * str: Plain text responses (most common)
        * dict: Structured content like {'type': 'text', 'text': '...'}
        * list: Multi-part responses with tool calls, e.g.,
          [{'type': 'text', 'text': '...'}, {'type': 'tool_use', ...}]
          Also includes metadata like 'extras', 'signature' which are skipped
"""

from collections.abc import Generator
from datetime import datetime
from typing import Annotated, Any, Literal, TypedDict, cast

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
from langgraph.prebuilt import ToolNode

from src.agent.tools import TOOLS
from src.config import Config

# Type for streaming events
StreamEvent = dict[str, Any]  # {"type": "token"|"thinking"|"tool_call"|"tool_result", ...}

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
You have access to web tools for real-time information:
- **web_search**: Search the web for current information, news, prices, events, etc.
- **fetch_url**: Fetch and read the content of a specific web page.

# When to Use Tools
ALWAYS use web_search first when the user asks about:
- Current events, news, "what happened today/recently"
- Real-time data: stock prices, crypto, weather, sports scores
- Recent releases, updates, or announcements
- Anything that might have changed since your training cutoff
- Facts you're uncertain about (verify before answering)

After searching, use fetch_url to read specific pages for more details if needed.
Do NOT rely on training data for time-sensitive information.

# Knowledge Cutoff
Your training data has a cutoff date. For anything after that, use web_search.
When citing information from searches, mention the source."""


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


def get_system_prompt(with_tools: bool = True, force_tools: list[str] | None = None) -> str:
    """Build the system prompt, optionally including tool instructions.

    Args:
        with_tools: Whether tools are available
        force_tools: List of tool names that must be used (e.g., ["web_search", "image_generation"])
    """
    date_context = f"\n\nCurrent date and time: {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    prompt = BASE_SYSTEM_PROMPT
    if with_tools and TOOLS:
        prompt += TOOLS_SYSTEM_PROMPT

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


class AgentState(TypedDict):
    """State for the chat agent."""

    messages: Annotated[list[BaseMessage], add_messages]


def create_chat_model(
    model_name: str, with_tools: bool = True, include_thinking: bool = False
) -> ChatGoogleGenerativeAI:
    """Create a Gemini chat model, optionally with tools bound.

    Args:
        model_name: The Gemini model to use
        with_tools: Whether to bind tools to the model
        include_thinking: Whether to include thinking/reasoning in responses
    """
    model = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=Config.GEMINI_API_KEY,
        temperature=1.0,  # Recommended default for Gemini 3
        convert_system_message_to_human=True,
        # Thinking configuration for Gemini 3 models
        thinking_level="medium" if include_thinking else None,
        include_thoughts=include_thinking,
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
    response = model.invoke(messages)
    return {"messages": [response]}


def create_chat_graph(
    model_name: str, with_tools: bool = True, include_thinking: bool = False
) -> StateGraph[AgentState]:
    """Create a chat graph with optional tool support."""
    model = create_chat_model(model_name, with_tools=with_tools, include_thinking=include_thinking)

    # Define the graph
    graph: StateGraph[AgentState] = StateGraph(AgentState)

    # Add the chat node
    graph.add_node("chat", lambda state: chat_node(state, model))

    if with_tools and TOOLS:
        # Add tool node
        tool_node = ToolNode(TOOLS)
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


def extract_thinking_content(content: str | list[Any] | dict[str, Any]) -> str | None:
    """Extract thinking content from message, if present.

    Gemini returns thinking as: {'type': 'thinking', 'thinking': '...'}
    """
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "thinking":
                return str(part.get("thinking", ""))
    return None


class ChatAgent:
    """Agent for handling chat conversations with tool support."""

    def __init__(
        self,
        model_name: str = Config.DEFAULT_MODEL,
        with_tools: bool = True,
        include_thinking: bool = False,
    ) -> None:
        self.model_name = model_name
        self.with_tools = with_tools
        self.include_thinking = include_thinking
        # Create graph with thinking support if requested
        self.graph = create_chat_graph(
            model_name, with_tools=with_tools, include_thinking=include_thinking
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

                    decoded = base64.b64decode(data).decode("utf-8")
                    file_name = file.get("name", "file")
                    blocks.append(
                        {
                            "type": "text",
                            "text": f"\n--- Content of {file_name} ---\n{decoded}\n--- End of {file_name} ---\n",
                        }
                    )
                except Exception:
                    # If decoding fails, skip the file
                    pass

        return blocks if blocks else text

    def _build_messages(
        self,
        text: str,
        files: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        force_tools: list[str] | None = None,
    ) -> list[BaseMessage]:
        """Build the messages list from history and user message."""
        messages: list[BaseMessage] = []

        # Always add system prompt (with tool instructions if tools are enabled)
        messages.append(
            SystemMessage(content=get_system_prompt(self.with_tools, force_tools=force_tools))
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

    def chat(
        self,
        user_message: str,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """
        Send a message and get a response.

        Args:
            user_message: The user's message
            history: Optional list of previous messages with 'role' and 'content' keys

        Returns:
            The assistant's response text
        """
        messages = self._build_messages(user_message, history)

        # Run the graph
        result = self.graph.invoke(cast(Any, {"messages": messages}))

        # Extract the assistant's response (last AI message without tool calls)
        response_text = ""
        for msg in reversed(result["messages"]):
            if isinstance(msg, AIMessage):
                # Skip messages that only have tool calls
                if msg.tool_calls and not extract_text_content(msg.content):
                    continue
                response_text = extract_text_content(msg.content)
                break

        return response_text

    def stream_chat(
        self,
        text: str,
        files: list[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        force_tools: list[str] | None = None,
    ) -> Generator[StreamEvent, None, None]:
        """
        Stream response events using LangGraph's stream method.

        Args:
            text: The user's message text
            files: Optional list of file attachments
            history: Optional list of previous messages with 'role', 'content', and 'files' keys
            force_tools: Optional list of tool names that must be used

        Yields:
            StreamEvent dicts with types: 'token', 'thinking', 'tool_call', 'tool_result'
        """
        messages = self._build_messages(text, files, history, force_tools=force_tools)

        # Track tool calls and thinking we've already emitted to avoid duplicates
        emitted_tool_calls: set[str] = set()
        emitted_thinking = False

        for event in self.graph.stream(
            cast(Any, {"messages": messages}),
            stream_mode="messages",
        ):
            # event is a tuple of (message_chunk, metadata) in messages mode
            if isinstance(event, tuple) and len(event) >= 1:
                message_chunk = event[0]

                # Handle AI message chunks (thinking, text tokens and tool calls)
                if isinstance(message_chunk, AIMessageChunk):
                    # Emit tool calls
                    if message_chunk.tool_calls:
                        for tool_call in message_chunk.tool_calls:
                            tool_call_id = tool_call.get("id", "")
                            if tool_call_id and tool_call_id not in emitted_tool_calls:
                                emitted_tool_calls.add(tool_call_id)
                                yield {
                                    "type": "tool_call",
                                    "id": tool_call_id,
                                    "name": tool_call.get("name", ""),
                                    "args": tool_call.get("args", {}),
                                }

                    # Handle content (may include thinking and text)
                    if message_chunk.content and not message_chunk.tool_calls:
                        content = message_chunk.content

                        # Handle list content (thinking and text parts from Gemini)
                        if isinstance(content, list):
                            for part in content:
                                if isinstance(part, dict):
                                    # Emit thinking content (only once)
                                    if part.get("type") == "thinking" and not emitted_thinking:
                                        thinking_text = part.get("thinking", "")
                                        # Ensure thinking_text is a string
                                        if thinking_text and isinstance(thinking_text, str):
                                            yield {
                                                "type": "thinking",
                                                "content": thinking_text,
                                            }
                                            emitted_thinking = True
                                    # Emit text content
                                    elif part.get("type") == "text":
                                        text_content = part.get("text", "")
                                        if text_content:
                                            yield {"type": "token", "text": text_content}
                        else:
                            # Simple string content
                            text_content = extract_text_content(content)
                            if text_content:
                                yield {"type": "token", "text": text_content}

                # Handle tool results
                elif isinstance(message_chunk, ToolMessage):
                    content = str(message_chunk.content)
                    # Truncate long results, but preserve JSON structure if possible
                    max_length = Config.MAX_TOOL_RESULT_LENGTH
                    if len(content) > max_length:
                        # Try to truncate at a safe point (end of a JSON object/array)
                        truncated = content[:max_length]
                        # If it looks like JSON, try to close it properly
                        if truncated.strip().startswith(("{", "[")):
                            # Count open/close braces to see if we can close it
                            open_braces = truncated.count("{") - truncated.count("}")
                            open_brackets = truncated.count("[") - truncated.count("]")
                            # Try to close JSON structure
                            if open_braces > 0 or open_brackets > 0:
                                # Remove trailing incomplete content
                                last_comma = truncated.rfind(",")
                                last_brace = max(truncated.rfind("{"), truncated.rfind("["))
                                if last_comma > last_brace:
                                    truncated = truncated[:last_comma].rstrip()
                                # Add closing braces
                                truncated += "}" * open_braces + "]" * open_brackets
                                truncated += '\n\n... (truncated)'
                            else:
                                truncated += '\n\n... (truncated)'
                        else:
                            truncated += '\n\n... (truncated)'
                        content = truncated
                    
                    yield {
                        "type": "tool_result",
                        "tool_call_id": message_chunk.tool_call_id,
                        "content": content,
                    }

    def chat_with_state(
        self,
        text: str,
        files: list[dict[str, Any]] | None = None,
        previous_state: dict[str, Any] | None = None,
        force_tools: list[str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """
        Chat with persistent state for multi-turn agent workflows.

        Args:
            text: The user's message text
            files: Optional list of file attachments
            previous_state: Optional previous agent state
            force_tools: Optional list of tool names that must be used

        Returns:
            Tuple of (response text, new state for persistence)
        """
        # Restore previous messages or start fresh
        messages: list[BaseMessage] = []

        # Always add system prompt (with tool instructions if tools are enabled)
        messages.append(
            SystemMessage(content=get_system_prompt(self.with_tools, force_tools=force_tools))
        )

        if previous_state and "messages" in previous_state:
            for msg_data in previous_state["messages"]:
                if msg_data["type"] == "human":
                    messages.append(HumanMessage(content=msg_data["content"]))
                elif msg_data["type"] == "ai":
                    messages.append(AIMessage(content=msg_data["content"]))
                elif msg_data["type"] == "tool":
                    messages.append(
                        ToolMessage(
                            content=msg_data["content"],
                            tool_call_id=msg_data.get("tool_call_id", ""),
                        )
                    )

        # Add the current user message (with multimodal support)
        content = self._build_message_content(text, files)
        messages.append(HumanMessage(content=content))

        # Run the graph
        result = self.graph.invoke(cast(Any, {"messages": messages}))

        # Extract response (last AI message with actual content)
        response_text = ""
        for msg in reversed(result["messages"]):
            if isinstance(msg, AIMessage):
                if msg.tool_calls and not extract_text_content(msg.content):
                    continue
                response_text = extract_text_content(msg.content)
                break

        # Serialize state for persistence (includes tool messages for multi-turn tool workflows)
        new_state: dict[str, Any] = {"messages": []}
        for m in result["messages"]:
            if isinstance(m, HumanMessage):
                new_state["messages"].append(
                    {"type": "human", "content": extract_text_content(m.content)}
                )
            elif isinstance(m, AIMessage):
                content = extract_text_content(m.content)
                if content:  # Only store if there's actual content
                    new_state["messages"].append({"type": "ai", "content": content})
            elif isinstance(m, ToolMessage):
                new_state["messages"].append(
                    {
                        "type": "tool",
                        "content": m.content,
                        "tool_call_id": m.tool_call_id,
                    }
                )

        return response_text, new_state


def generate_title(user_message: str, assistant_response: str) -> str:
    """
    Generate a concise title for a conversation using Gemini.

    Args:
        user_message: The first user message
        assistant_response: The assistant's response

    Returns:
        A short, descriptive title (max ~50 chars)
    """
    # Use Flash model for fast, cheap title generation
    model = ChatGoogleGenerativeAI(
        model="gemini-2.0-flash",
        google_api_key=Config.GEMINI_API_KEY,
        temperature=0.7,
    )

    prompt = f"""Generate a very short, concise title (3-6 words max) for this conversation.
The title should capture the main topic or intent.
Do NOT use quotes around the title.
Do NOT include prefixes like "Title:" or "Topic:".
Just output the title text directly.

User: {user_message[:500]}
Assistant: {assistant_response[:500]}

Title:"""

    try:
        response = model.invoke([HumanMessage(content=prompt)])
        title = extract_text_content(response.content).strip()
        # Clean up any quotes or prefixes that slipped through
        title = title.strip("\"'")
        if title.lower().startswith("title:"):
            title = title[6:].strip()
        # Truncate if too long
        if len(title) > 60:
            title = title[:57] + "..."
        return title or user_message[:50]
    except Exception:
        # Fallback to truncated message on any error
        return user_message[:50] + ("..." if len(user_message) > 50 else "")
