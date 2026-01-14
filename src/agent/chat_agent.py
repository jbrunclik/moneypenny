"""Chat agent module - DEPRECATED.

This module has been refactored into focused submodules. Import directly from:
- src.agent.agent: ChatAgent, generate_title, _planner_dashboard_context
- src.agent.graph: AgentState, create_chat_model, create_chat_graph, etc.
- src.agent.prompts: System prompts, get_system_prompt, get_user_context, etc.
- src.agent.content: extract_text_content, extract_metadata_from_response, etc.
- src.agent.tool_results: set_current_request_id, get_full_tool_results, etc.
- src.agent.tool_display: TOOL_METADATA, extract_tool_detail, etc.

This file exists only for tool name validation on import.
"""

from src.agent.tool_display import validate_tool_names

# Run validation on import to catch tool name mismatches early
validate_tool_names()
