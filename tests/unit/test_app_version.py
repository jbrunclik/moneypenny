"""The app version is the main bundle's hash (stale-bundle checks compare it)."""

from src.app import app_version_from_manifest


def _manifest(file: str) -> dict[str, dict[str, str | list[str]]]:
    return {"src/main.ts": {"file": file}}


def test_the_version_is_the_whole_hash_after_main() -> None:
    assert app_version_from_manifest(_manifest("assets/main-y-VVsbiY.js")) == "y-VVsbiY"


def test_a_hash_ending_in_a_dash_still_gives_a_version() -> None:
    """Nov 11 2026: main-QL6ZQxq-.js gave "" and switched stale-bundle checks off."""
    assert app_version_from_manifest(_manifest("assets/main-QL6ZQxq-.js")) == "QL6ZQxq-"


def test_no_manifest_no_version() -> None:
    assert app_version_from_manifest({}) is None
    assert app_version_from_manifest(_manifest("assets/other.js")) is None
