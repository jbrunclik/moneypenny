"""Validation tests for ChatRequest.client_location."""

import pytest
from pydantic import ValidationError

from src.api.schemas import ChatRequest, ClientLocation


def test_chat_request_accepts_client_location() -> None:
    req = ChatRequest(
        message="hi",
        client_location={
            "lat": 50.0755,
            "lon": 14.4378,
            "accuracy_m": 12.5,
            "timestamp_ms": 1755300000000,
        },
    )
    assert req.client_location is not None
    assert req.client_location.lat == 50.0755


def test_chat_request_client_location_optional() -> None:
    assert ChatRequest(message="hi").client_location is None


@pytest.mark.parametrize("lat,lon", [(91, 0), (-91, 0), (0, 181), (0, -181)])
def test_client_location_bounds(lat: float, lon: float) -> None:
    with pytest.raises(ValidationError):
        ClientLocation(lat=lat, lon=lon)


def test_location_contextvar_roundtrip() -> None:
    from src.agent.tools.context import get_location_context, set_location_context

    assert get_location_context() is None
    set_location_context({"lat": 50.0, "lon": 14.0})
    assert get_location_context() == {"lat": 50.0, "lon": 14.0}
    set_location_context(None)
    assert get_location_context() is None
