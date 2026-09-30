"""Built-in skill files: parsing, validation, and the always-on index."""

from pathlib import Path

import pytest

from src.agent import skills
from src.constants import SKILL_MAX_BODY_CHARS, SKILL_MAX_DESCRIPTION_CHARS

EXPECTED = {
    "browser-tactics",
    "office-documents",
    "pdf-documents",
    "product-research",
    "trip-itinerary",
    "weekly-planning",
}


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name / "SKILL.md"
    path.parent.mkdir()
    path.write_text(text)
    return path


def test_every_shipped_skill_is_valid() -> None:
    names = [s.name for s in skills.list_skills()]
    assert set(names) == EXPECTED
    assert names == sorted(names)
    for skill in skills.list_skills():
        assert skill.description and len(skill.description) <= SKILL_MAX_DESCRIPTION_CHARS
        assert skill.body.strip() and len(skill.body) <= SKILL_MAX_BODY_CHARS


def test_get_skill_by_name() -> None:
    skill = skills.get_skill("office-documents")
    assert skill is not None
    assert "python-docx" in skill.body
    assert skills.get_skill("nope") is None


def test_parse_rejects_name_not_matching_directory(tmp_path: Path) -> None:
    path = _write(tmp_path, "office", "---\nname: word\ndescription: x\n---\nbody\n")
    with pytest.raises(ValueError, match="office"):
        skills.parse_skill(path)


def test_parse_rejects_missing_frontmatter(tmp_path: Path) -> None:
    path = _write(tmp_path, "plain", "just a body\n")
    with pytest.raises(ValueError, match="frontmatter"):
        skills.parse_skill(path)


def test_parse_rejects_oversized_description(tmp_path: Path) -> None:
    long = "x" * (SKILL_MAX_DESCRIPTION_CHARS + 1)
    path = _write(tmp_path, "big", f"---\nname: big\ndescription: {long}\n---\nbody\n")
    with pytest.raises(ValueError, match="description"):
        skills.parse_skill(path)


def test_parse_rejects_oversized_body(tmp_path: Path) -> None:
    body = "y" * (SKILL_MAX_BODY_CHARS + 1)
    path = _write(tmp_path, "huge", f"---\nname: huge\ndescription: d\n---\n{body}\n")
    with pytest.raises(ValueError, match="body"):
        skills.parse_skill(path)


def test_index_lists_every_skill_with_the_load_directive() -> None:
    index = skills.skills_index_prompt()
    assert "ALWAYS call load_skill(name) FIRST" in index
    assert "does not finish your turn" in index
    for skill in skills.list_skills():
        assert f"- {skill.name}: {skill.description}" in index


def test_index_is_byte_stable() -> None:
    assert skills.skills_index_prompt() == skills.skills_index_prompt()


def test_bodies_survive_braces_verbatim(tmp_path: Path) -> None:
    path = _write(tmp_path, "braces", "---\nname: braces\ndescription: d\n---\nuse {placeholder}\n")
    assert "{placeholder}" in skills.parse_skill(path).body
