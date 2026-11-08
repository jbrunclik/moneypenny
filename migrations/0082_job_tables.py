"""Job names in the schema: the agent facade's tables and columns go.

- agent_executions -> job_runs and agent_approval_requests -> job_approvals,
  created fresh (agent_id -> item_id, triggered_by_agent_id ->
  triggered_by_job_id) so no foreign key points at the dropped backup.
- conversations.agent_id -> job_id, users.daily_briefing_agent_id ->
  daily_briefing_job_id. conversations.job_id keeps the column's inert
  REFERENCES clause (foreign keys are never enabled; dropping it would mean
  rebuilding conversations).
- The autonomous_agents view and its _autonomous_agents_0080 backup go.

Rollback restores both tables (rows carried back), the column names, an EMPTY
backup table and the view: 0080's own rollback then rebuilds the agents from
the chats and jobs. Steps roll back in reverse, so the view comes back last.
"""

from typing import Any

from yoyo import step

__depends__ = {"0081_grant_levels"}

NEVER = "9999-12-31T00:00:00.000000+00:00"

# --- autonomous_agents as 0080 made it (rollback only)
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

_BACKUP = [
    """CREATE TABLE "_autonomous_agents_0080" (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            conversation_id TEXT REFERENCES conversations(id),
            name TEXT NOT NULL,
            description TEXT,
            system_prompt TEXT,
            schedule TEXT,
            timezone TEXT DEFAULT 'UTC',
            enabled INTEGER DEFAULT 1,
            tool_permissions TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_run_at TEXT,
            next_run_at TEXT,
            last_viewed_at TEXT,
            model TEXT DEFAULT 'gemini-3-flash-preview', budget_limit REAL DEFAULT NULL,
            fresh_context INTEGER NOT NULL DEFAULT 0, system_type TEXT,
            UNIQUE(user_id, name)
        )""",
    'CREATE INDEX idx_agents_user ON "_autonomous_agents_0080"(user_id)',
    'CREATE INDEX idx_agents_next_run ON "_autonomous_agents_0080"(next_run_at) WHERE enabled = 1',
    'CREATE INDEX idx_agents_conversation ON "_autonomous_agents_0080"(conversation_id)',
]

_OLD_RUNS = [
    """CREATE TABLE agent_executions (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL REFERENCES "_autonomous_agents_0080"(id),
            status TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            triggered_by_agent_id TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            error_message TEXT
        )""",
    "CREATE INDEX idx_executions_agent ON agent_executions(agent_id)",
    "CREATE INDEX idx_executions_status ON agent_executions(status)",
    "CREATE INDEX idx_executions_agent_started ON agent_executions(agent_id, started_at DESC)",
]

_OLD_APPROVALS = [
    """CREATE TABLE agent_approval_requests (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL REFERENCES "_autonomous_agents_0080"(id),
            user_id TEXT NOT NULL REFERENCES users(id),
            tool_name TEXT NOT NULL,
            tool_args TEXT,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            expires_at TEXT
        )""",
    "CREATE INDEX idx_approvals_user_pending ON agent_approval_requests(user_id, status)",
    "CREATE INDEX idx_approvals_agent ON agent_approval_requests(agent_id)",
    "CREATE INDEX idx_approvals_expires ON agent_approval_requests(status, expires_at) "
    "WHERE status = 'pending'",
]

# --- The job tables
_JOB_RUNS = [
    """CREATE TABLE job_runs (
            id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL REFERENCES scheduled_items(id),
            status TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            triggered_by_job_id TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            error_message TEXT
        )""",
    "CREATE INDEX idx_job_runs_item ON job_runs(item_id)",
    "CREATE INDEX idx_job_runs_status ON job_runs(status)",
    "CREATE INDEX idx_job_runs_item_started ON job_runs(item_id, started_at DESC)",
]

_JOB_APPROVALS = [
    """CREATE TABLE job_approvals (
            id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL REFERENCES scheduled_items(id),
            user_id TEXT NOT NULL REFERENCES users(id),
            tool_name TEXT NOT NULL,
            tool_args TEXT,
            description TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            expires_at TEXT
        )""",
    "CREATE INDEX idx_job_approvals_user_pending ON job_approvals(user_id, status)",
    "CREATE INDEX idx_job_approvals_item ON job_approvals(item_id)",
    "CREATE INDEX idx_job_approvals_expires ON job_approvals(status, expires_at) "
    "WHERE status = 'pending'",
]

_RUN_COLUMNS = "id, {item}, status, trigger_type, {by}, started_at, completed_at, error_message"
_NEW_RUN_COLUMNS = _RUN_COLUMNS.format(item="item_id", by="triggered_by_job_id")
_OLD_RUN_COLUMNS = _RUN_COLUMNS.format(item="agent_id", by="triggered_by_agent_id")
_APPROVAL_COLUMNS = (
    "id, {item}, user_id, tool_name, tool_args, description, status, created_at, "
    "resolved_at, expires_at"
)
_NEW_APPROVAL_COLUMNS = _APPROVAL_COLUMNS.format(item="item_id")
_OLD_APPROVAL_COLUMNS = _APPROVAL_COLUMNS.format(item="agent_id")


def _run_all(statements: list[str]) -> Any:
    def apply(conn: Any) -> None:
        cursor = conn.cursor()
        for sql in statements:
            cursor.execute(sql)

    return apply


steps = [
    step("DROP VIEW autonomous_agents", _VIEW),
    step('DROP TABLE "_autonomous_agents_0080"', _run_all(_BACKUP)),
    step(_run_all(_JOB_RUNS), "DROP TABLE job_runs"),
    step(_run_all(_JOB_APPROVALS), "DROP TABLE job_approvals"),
    step(
        f"INSERT INTO job_runs ({_NEW_RUN_COLUMNS}) SELECT {_OLD_RUN_COLUMNS} FROM agent_executions",
        f"INSERT INTO agent_executions ({_OLD_RUN_COLUMNS}) SELECT {_NEW_RUN_COLUMNS} FROM job_runs",
    ),
    step(
        f"INSERT INTO job_approvals ({_NEW_APPROVAL_COLUMNS}) "
        f"SELECT {_OLD_APPROVAL_COLUMNS} FROM agent_approval_requests",
        f"INSERT INTO agent_approval_requests ({_OLD_APPROVAL_COLUMNS}) "
        f"SELECT {_NEW_APPROVAL_COLUMNS} FROM job_approvals",
    ),
    step("DROP TABLE agent_executions", _run_all(_OLD_RUNS)),
    step("DROP TABLE agent_approval_requests", _run_all(_OLD_APPROVALS)),
    step(
        "ALTER TABLE conversations RENAME COLUMN agent_id TO job_id",
        "ALTER TABLE conversations RENAME COLUMN job_id TO agent_id",
    ),
    step(
        "ALTER TABLE users RENAME COLUMN daily_briefing_agent_id TO daily_briefing_job_id",
        "ALTER TABLE users RENAME COLUMN daily_briefing_job_id TO daily_briefing_agent_id",
    ),
]
