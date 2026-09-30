"""Built-in skills: recipe-level instructions the agent loads on demand.

Each skill is src/agent/skills/<name>/SKILL.md with agentskills.io-style
frontmatter (name, description). The descriptions form an always-on index
(skills_index_prompt, appended to the tools prompt); the body reaches the
model only through the load_skill tool, as a tool result - after the cached
prompt prefix, so loading never breaks the context cache. Files are parsed
and validated once at import: a broken skill fails CI, not a chat turn.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.constants import SKILL_MAX_BODY_CHARS, SKILL_MAX_DESCRIPTION_CHARS

_SKILLS_DIR = Path(__file__).parent
_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)

_INDEX_HEADER = """
# Skills
Skills are detailed instructions for specific tasks. When a task matches a skill below,
ALWAYS call load_skill(name) FIRST, before doing the task - even if you think you know how.
Loading a skill does not finish your turn: read it, then continue with the task in the same
turn.
"""


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str


def parse_skill(path: Path) -> Skill:
    """Parse and validate one SKILL.md (ValueError names the file)."""
    match = _FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"{path}: missing '---' frontmatter block")
    meta = yaml.safe_load(match.group(1)) or {}
    name = str(meta.get("name", ""))
    description = " ".join(str(meta.get("description", "")).split())
    body = match.group(2).strip() + "\n"
    if name != path.parent.name or not _NAME_RE.match(name) or len(name) > 64:
        raise ValueError(
            f"{path}: name {name!r} must be lowercase-hyphenated and match its directory"
        )
    if not description or len(description) > SKILL_MAX_DESCRIPTION_CHARS:
        raise ValueError(f"{path}: description must be 1-{SKILL_MAX_DESCRIPTION_CHARS} chars")
    if len(body) > SKILL_MAX_BODY_CHARS:
        raise ValueError(f"{path}: body exceeds {SKILL_MAX_BODY_CHARS} chars")
    return Skill(name=name, description=description, body=body)


def _load_all() -> dict[str, Skill]:
    parsed = [parse_skill(p) for p in sorted(_SKILLS_DIR.glob("*/SKILL.md"))]
    return {s.name: s for s in sorted(parsed, key=lambda s: s.name)}


_SKILLS = _load_all()


def list_skills() -> list[Skill]:
    return list(_SKILLS.values())


def get_skill(name: str) -> Skill | None:
    return _SKILLS.get(name)


def skills_index_prompt() -> str:
    """The always-on index section (byte-stable: part of the cached prefix)."""
    lines = [f"- {s.name}: {s.description}" for s in _SKILLS.values()]
    return _INDEX_HEADER + "\n".join(lines) + "\n"
