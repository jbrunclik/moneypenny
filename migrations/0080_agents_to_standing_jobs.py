"""Agents become standing chats with a standing job (same id as the agent).

For every agent: its chat gets the standing settings (name, instructions,
type, description, unread marker) and a scheduled_items row with the agent's
id carries the schedule, timezone, grants (tool_permissions; NULL = all tools
= ["*"]), model, budget and fresh_context; a disabled agent's job is paused
("disabled"). Keeping the id keeps every reference valid: conversations.agent_id,
agent_executions, agent_approval_requests, users.daily_briefing_agent_id.

autonomous_agents is then renamed to a backup and replaced by a VIEW of the
same name over the chat + job, so every reader keeps working while Part C
removes the agent code (docs/superpowers/plans/2026-11-08-standing-chats-phase-2.md).
Rollback restores the table from the live chats and jobs: edits and agents
created since carry over, agents deleted since stay deleted (a restored agent's
next_run_at may be in the past: it runs once on the next tick).
"""

from yoyo import step

__depends__ = {"0079_standing_chat_columns"}

# A standing job without a schedule (run by hand / by another agent only)
NEVER = "9999-12-31T00:00:00.000000+00:00"
JOB_TEXT = "Do what this chat''s standing instructions describe."

_COPY_JOBS = f"""
INSERT INTO scheduled_items (
    id, user_id, conversation_id, kind, text, end_condition, schedule, interval_hours,
    next_run_at, expires_at, status, last_result, quiet_runs, failures, created_at,
    claimed_at, grants, model, budget_usd, fresh_context, timezone, paused_reason
)
SELECT
    a.id, a.user_id, a.conversation_id, 'recurring', '{JOB_TEXT}', NULL, a.schedule, NULL,
    COALESCE(a.next_run_at, '{NEVER}'), NULL,
    CASE WHEN a.enabled THEN 'active' ELSE 'paused' END, NULL, 0, 0, a.created_at,
    NULL, COALESCE(a.tool_permissions, '["*"]'), a.model, a.budget_limit,
    COALESCE(a.fresh_context, 1), a.timezone,
    CASE WHEN a.enabled THEN NULL ELSE 'disabled' END
FROM autonomous_agents a
WHERE a.conversation_id IS NOT NULL
"""

_COPY_SETTINGS = """
UPDATE conversations SET
    standing_name = (SELECT a.name FROM autonomous_agents a WHERE a.conversation_id = conversations.id),
    standing_instructions = (
        SELECT a.system_prompt FROM autonomous_agents a WHERE a.conversation_id = conversations.id
    ),
    standing_type = (
        SELECT a.system_type FROM autonomous_agents a WHERE a.conversation_id = conversations.id
    ),
    standing_description = (
        SELECT a.description FROM autonomous_agents a WHERE a.conversation_id = conversations.id
    ),
    standing_viewed_at = (
        SELECT a.last_viewed_at FROM autonomous_agents a WHERE a.conversation_id = conversations.id
    )
WHERE id IN (SELECT conversation_id FROM autonomous_agents)
"""

# The agent as readers knew it, from the chat and its job
_VIEW = f"""
CREATE VIEW autonomous_agents AS
SELECT
    s.id AS id,
    s.user_id AS user_id,
    c.id AS conversation_id,
    c.standing_name AS name,
    c.standing_description AS description,
    c.standing_instructions AS system_prompt,
    s.schedule AS schedule,
    COALESCE(s.timezone, 'UTC') AS timezone,
    CASE WHEN s.paused_reason = 'disabled' THEN 0 ELSE 1 END AS enabled,
    CASE WHEN s.grants = '["*"]' THEN NULL ELSE s.grants END AS tool_permissions,
    COALESCE(s.model, c.model) AS model,
    s.created_at AS created_at,
    c.updated_at AS updated_at,
    (SELECT MAX(e.started_at) FROM agent_executions e WHERE e.agent_id = s.id) AS last_run_at,
    CASE
        WHEN s.paused_reason = 'disabled' OR s.next_run_at >= '{NEVER}' THEN NULL
        ELSE s.next_run_at
    END AS next_run_at,
    c.standing_viewed_at AS last_viewed_at,
    s.budget_usd AS budget_limit,
    s.fresh_context AS fresh_context,
    c.standing_type AS system_type
FROM conversations c
JOIN scheduled_items s ON s.id = c.agent_id
WHERE c.is_agent = 1
"""

