"""Prompt snapshots: the static prompt per profile and every tool declaration.

Each prompt or tool change shows up in review as a diff of the committed files
in tests/fixtures/prompt_snapshots/, with its size in sizes.txt (the static
prompt and tool schemas are sent on every turn, so their size is cost).
After an intended change, regenerate with `make prompt-snapshots`.

The snapshot must be the same on a laptop with a .env and in CI without one,
so everything environment-dependent is pinned: every tool is declared (not
only the configured integrations), Mapy is treated as configured, and the
memory tunables the prompt quotes take their code defaults. A new
environment-dependent piece makes laptop and CI disagree - pin it here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from langchain_core.tools import BaseTool
from langchain_google_genai._function_utils import convert_to_genai_function_declarations

import src.agent.prompts as prompts_module
import src.agent.tools as tools_module
from src.agent.context_cache import CacheProfile
from src.agent.prompts import get_static_prompt_for_profile
from src.config import Config

SNAPSHOT_DIR = Path(__file__).parents[1] / "fixtures" / "prompt_snapshots"
UPDATE_ENV_VAR = "UPDATE_PROMPT_SNAPSHOTS"

# Code defaults of the tunables the memory prompt quotes (src/config.py)
_PINNED_CONFIG = {"MEMORY_WARNING_THRESHOLD": 160, "MEMORY_MAX_OPS_PER_CALL": 10}


@pytest.fixture
def pinned_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prompts_module, "is_mapy_configured", lambda: True)
    for name, value in _PINNED_CONFIG.items():
        monkeypatch.setattr(Config, name, value)


def _all_tools() -> list[BaseTool]:
    """Every tool the package exports, configured or not, by name."""
    tools = {t.name: t for t in vars(tools_module).values() if isinstance(t, BaseTool)}
    return [tools[name] for name in sorted(tools)]


def _declarations() -> list[dict[str, object]]:
    """The function declarations as Gemini receives them (as the context cache builds them)."""
    declarations: list[dict[str, object]] = []
    for genai_tool in convert_to_genai_function_declarations(_all_tools()):
        dumped = genai_tool.model_dump(exclude_none=True, mode="json")
        declarations.extend(dumped["function_declarations"])
    return declarations


def _sizes(prompts: dict[str, str], declarations: list[dict[str, object]]) -> str:
    tool_sizes = {str(d["name"]): len(json.dumps(d, ensure_ascii=False)) for d in declarations}
    lines = [
        "# Characters sent on every turn. Regenerate: make prompt-snapshots",
        "",
        "static prompt",
        *(f"  {profile:<12} {len(text):>7}" for profile, text in prompts.items()),
        "",
        f"tool declarations ({len(tool_sizes)} tools, {sum(tool_sizes.values())} chars)",
        *(f"  {name:<26} {size:>7}" for name, size in tool_sizes.items()),
    ]
    return "\n".join(lines) + "\n"


def _build_snapshots() -> dict[str, str]:
    prompts = {p.value: get_static_prompt_for_profile(p.value) for p in CacheProfile}
    declarations = _declarations()
    files = {f"static-{profile}.txt": text for profile, text in prompts.items()}
    files["tools.json"] = json.dumps(declarations, indent=2, ensure_ascii=False) + "\n"
    files["sizes.txt"] = _sizes(prompts, declarations)
    return files


def _write_snapshots(files: dict[str, str]) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in SNAPSHOT_DIR.iterdir():
        if stale.name not in files:
            stale.unlink()
    for name, content in files.items():
        (SNAPSHOT_DIR / name).write_text(content, encoding="utf-8")


def _changed(files: dict[str, str]) -> list[str]:
    """One line per file that differs from the committed snapshot."""
    changes: list[str] = []
    for name, content in files.items():
        path = SNAPSHOT_DIR / name
        committed = path.read_text(encoding="utf-8") if path.exists() else None
        if committed is None:
            changes.append(f"  {name}: new ({len(content)} chars)")
        elif committed != content:
            changes.append(f"  {name}: {len(committed)} -> {len(content)} chars")
    if SNAPSHOT_DIR.exists():
        changes += [
            f"  {p.name}: no longer produced" for p in SNAPSHOT_DIR.iterdir() if p.name not in files
        ]
    return changes


@pytest.mark.usefixtures("pinned_environment")
def test_prompts_and_tool_declarations_match_the_snapshots() -> None:
    files = _build_snapshots()
    if os.environ.get(UPDATE_ENV_VAR) == "1":
        _write_snapshots(files)
        return
    changes = _changed(files)
    assert not changes, (
        "The static prompt or tool declarations changed:\n"
        + "\n".join(changes)
        + "\nIf intended, run `make prompt-snapshots` and commit tests/fixtures/prompt_snapshots/."
    )


@pytest.mark.usefixtures("pinned_environment")
def test_snapshots_cover_every_profile_and_tool() -> None:
    """A profile or tool missing here would change unreviewed."""
    files = _build_snapshots()
    assert {f"static-{p.value}.txt" for p in CacheProfile} <= files.keys()
    names = [d["name"] for d in json.loads(files["tools.json"])]
    assert names == [t.name for t in _all_tools()]
    assert {"manage_memory", "todoist", "create_artifact", "propose_deep_research"} <= set(names)


def test_no_tool_sends_its_description_twice() -> None:
    """langchain-google-genai copies a BaseTool's args-model docstring into
    `parameters.description`, beside the function description it already is -
    10.2k of the 24.5k tool tokens on every call (measured Nov 2026). The
    tools drop that duplicate from their args JSON schema."""
    doubled = [
        str(d["name"])
        for d in _declarations()
        if isinstance(d.get("parameters"), dict)
        and d["parameters"].get("description")  # type: ignore[union-attr]
        and d["parameters"]["description"] == d.get("description")  # type: ignore[index]
    ]
    assert doubled == []
