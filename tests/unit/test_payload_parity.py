"""The JSON a message stores and the API model that sends it describe one shape.

Each TypedDict in src/db/models/dataclasses.py (what messages.annotations,
.grounding, .action and .artifacts hold) mirrors a response model in
src/api/schemas/chat.py by hand. A key added to one side only drifts quietly:
the API drops a stored key, or the client is promised one that is never
stored. The pairs must agree on their keys and on which values may be
missing - absent or None in storage exactly when the API may send null.
"""

import types
from typing import Any, Union, get_args, get_origin, get_type_hints

import pytest
from pydantic import BaseModel

from src.api.schemas.chat import (
    ArtifactRef,
    ClaimAnnotationResponse,
    DeepResearchActionResponse,
    GroundingSummaryResponse,
    VerifyClaimActionResponse,
)
from src.db.models.dataclasses import (
    ArtifactShown,
    ClaimAnnotation,
    DeepResearchAction,
    GroundingSummary,
    VerifyClaimAction,
)

PAIRS: list[tuple[Any, type[BaseModel]]] = [
    (ClaimAnnotation, ClaimAnnotationResponse),
    (GroundingSummary, GroundingSummaryResponse),
    (VerifyClaimAction, VerifyClaimActionResponse),
    (DeepResearchAction, DeepResearchActionResponse),
    (ArtifactShown, ArtifactRef),
]


def _allows_none(annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        return type(None) in get_args(annotation)
    return annotation is type(None)


def _stored_may_be_missing(stored: Any) -> dict[str, bool]:
    hints = get_type_hints(stored)
    return {key: key in stored.__optional_keys__ or _allows_none(hints[key]) for key in hints}


def _sent_may_be_null(model: type[BaseModel]) -> dict[str, bool]:
    return {name: _allows_none(field.annotation) for name, field in model.model_fields.items()}


@pytest.mark.parametrize(("stored", "model"), PAIRS, ids=[model.__name__ for _, model in PAIRS])
def test_stored_payload_matches_its_response_model(stored: Any, model: type[BaseModel]) -> None:
    assert _stored_may_be_missing(stored) == _sent_may_be_null(model)


def test_the_check_sees_a_drift() -> None:
    """A key on one side only, or a nullability mismatch, fails the comparison."""
    from typing import NotRequired, TypedDict

    class Stored(TypedDict):
        a: str
        b: NotRequired[int]

    class Sent(BaseModel):
        a: str
        b: int  # not nullable: the stored side may lack it

    class SentWithExtra(BaseModel):
        a: str
        b: int | None = None
        c: str

    assert _stored_may_be_missing(Stored) != _sent_may_be_null(Sent)
    assert _stored_may_be_missing(Stored) != _sent_may_be_null(SentWithExtra)
