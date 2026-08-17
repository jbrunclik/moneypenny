"""Tests for the places agent tools (search_places, get_route)."""

from unittest.mock import MagicMock, patch

from src.agent.tools.places import get_route, search_places

POI = {
    "name": "Kavárna Slavia",
    "label": "Kavárna",
    "position": {"lon": 14.4135, "lat": 50.0813},
    "type": "poi",
    "location": "Praha 1 - Staré Město, Česko",
    "regionalStructure": [{"name": "Praha", "type": "regional.municipality"}],
}


@patch("src.agent.tools.places.mapy_geocode", return_value=[POI])
@patch("src.agent.tools.places.get_location_context", return_value={"lat": 50.08, "lon": 14.42})
def test_search_places_near_current(mock_loc: MagicMock, mock_geo: MagicMock) -> None:
    result = search_places.invoke({"query": "kavárna", "near": "current"})
    assert "Kavárna Slavia" in result
    assert "km" in result or "m " in result  # distance included
    mock_geo.assert_called_once()
    assert mock_geo.call_args.kwargs["prefer_near"] == (14.42, 50.08)


@patch("src.agent.tools.places.get_location_context", return_value=None)
def test_search_places_current_without_fix(mock_loc: MagicMock) -> None:
    result = search_places.invoke({"query": "kavárna", "near": "current"})
    # Graceful message that tells the agent the exact Settings path to relay
    assert "Settings" in result
    assert "Share device location" in result


@patch("src.agent.tools.places.mapy_geocode", return_value=[POI])
@patch("src.agent.tools.places._get_saved_place", return_value=None)
@patch("src.agent.tools.places.get_location_context", return_value=None)
def test_search_places_near_address(
    mock_loc: MagicMock, mock_saved: MagicMock, mock_geo: MagicMock
) -> None:
    result = search_places.invoke({"query": "lékárna", "near": "Brno"})
    assert "Kavárna Slavia" in result
    # first geocode call resolves "Brno", second searches near it
    assert mock_geo.call_count == 2


@patch("src.agent.tools.places.mapy_route", return_value={"length": 12500, "duration": 1500})
@patch(
    "src.agent.tools.places._get_saved_place",
    side_effect=lambda name: {"lon": 14.40, "lat": 50.07} if name == "home" else None,
)
@patch("src.agent.tools.places.mapy_geocode", return_value=[POI])
def test_get_route_home_to_poi(
    mock_geo: MagicMock, mock_saved: MagicMock, mock_route: MagicMock
) -> None:
    result = get_route.invoke({"origin": "home", "destination": "Kavárna Slavia", "mode": "car"})
    assert "12.5 km" in result
    assert "25 min" in result
    call = mock_route.call_args
    route_type = call.kwargs.get("route_type") or call.args[2]
    assert route_type == "car_fast_traffic"


@patch("src.agent.tools.places.mapy_route", return_value={"length": 900, "duration": 700})
@patch("src.agent.tools.places._get_saved_place", return_value=None)
@patch("src.agent.tools.places.mapy_geocode", return_value=[POI])
def test_get_route_foot_mode(
    mock_geo: MagicMock, mock_saved: MagicMock, mock_route: MagicMock
) -> None:
    result = get_route.invoke({"origin": "Praha 1", "destination": "Praha 2", "mode": "foot"})
    assert "900 m" in result
    call = mock_route.call_args
    route_type = call.kwargs.get("route_type") or call.args[2]
    assert route_type == "foot_fast"


def test_get_route_unknown_mode() -> None:
    result = get_route.invoke({"origin": "A", "destination": "B", "mode": "teleport"})
    assert "Unknown mode" in result
