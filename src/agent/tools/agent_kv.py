"""Key-value store tool for autonomous agents.

This tool allows agents to persist and retrieve structured data
across conversations and executions using a namespaced K/V store.
Values must be valid JSON strings.
"""

from typing import Any

from langchain_core.tools import tool

from src.agent.tools.context import get_conversation_context
from src.db.models import db
from src.utils.logging import get_logger

logger = get_logger(__name__)

# Limits
_MAX_KEY_LENGTH = 256
_MAX_VALUE_SIZE = 65536  # 64KB
_MAX_KEYS_PER_NAMESPACE = 1000


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `patch` into `base`, returning a new dict.

    Nested objects merge rather than replace, so updating one field of
    `progress.bench` does not drop `progress.squat`. An explicit null removes
    the key, which is the only way to delete a field without a full rewrite.
    """
    out = dict(base)
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


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
    - merge: Deep-merge a JSON object into the existing value (creates it if absent).
      PREFER THIS over get-then-set when updating part of a stored object: it is
      one round instead of two, and it cannot clobber fields you did not read.
      Only the keys you pass are changed; nested objects merge recursively and a
      null value deletes a key. Fails if the stored value is not a JSON object.
    - delete: Remove a key
    - list: List all keys in the namespace (key parameter used as optional prefix filter)

    Args:
        action: One of 'get', 'set', 'merge', 'delete', 'list'
        key: The key to operate on (required for get/set/merge/delete, optional prefix for list)
        value: The value to store (required for set/merge, must be valid JSON, max 64KB)
        namespace: Storage namespace. Auto-defaults to 'agent:<agent_id>' for autonomous agents.
            Can be overridden to access shared namespaces.

    Returns:
        The result of the operation as a string
    """
    import json

    from src.agent.executor import get_agent_context
    from src.agent.tools.context import get_language_context, get_sports_context

    # Get user context
    _, user_id = get_conversation_context()
    if not user_id:
        return "Error: No user context available. Cannot access K/V store."

    # Available during autonomous agent execution, sports, or language conversations
    agent_context = get_agent_context()
    sports_program = get_sports_context()
    language_program = get_language_context()
    if not agent_context and not sports_program and not language_program:
        return "Error: kv_store is only available during autonomous agent, sports, or language conversations."

    # Auto-default namespace
    if not namespace:
        if language_program:
            namespace = "language"
        elif sports_program:
            namespace = "sports"
        elif agent_context:
            namespace = f"agent:{agent_context.agent.id}"

    # Validate action
    if action not in ("get", "set", "merge", "delete", "list"):
        return f"Error: Invalid action '{action}'. Use 'get', 'set', 'merge', 'delete', or 'list'."

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

    elif action == "merge":
        if not key:
            return "Error: 'key' is required for 'merge' action."
        if not value:
            return "Error: 'value' is required for 'merge' action."
        if len(value) > _MAX_VALUE_SIZE:
            return f"Error: Value too large ({len(value)} bytes). Maximum is {_MAX_VALUE_SIZE} bytes (64KB)."
        try:
            patch = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return "Error: Value must be valid JSON."
        if not isinstance(patch, dict):
            return "Error: 'merge' requires a JSON object. Use 'set' to replace a non-object value."

        stored = db.kv_get(user_id, namespace, key)
        base: dict[str, Any] = {}
        if stored is None:
            if db.kv_count(user_id, namespace) >= _MAX_KEYS_PER_NAMESPACE:
                return f"Error: Namespace '{namespace}' has reached the maximum of {_MAX_KEYS_PER_NAMESPACE} keys."
        else:
            try:
                decoded = json.loads(stored)
            except (json.JSONDecodeError, TypeError):
                return (
                    f"Error: Stored value for '{key}' is not valid JSON. Use 'set' to replace it."
                )
            if not isinstance(decoded, dict):
                return f"Error: Stored value for '{key}' is not a JSON object. Use 'set' to replace it."
            base = decoded

        merged = json.dumps(_deep_merge(base, patch))
        if len(merged) > _MAX_VALUE_SIZE:
            return f"Error: Merged value too large ({len(merged)} bytes). Maximum is {_MAX_VALUE_SIZE} bytes (64KB)."
        db.kv_set(user_id, namespace, key, merged)
        return f"Merged into '{key}' in namespace '{namespace}'. New value:\n{merged}"

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
