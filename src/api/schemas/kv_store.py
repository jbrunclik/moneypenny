"""K/V store management schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class KVNamespaceItem(BaseModel):
    """Single namespace entry."""

    namespace: str
    key_count: int


class KVNamespacesResponse(BaseModel):
    """List of namespaces with key counts."""

    namespaces: list[KVNamespaceItem]


class KVKeyItem(BaseModel):
    """Single key-value entry."""

    key: str
    value: str


class KVKeysResponse(BaseModel):
    """Keys in a namespace."""

    namespace: str
    keys: list[KVKeyItem]


class KVValueResponse(BaseModel):
    """Single key value."""

    namespace: str
    key: str
    value: str


class KVSetRequest(BaseModel):
    """Request to set a key value."""

    value: str = Field(..., max_length=65536)
