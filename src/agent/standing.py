"""A standing chat's additions to an ordinary chat turn (the type).

Agents and sports / language programs are standing chats
(docs/superpowers/specs/2026-11-08-standing-chats-design.md); the loader is
src/api/helpers/standing_context.py, the prompt section src/agent/prompts.py.
"""

from dataclasses import dataclass
from typing import Literal

StandingKind = Literal["agent", "sports", "language"]


@dataclass(frozen=True)
class StandingContext:
    """A standing chat's additions to the ordinary chat turn."""

    kind: StandingKind
    name: str
    instructions: str
    data: str | None
    kv_namespace: str
    agent_id: str | None = None
