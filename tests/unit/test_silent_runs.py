"""A scheduled run with nothing new replies [SILENT]: nothing is posted and no
push goes out - every run used to push whether or not it found anything."""

import pytest

from src.agent.executor import is_silent_reply


@pytest.mark.parametrize(
    "text", ["[SILENT]", " [silent]. ", "[SILENT]\n", "`[SILENT]`", "**[SILENT]**"]
)
def test_the_marker_alone_is_silent(text: str) -> None:
    assert is_silent_reply(text)


@pytest.mark.parametrize("text", ["Found 2 new items. [SILENT]", "", "Nothing changed, but note X"])
def test_real_content_is_not_silent(text: str) -> None:
    assert not is_silent_reply(text)


def test_the_agent_prompt_explains_the_marker() -> None:
    from src.agent.prompt_texts.agents import AUTONOMOUS_AGENT_SYSTEM_PROMPT

    assert "[SILENT]" in AUTONOMOUS_AGENT_SYSTEM_PROMPT
