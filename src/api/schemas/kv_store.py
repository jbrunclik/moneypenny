"""K/V store management schemas."""

from __future__ import annotations

from pydantic import Field

from src.api.schemas.base import RequestModel, ResponseModel


class KVNamespaceItem(ResponseModel):
    """Single namespace entry."""

    namespace: str
    key_count: int


class KVNamespacesResponse(ResponseModel):
    """List of namespaces with key counts."""

    namespaces: list[KVNamespaceItem]


class KVKeyItem(ResponseModel):
    """Single key-value entry."""

    key: str
    value: str


class KVKeysResponse(ResponseModel):
    """Keys in a namespace."""

    namespace: str
    keys: list[KVKeyItem]


class KVValueResponse(ResponseModel):
    """Single key value."""

    namespace: str
    key: str
    value: str


class KVSetRequest(RequestModel):
    """Request to set a key value."""

    value: str = Field(..., max_length=65536)
