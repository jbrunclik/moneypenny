"""Replies get model_fallback: the model that wrote them when it was the fallback.

Nov 26 2026: a fallback only showed a toast; the reply now says so for good.
docs/features/chat-and-streaming.md "Model fallback".
"""

from yoyo import step

__depends__ = {"0105_search_artifact_titles"}

steps = [
    step(
        "ALTER TABLE messages ADD COLUMN model_fallback TEXT",
        "ALTER TABLE messages DROP COLUMN model_fallback",
    ),
]
