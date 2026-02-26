"""Key-value store routes: user-scoped namespaced storage.

This module provides REST endpoints for managing key-value data
stored per-user in namespaces.
"""

from __future__ import annotations

from typing import Any

from apiflask import APIBlueprint

from src.api.errors import raise_not_found_error, raise_validation_error
from src.api.rate_limiting import rate_limit_conversations
from src.api.schemas import (
    KVKeysResponse,
    KVNamespacesResponse,
    KVSetRequest,
    KVValueResponse,
    StatusResponse,
)
from src.auth.jwt_auth import require_auth
from src.db.models import User, db
from src.utils.logging import get_logger

logger = get_logger(__name__)

api = APIBlueprint("kv_store", __name__, url_prefix="/api/kv", tag="KV Store")


@api.route("", methods=["GET"])
@api.output(KVNamespacesResponse)
@api.doc(responses=[401])
@require_auth
def list_namespaces(user: User) -> dict[str, Any]:
    """List all namespaces with key counts for the current user."""
    namespaces = db.kv_list_namespaces(user.id)
    return {"namespaces": [{"namespace": ns, "key_count": count} for ns, count in namespaces]}


@api.route("/<path:namespace>", methods=["GET"])
@api.output(KVKeysResponse)
@api.doc(responses=[401])
@require_auth
def list_keys(user: User, namespace: str) -> dict[str, Any]:
    """List all keys and values in a namespace."""
    items = db.kv_list(user.id, namespace)
    return {
        "namespace": namespace,
        "keys": [{"key": k, "value": v} for k, v in items],
    }


@api.route("/<path:namespace>/<key>", methods=["GET"])
@api.output(KVValueResponse)
@api.doc(responses=[401, 404])
@require_auth
def get_value(user: User, namespace: str, key: str) -> dict[str, Any]:
    """Get a single key's value."""
    value = db.kv_get(user.id, namespace, key)
    if value is None:
        raise_not_found_error("Key")
    return {
        "namespace": namespace,
        "key": key,
        "value": value,
    }


@api.route("/<path:namespace>/<key>", methods=["PUT"])
@api.input(KVSetRequest)
@api.output(KVValueResponse)
@api.doc(responses=[400, 401])
@rate_limit_conversations
@require_auth
def set_value(user: User, namespace: str, key: str, json_data: KVSetRequest) -> dict[str, Any]:
    """Set a key's value (create or update). Value must be valid JSON."""
    import json

    if len(key) > 256:
        raise_validation_error("Key too long (max 256 characters)")

    # Validate that value is valid JSON
    try:
        json.loads(json_data.value)
    except (json.JSONDecodeError, TypeError):
        raise_validation_error("Value must be valid JSON")

    db.kv_set(user.id, namespace, key, json_data.value)
    return {
        "namespace": namespace,
        "key": key,
        "value": json_data.value,
    }


@api.route("/<path:namespace>/<key>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[401, 404])
@require_auth
def delete_key(user: User, namespace: str, key: str) -> dict[str, Any]:
    """Delete a key."""
    deleted = db.kv_delete(user.id, namespace, key)
    if not deleted:
        raise_not_found_error("Key")
    return {"status": "deleted"}


@api.route("/<path:namespace>", methods=["DELETE"])
@api.output(StatusResponse)
@api.doc(responses=[401])
@require_auth
def clear_namespace(user: User, namespace: str) -> dict[str, Any]:
    """Clear all keys in a namespace."""
    count = db.kv_clear_namespace(user.id, namespace)
    return {"status": f"cleared {count} keys"}
