"""Datetime conventions for persisted timestamps.

The codebase stores naive ISO strings in SQLite, in two conventions:

- **UTC-naive** (`utcnow_naive()`): machine timestamps that are compared
  across requests/workers or against the scheduler - the agent subsystem
  (autonomous_agents, agent_executions, agent_approval_requests), all cache
  tables, kv_store and settings metadata. Serialize these to the API with
  `to_utc_iso()` so browsers parse them correctly in any timezone.

- **Local-naive** (`datetime.now()`): user-facing conversation data
  (messages, conversations, costs) and fields cross-compared with it
  (`autonomous_agents.last_viewed_at` vs `messages.created_at`, the daily
  spending window vs `message_costs.created_at`). Changing these requires a
  data migration and a display-path sweep - see TODO R9 notes.

Don't mix conventions for fields that are compared with each other.
"""

from datetime import UTC, datetime


def utcnow_naive() -> datetime:
    """Current UTC time as a naive datetime (the storage convention).

    Replacement for the deprecated ``datetime.utcnow()``.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def to_utc_iso(dt: datetime) -> str:
    """Serialize a UTC-naive datetime as an explicit-UTC ISO string.

    Naive ISO strings are parsed as *browser-local* time by JavaScript's
    ``new Date()``; the ``+00:00`` marker makes parsing timezone-correct.
    """
    return dt.replace(tzinfo=UTC).isoformat()
