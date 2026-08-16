"""Tests for the Mapy.com REST API client."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.utils.mapy import MapyError, mapy_geocode, mapy_rgeocode, mapy_route


def _mock_response(status: int, payload: dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    return resp


GEOCODE_PAYLOAD = {
    "items": [
        {
            "name": "Kavárna Slavia",
            "label": "Kavárna",
            "position": {"lon": 14.4135, "lat": 50.0813},
            "type": "poi",
            "location": "Praha 1 - Staré Město, Česko",
            "regionalStructure": [
                {"name": "Praha 1", "type": "regional.municipality_part"},
                {"name": "Praha", "type": "regional.municipality"},
                {"name": "Česko", "type": "regional.country", "isoCode": "CZ"},
            ],
        }
    ]
}


@patch("src.utils.mapy.Config")
@patch("src.utils.mapy.requests.get")
def test_geocode_poi_near(mock_get: MagicMock, mock_config: MagicMock) -> None:
    mock_config.MAPY_CZ_API_KEY = "test-key"
    mock_config.MAPY_API_TIMEOUT = 10
    mock_get.return_value = _mock_response(200, GEOCODE_PAYLOAD)

    items = mapy_geocode("kavárna", poi_only=True, prefer_near=(14.42, 50.08), limit=5)

    assert items[0]["name"] == "Kavárna Slavia"
    _, kwargs = mock_get.call_args
    assert kwargs["headers"] == {"X-Mapy-Api-Key": "test-key"}
    assert kwargs["params"]["type"] == "poi"
    assert kwargs["params"]["preferNear"] == "14.42,50.08"
    assert kwargs["params"]["limit"] == 5
    assert "apikey" not in kwargs["params"]


@patch("src.utils.mapy.Config")
@patch("src.utils.mapy.requests.get")
def test_rgeocode(mock_get: MagicMock, mock_config: MagicMock) -> None:
    mock_config.MAPY_CZ_API_KEY = "test-key"
    mock_config.MAPY_API_TIMEOUT = 10
    mock_get.return_value = _mock_response(200, GEOCODE_PAYLOAD)

    items = mapy_rgeocode(14.4378, 50.0755)

    assert items[0]["location"].startswith("Praha 1")
    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"lon": 14.4378, "lat": 50.0755}


@patch("src.utils.mapy.Config")
@patch("src.utils.mapy.requests.get")
def test_route(mock_get: MagicMock, mock_config: MagicMock) -> None:
    mock_config.MAPY_CZ_API_KEY = "test-key"
    mock_config.MAPY_API_TIMEOUT = 10
    mock_get.return_value = _mock_response(200, {"length": 12500, "duration": 1500, "geometry": {}})

    result = mapy_route((14.4009, 50.0711), (14.4378, 50.0755), "car_fast_traffic")

    assert result["length"] == 12500
    assert result["duration"] == 1500
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["start"] == "14.4009,50.0711"
    assert kwargs["params"]["end"] == "14.4378,50.0755"
    assert kwargs["params"]["routeType"] == "car_fast_traffic"


@patch("src.utils.mapy.Config")
@patch("src.utils.mapy.requests.get")
def test_error_raises_mapy_error(mock_get: MagicMock, mock_config: MagicMock) -> None:
    mock_config.MAPY_CZ_API_KEY = "test-key"
    mock_config.MAPY_API_TIMEOUT = 10
    mock_get.return_value = _mock_response(403, {"detail": [{"msg": "Forbidden"}]})

    with pytest.raises(MapyError, match="403"):
        mapy_geocode("Praha")


@patch("src.utils.mapy.Config")
def test_missing_key_raises(mock_config: MagicMock) -> None:
    mock_config.MAPY_CZ_API_KEY = ""
    with pytest.raises(MapyError, match="not configured"):
        mapy_geocode("Praha")
