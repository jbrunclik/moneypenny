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
Rollback restores the table (changes made through the view since are lost).
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

_CLEAR_SETTINGS = """
UPDATE conversations SET standing_name = NULL, standing_instructions = NULL,
    standing_type = NULL, standing_description = NULL, standing_viewed_at = NULL
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

steps = [
    step(_COPY_JOBS, "DELETE FROM scheduled_items WHERE id IN (SELECT id FROM autonomous_agents)"),
    step(_COPY_SETTINGS, _CLEAR_SETTINGS),
    step(
        "ALTER TABLE autonomous_agents RENAME TO _autonomous_agents_0080",
        "ALTER TABLE _autonomous_agents_0080 RENAME TO autonomous_agents",
    ),
    step(_VIEW, "DROP VIEW autonomous_agents"),
]
