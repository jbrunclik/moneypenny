"""Run proposals: an unattended run's request for a yes is a proposal too.

One approval mechanism, step 2. A proposal gains its origin ('chat' or
'run'), the run's job and execution, an expiry (runs wait up to
AGENT_APPROVAL_TTL_HOURS; chat messages never expire them) and a consumed
flag (an approved call runs once). Pending job_approvals copy in - same id,
linked to their "[approval-request:<id>]" message - and job_approvals goes
(production held none). Rolling back recreates the empty table.
"""

from yoyo import step

__depends__ = {"0087_proposal_sync_on_change"}

_JOB_APPROVALS = """CREATE TABLE job_approvals (
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
        )"""

steps = [
    step(
        "ALTER TABLE proposals ADD COLUMN origin TEXT NOT NULL DEFAULT 'chat'",
        "ALTER TABLE proposals DROP COLUMN origin",
    ),
    step("ALTER TABLE proposals ADD COLUMN job_id TEXT", "ALTER TABLE proposals DROP COLUMN job_id"),
    step(
        "ALTER TABLE proposals ADD COLUMN execution_id TEXT",
        "ALTER TABLE proposals DROP COLUMN execution_id",
    ),
    step(
        "ALTER TABLE proposals ADD COLUMN expires_at TEXT",
        "ALTER TABLE proposals DROP COLUMN expires_at",
    ),
    step(
        "ALTER TABLE proposals ADD COLUMN consumed INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE proposals DROP COLUMN consumed",
    ),
    step(
        "CREATE INDEX idx_proposals_job_state ON proposals(job_id, state)",
        "DROP INDEX IF EXISTS idx_proposals_job_state",
    ),
    step(
        """INSERT INTO proposals (id, user_id, conversation_id, message_id, request_id, kind,
               summary, details, options, state, created_at, origin, job_id, expires_at)
           SELECT ja.id, ja.user_id, si.conversation_id,
               (SELECT m.id FROM messages m
                WHERE m.content LIKE '[approval-request:' || ja.id || ']%' LIMIT 1),
               '',
               CASE ja.tool_name WHEN 'edit_standing_chat' THEN 'edit_agent' ELSE 'agent_action' END,
               ja.description, '{}',
               json_array(json_object(
                   'label', 'Approve', 'description', '',
                   'payload', CASE ja.tool_name
                       WHEN 'edit_standing_chat' THEN json_object(
                           'job_id', ja.item_id, 'changes', json(coalesce(ja.tool_args, '{}')))
                       ELSE json_object('tool', ja.tool_name, 'args', json(coalesce(ja.tool_args, '{}')))
                   END)),
               'pending', ja.created_at, 'run', ja.item_id, ja.expires_at
           FROM job_approvals ja JOIN scheduled_items si ON si.id = ja.item_id
           WHERE ja.status = 'pending' AND si.conversation_id IS NOT NULL""",
        "DELETE FROM proposals WHERE origin = 'run'",
    ),
    step("DROP TABLE job_approvals", _JOB_APPROVALS),
]
