"""Tests for the dynamic location section of the user context prompt."""

from unittest.mock import MagicMock, patch

from src.agent.prompts import get_user_context


@patch("src.agent.prompts._get_saved_places_lines", return_value=[])
@patch(
    "src.agent.prompts._reverse_geocode_locality",
    return_value="Praha 1 - Staré Město, Česko",
)
@patch("src.agent.prompts.get_location_context")
def test_device_location_in_context(
    mock_loc: MagicMock, mock_rgeo: MagicMock, mock_places: MagicMock
) -> None:
    mock_loc.return_value = {
        "lat": 50.0813,
        "lon": 14.4135,
        "accuracy_m": 10,
        "timestamp_ms": None,
    }
    ctx = get_user_context(user_name="Jiri", user_id="u1")
    assert "Praha 1 - Staré Město" in ctx
    assert "device location" in ctx.lower()


@patch(
    "src.agent.prompts._get_saved_places_lines",
    return_value=["- home: Nádražní 12, Praha"],
)
@patch("src.agent.prompts.get_location_context", return_value=None)
def test_saved_places_listed_without_fix(mock_loc: MagicMock, mock_places: MagicMock) -> None:
    ctx = get_user_context(user_name="Jiri", user_id="u1")
    assert "home: Nádražní 12" in ctx


@patch("src.agent.prompts._get_saved_places_lines", return_value=[])
@patch("src.agent.prompts.get_location_context", return_value=None)
def test_env_fallback_when_nothing_shared(mock_loc: MagicMock, mock_places: MagicMock) -> None:
    with patch("src.agent.prompts.Config") as mock_config:
        mock_config.USER_LOCATION = "Prague, Czech Republic"
        ctx = get_user_context(user_name="Jiri", user_id="u1")
    assert "Prague, Czech Republic" in ctx


def test_saved_places_lines_formats_address() -> None:
    from src.agent.prompts import _get_saved_places_lines

    with patch("src.db.models.db.kv_list") as mock_kv:
        mock_kv.return_value = [
            ("home", '{"address": "Nádražní 12, Praha", "lon": 14.4, "lat": 50.07}'),
            ("gym", "not-json"),
        ]
        lines = _get_saved_places_lines("u1")
    assert lines == ["- home: Nádražní 12, Praha", "- gym"]
    mock_kv.assert_called_once_with("u1", "places")
