"""Key-value store tool for autonomous agents.

This tool allows agents to persist and retrieve structured data
across conversations and executions using a namespaced K/V store.
Values must be valid JSON strings.
"""

from langchain_core.tools import tool

from src.agent.tools.context import get_conversation_context
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Limits
_MAX_KEY_LENGTH = 256
_MAX_VALUE_SIZE = 65536  # 64KB
_MAX_KEYS_PER_NAMESPACE = 1000


@tool
def kv_store(
    action: str,
    key: str = "",
    value: str = "",
    namespace: str = "",
) -> str:
    """Persist and retrieve key-value data across conversations and executions.

    Use this to store state, results, or any structured data that should survive
    across multiple runs. Data is scoped per-user and per-namespace.

    Actions:
    - get: Retrieve a value by key
    - set: Store a key-value pair (creates or overwrites). Value must be valid JSON.
    - delete: Remove a key
    - list: List all keys in the namespace (key parameter used as optional prefix filter)

    Args:
        action: One of 'get', 'set', 'delete', 'list'
        key: The key to operate on (required for get/set/delete, optional prefix for list)
        value: The value to store (required for set, must be valid JSON, max 64KB)
        namespace: Storage namespace. Auto-defaults to 'agent:<agent_id>' for autonomous agents.
            Can be overridden to access shared namespaces.

    Returns:
        The result of the operation as a string
    """
    import json

    from src.agent.executor import get_agent_context

    # Get user context
    _, user_id = get_conversation_context()
    if not user_id:
        return "Error: No user context available. Cannot access K/V store."

    # Only available during autonomous agent execution
    agent_context = get_agent_context()
    if not agent_context:
        return "Error: kv_store is only available during autonomous agent execution."

    # Auto-default namespace for agents
    if not namespace:
        namespace = f"agent:{agent_context.agent.id}"

    # Validate action
    if action not in ("get", "set", "delete", "list"):
        return f"Error: Invalid action '{action}'. Use 'get', 'set', 'delete', or 'list'."

    # Validate key length
    if key and len(key) > _MAX_KEY_LENGTH:
        return f"Error: Key too long ({len(key)} chars). Maximum is {_MAX_KEY_LENGTH}."

    if action == "get":
        if not key:
            return "Error: 'key' is required for 'get' action."
        result = db.kv_get(user_id, namespace, key)
        if result is None:
            return f"Key '{key}' not found in namespace '{namespace}'."
        return result

    elif action == "set":
        if not key:
            return "Error: 'key' is required for 'set' action."
        if not value:
            return "Error: 'value' is required for 'set' action."
        if len(value) > _MAX_VALUE_SIZE:
            return f"Error: Value too large ({len(value)} bytes). Maximum is {_MAX_VALUE_SIZE} bytes (64KB)."
        # Validate JSON
        try:
            json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return "Error: Value must be valid JSON."
        # Check key count limit
        current_count = db.kv_count(user_id, namespace)
        existing = db.kv_get(user_id, namespace, key)
        if existing is None and current_count >= _MAX_KEYS_PER_NAMESPACE:
            return f"Error: Namespace '{namespace}' has reached the maximum of {_MAX_KEYS_PER_NAMESPACE} keys."
        db.kv_set(user_id, namespace, key, value)
        return f"Stored '{key}' in namespace '{namespace}'."

    elif action == "delete":
        if not key:
            return "Error: 'key' is required for 'delete' action."
        deleted = db.kv_delete(user_id, namespace, key)
        if deleted:
            return f"Deleted '{key}' from namespace '{namespace}'."
        return f"Key '{key}' not found in namespace '{namespace}'."

    else:  # list
        prefix = key if key else None
        items = db.kv_list(user_id, namespace, prefix=prefix)
        if not items:
            prefix_msg = f" with prefix '{prefix}'" if prefix else ""
            return f"No keys found in namespace '{namespace}'{prefix_msg}."
        lines = [f"Keys in namespace '{namespace}' ({len(items)}):"]
        for k, v in items:
            preview = v[:100] + "..." if len(v) > 100 else v
            lines.append(f"  {k}: {preview}")
        return "\n".join(lines)