# --- Rollback: back to the agents table as the live chats and jobs have it.
# Steps roll back in reverse, so these run after the table is renamed back:
# edits made since the migration carry over, agents created since are added,
# agents deleted since stay deleted; then every agent chat's settings and job go.
_AGENT_CHAT_JOB = """
FROM conversations c JOIN scheduled_items s ON s.id = c.agent_id
WHERE c.is_agent = 1
"""
_RESTORE_FIELDS = f"""
    name = c.standing_name,
    description = c.standing_description,
    system_prompt = c.standing_instructions,
    schedule = s.schedule,
    timezone = COALESCE(s.timezone, 'UTC'),
    enabled = CASE WHEN s.paused_reason = 'disabled' THEN 0 ELSE 1 END,
    tool_permissions = CASE WHEN s.grants = '["*"]' THEN NULL ELSE s.grants END,
    model = COALESCE(s.model, c.model),
    updated_at = c.updated_at,
    next_run_at = CASE
        WHEN s.paused_reason = 'disabled' OR s.next_run_at >= '{NEVER}' THEN NULL
        ELSE s.next_run_at
    END,
    last_viewed_at = c.standing_viewed_at,
    budget_limit = s.budget_usd,
    fresh_context = s.fresh_context,
    system_type = c.standing_type
"""
_RESTORE_EDITS = f"""
UPDATE autonomous_agents SET {_RESTORE_FIELDS}
FROM conversations c JOIN scheduled_items s ON s.id = c.agent_id
WHERE c.is_agent = 1 AND s.id = autonomous_agents.id
"""
_RESTORE_NEW = f"""
INSERT INTO autonomous_agents (
    id, user_id, conversation_id, name, description, system_prompt, schedule, timezone,
    enabled, tool_permissions, model, created_at, updated_at, next_run_at, last_viewed_at,
    budget_limit, fresh_context, system_type
)
SELECT
    s.id, s.user_id, c.id, c.standing_name, c.standing_description, c.standing_instructions,
    s.schedule, COALESCE(s.timezone, 'UTC'),
    CASE WHEN s.paused_reason = 'disabled' THEN 0 ELSE 1 END,
    CASE WHEN s.grants = '["*"]' THEN NULL ELSE s.grants END,
    COALESCE(s.model, c.model), s.created_at, c.updated_at,
    CASE
        WHEN s.paused_reason = 'disabled' OR s.next_run_at >= '{NEVER}' THEN NULL
        ELSE s.next_run_at
    END,
    c.standing_viewed_at, s.budget_usd, s.fresh_context, c.standing_type
{_AGENT_CHAT_JOB} AND s.id NOT IN (SELECT id FROM autonomous_agents)
"""
_DROP_DELETED = (
    "DELETE FROM autonomous_agents WHERE conversation_id IS NOT NULL "
    "AND conversation_id NOT IN (SELECT id FROM conversations)"
)
_CLEAR_ALL_SETTINGS = """
UPDATE conversations SET standing_name = NULL, standing_instructions = NULL,
    standing_type = NULL, standing_description = NULL, standing_viewed_at = NULL
WHERE is_agent = 1
"""
_DROP_JOBS = """
DELETE FROM scheduled_items
WHERE id IN (SELECT agent_id FROM conversations WHERE is_agent = 1 AND agent_id IS NOT NULL)
"""
_NOTHING = "SELECT 1"  # an apply with nothing to do (its rollback restores)

steps = [
    step(_COPY_JOBS, _DROP_JOBS),
    step(_COPY_SETTINGS, _CLEAR_ALL_SETTINGS),
    step(_NOTHING, _DROP_DELETED),
    step(_NOTHING, _RESTORE_NEW),
    step(_NOTHING, _RESTORE_EDITS),
    step(
        "ALTER TABLE autonomous_agents RENAME TO _autonomous_agents_0080",
        "ALTER TABLE _autonomous_agents_0080 RENAME TO autonomous_agents",
    ),
    step(_VIEW, "DROP VIEW autonomous_agents"),
]
