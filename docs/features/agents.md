# Autonomous Agents

Autonomous agents run on cron schedules to perform tasks independently. Each agent has a dedicated conversation showing its activity and can request approval for dangerous operations.

## Overview

The autonomous agents feature enables:
- **Scheduled execution**: Agents run automatically based on cron schedules
- **Tool permissions**: Control which tools each agent can use
- **Approval workflow**: Dangerous operations require user approval before execution
- **Agent-to-agent communication**: Agents can trigger other agents via the `trigger_agent` tool
- **Command Center**: Dashboard UI for managing agents and approvals

### When a prompt-only agent suffices

Many watcher/digest-style features (periodically check something, summarize it, notify)
need **no new code and no new tool** — just an agent with a crafted system prompt on a cron
schedule. The default toolset (`web_search`, `fetch_url`, `kv_store`, auto-namespaced per
agent) already covers "fetch, compare against remembered state, report". Before writing a
bespoke tool for a recurring notifier, check whether a prompt-only agent can do it.

Prompt guidance for these agents:
- Make **line 1 of the response a plain-text headline** — the push-notification body is the
  first line of the agent's response (truncated to ~160 chars).
- Pair `fresh_context` with `kv_store` so the agent keeps state across runs (last value seen,
  rolling history) rather than re-deriving it every time.
- Forbid writing guessed/placeholder data to `kv_store` on a fetch failure, and state units
  and formats explicitly so the model does not silently transform values.

## Architecture

### Database Schema

The feature adds three tables:

```sql
-- Autonomous agents
autonomous_agents (
    id PRIMARY KEY,
    user_id REFERENCES users(id),
    conversation_id REFERENCES conversations(id),
    name NOT NULL,
    description,
    system_prompt,
    schedule,
    timezone DEFAULT 'UTC',
    enabled DEFAULT 1,
    tool_permissions,
    model DEFAULT 'gemini-3-flash-preview',
    budget_limit,
    created_at NOT NULL,
    updated_at NOT NULL,
    last_run_at,
    next_run_at,
    last_viewed_at,
    fresh_context DEFAULT 0,   -- 0038: run without prior history (report-style agents)
    system_type,               -- 0039: system-managed agents, e.g. 'daily_briefing'
    UNIQUE(user_id, name)
)

-- Approval requests (blocks execution until resolved or expired)
agent_approval_requests (
    id PRIMARY KEY,
    agent_id REFERENCES autonomous_agents(id),
    user_id REFERENCES users(id),
    tool_name NOT NULL,
    tool_args,
    description NOT NULL,
    status DEFAULT 'pending',
    created_at NOT NULL,
    resolved_at,
    expires_at
)

-- Execution history
agent_executions (
    id PRIMARY KEY,
    agent_id REFERENCES autonomous_agents(id),
    status NOT NULL,
    trigger_type NOT NULL,
    triggered_by_agent_id,
    started_at NOT NULL,
    completed_at,
    error_message
)
```

Conversations are extended with `is_agent` and `agent_id` fields.

### Backend Modules

| Module | Purpose |
|--------|---------|
| `src/db/models/agent.py` | Database CRUD for agents, approvals, executions |
| `src/api/routes/agents.py` | REST API endpoints |
| `src/agent/executor.py` | Agent execution engine |
| `src/agent/permissions.py` | Tool permission checking |
| `src/agent/compaction.py` | Conversation compaction logic |
| `src/agent/daily_briefing.py` | Stock prompt for the system-managed Daily Briefing agent |
| `src/agent/retry.py` | Transient failure retry logic (used per model call by the graph) |
| `src/agent/dev_scheduler.py` | Development mode scheduler |
| `scripts/run_agent_scheduler.py` | Production scheduler script |

### Frontend Modules

| Module | Purpose |
|--------|---------|
| `web/src/core/agents.ts` | Navigation and state management |
| `web/src/components/CommandCenter.ts` | Dashboard UI |
| `web/src/components/AgentEditor.ts` | Create/edit modal |
| `web/src/styles/components/agents.css` | Styling |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/agents` | GET | List user's agents |
| `/api/agents` | POST | Create agent (auto-creates conversation) |
| `/api/agents/<id>` | GET | Get agent details |
| `/api/agents/<id>` | PATCH | Update agent |
| `/api/agents/<id>` | DELETE | Delete agent + conversation |
| `/api/agents/<id>/run` | POST | Manual trigger |
| `/api/agents/<id>/mark-viewed` | POST | Mark agent's conversation as viewed |
| `/api/agents/<id>/executions` | GET | Execution history |
| `/api/agents/<id>/conversation/sync` | GET | Sync agent conversation state |
| `/api/agents/command-center` | GET | Dashboard data |
| `/api/agents/approvals` | GET | All pending approvals |
| `/api/ai-assist/parse-schedule` | POST | Helper to parse/validate cron strings |
| `/api/ai-assist/enhance-prompt` | POST | AI helper to refine system prompts |
| `/api/approvals/<id>/approve` | POST | Approve request |
| `/api/approvals/<id>/reject` | POST | Reject request |

## Tool Permissions

Agents are configured with `tool_permissions`; the tool table, permission semantics, the three layers that decide availability, and the checklist for adding a tool are in [Agent Tools](agent-tools.md).

## LLM-Driven Approval System

Agents decide when to request approval using the `request_approval` tool. The agent's system prompt includes guidelines for when approval is appropriate:

- Destructive or irreversible actions
- External communication (sending emails, messages)
- Operations that modify important data
- Anything the user should be aware of before proceeding

When an agent calls `request_approval`:

1. Execution halts immediately via `ApprovalRequestedException`
2. An approval request is created in the database with an expiration
3. The agent's status changes to `waiting_approval`
4. The user sees the request in the Command Center
5. On approval: Agent re-runs from the beginning with access to the approval state
6. On rejection: Execution fails with an error message

**Note:** Approval requests expire after `AGENT_APPROVAL_TTL_HOURS` (default 24 hours). Expired requests block the agent until resolved or cleaned up.

## Scheduling

### Cron Format

Schedules use standard cron format: `minute hour day-of-month month day-of-week` (e.g., `0 9 * * *` for daily at 9:00 AM).

### Development Mode

In development (`FLASK_ENV=development`), `start_dev_scheduler()` runs a background loop every **60 seconds** (`SCHEDULER_INTERVAL_SECONDS`) to evaluate and execute scheduled agents.

### Production Mode

In production a systemd timer runs `scripts/run_agent_scheduler.py` every minute to check for due agents (see [Scheduled Jobs](../architecture/scheduled-jobs.md)). Never run a scheduler thread inside the web workers.

## Agent Execution Flow

1. **Check pending approvals**: Skip if agent has an unresolved/unexpired approval request
2. **Check budget limit**: Skip if agent has exceeded its daily budget
3. **Compact conversation**: Summarize old messages if `AGENT_COMPACTION_THRESHOLD` is reached
4. **Create execution record**: Track the run in `agent_executions`
5. **Load conversation history**: Get agent's conversation messages (skipped for `fresh_context` agents, which run each turn from a clean slate)
6. **Set up ChatAgent**: Configure with agent's tools and permissions
7. **Run the turn**: `ChatAgent.chat_batch()` in autonomous mode (model calls are retried inside the graph, see below)
8. **Save messages**: Add user trigger and assistant response (with source chips from `extract_read_sources()`, generated files and cost) to the conversation
9. **Update timestamps**: Set `last_run_at` and calculate `next_run_at`

## Conversation Compaction

Before each run, an agent conversation over `AGENT_COMPACTION_THRESHOLD` (50) messages has its older messages replaced by a segmented summary, keeping the latest `AGENT_COMPACTION_KEEP_RECENT` (10). Unlike chat compaction this is destructive, and a failed summary skips compaction rather than dropping messages. Details: [Conversation Context](../architecture/conversation-context.md#autonomous-agent-compaction).

## Transient Failure Retries

Transient model errors (connection errors, timeouts, rate limits, 503s) are retried with exponential backoff and jitter **per model call** inside the graph chat node (`AGENT_MAX_RETRIES`, `AGENT_RETRY_BASE_DELAY_SECONDS`, `AGENT_RETRY_MAX_DELAY_SECONDS`). The executor deliberately has no whole-run retry: replaying a turn would re-execute non-idempotent tools (Todoist/Calendar writes, WhatsApp sends). See [Agent Graph](../architecture/agent-graph.md#chat-node-and-transient-error-retries).

## Budget Limits

Agents can have per-agent daily spending limits to prevent runaway costs.

**Configuration:**
- Set `budget_limit` in the agent editor (USD per day)
- Leave empty for unlimited spending (default: `AGENT_DEFAULT_DAILY_BUDGET_USD`)
- Agents that exceed their daily budget are skipped until the next day

**How it works:**
1. Before execution, check today's total spending for the agent
2. If spending exceeds `budget_limit`, skip execution with an error message
3. Spending resets at midnight UTC each day

## Command Center UI

The Command Center dashboard shows:

- **Pending Approvals**: Cards with approve/reject buttons
- **Your Agents**: Grid of agent cards with status, schedule, unread count
- **Recent Activity**: List of recent executions

### Sidebar Badge

The sidebar shows:
- Unread count badge (total new messages across agent conversations)
- Waiting indicator (pulsing dot when agents need approval)

## Creating an Agent

1. Click the robot icon in the sidebar or navigate to Command Center
2. Click "New Agent"
3. Fill in:
   - **Name**: Unique identifier
   - **Description**: What the agent does
   - **Schedule**: Cron expression or preset
   - **Timezone**: For schedule interpretation
   - **System Prompt**: Agent's goals and behavior
   - **Tool Permissions**: Which tools the agent can use
   - **Enabled**: Toggle to activate/deactivate

## Agent-to-Agent Communication

Agents can trigger other agents using the `trigger_agent` tool:

```python
@tool
def trigger_agent(agent_name: str, message: str = "Continue") -> str:
    """Trigger another autonomous agent to run."""
```

Circular dependencies are prevented via a `trigger_chain` in the agent context - an agent cannot trigger an agent that's already in the current execution chain.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_APPROVAL_TTL_HOURS` | 24 | Hours until approval requests expire |
| `AGENT_EXECUTION_TIMEOUT_MINUTES` | 10 | Max execution time before considered stale |
| `AGENT_EXECUTION_COOLDOWN_SECONDS` | 5 | Minimum seconds between manual runs |
| `AGENT_MAX_TRIGGER_DEPTH` | 3 | Maximum agent-to-agent trigger chain length (cycles are always blocked) |
| `AGENT_COMPACTION_THRESHOLD` | 50 | Message count to trigger compaction |
| `AGENT_COMPACTION_KEEP_RECENT` | 10 | Messages to keep after compaction |
| `AGENT_MAX_RETRIES` | 3 | Max retry attempts for transient failures |
| `AGENT_RETRY_BASE_DELAY_SECONDS` | 1.0 | Initial retry delay |
| `AGENT_RETRY_MAX_DELAY_SECONDS` | 30.0 | Maximum retry delay |
| `AGENT_DEFAULT_DAILY_BUDGET_USD` | 0 | Default daily budget (0 = unlimited) |
| `AGENT_MAX_TOOL_RETRIES` | 2 | Max consecutive tool errors before LLM is told to give up |
| `GUNICORN_MAX_REQUESTS` | 1000 | Recycle workers after N requests (memory leak safety net) |
| `GUNICORN_MAX_REQUESTS_JITTER` | 50 | Random jitter to stagger worker recycling |

Agents also use existing configuration for:
- `GEMINI_API_KEY` - LLM access
- `DATABASE_PATH` - Agent storage
- Integration credentials (Todoist, Calendar) if used

### Feature Toggle

Agents are always available for authenticated users. No feature flag required.

## Testing

### Visual Tests

Run visual regression tests:

```bash
cd web && npx playwright test tests/visual/agents.visual.ts
```

Update snapshots:

```bash
cd web && npx playwright test tests/visual/agents.visual.ts --update-snapshots
```

### Test Endpoints (E2E)

In E2E test mode, these endpoints control agent state:

- `POST /test/set-agents-command-center` - Set mock command center data
- `POST /test/clear-agents-config` - Reset to defaults

## Routing Race Condition Prevention

When users rapidly navigate between different views (conversations, planner, agents), async operations
from the first view might complete after the user has already switched to another view. Without
protection, this would render stale content in the wrong view.

### The Navigation Token Pattern

The solution uses a navigation token that increments on each navigation:

```typescript
// In store.ts
navigationToken: number;
startNavigation: () => number;       // Increments and returns new token
isNavigationValid: (token) => boolean; // Checks if token matches current
```

### Usage in Navigation Functions

Each async navigation function follows this pattern:

```typescript
async function navigateToAgents(): Promise<void> {
  // 1. Get token BEFORE async operations
  const navToken = store.startNavigation();

  // 2. Start async load
  const data = await agents.getCommandCenter();

  // 3. Check token AFTER async completes - cancel if invalid
  if (!store.isNavigationValid(navToken)) {
    log.info('User navigated away, aborting render');
    return;
  }

  // 4. Safe to render
  renderCommandCenter(data);
}
```

### Why This Works

- Each navigation increments the token
- If user clicks Agents → Planner → Agents rapidly:
  - First Agents click: token = 1
  - Planner click: token = 2
  - Second Agents click: token = 3
- When first Agents load completes (token was 1, current is 3) → cancelled
- Only the final navigation renders

### Adding New Screens

When adding a new screen:
1. Import `useStore` and call `startNavigation()` before async operations
2. After async completes, check `isNavigationValid(token)` before rendering
3. If invalid, return early without rendering

This pattern automatically handles race conditions with all other screens
without needing screen-specific flag checks.

### Input Area Visibility During Navigation

The agents view hides the input area (since it's not a chat). When navigating away from agents to
other views, the input area must be restored. This is handled by `ensureInputAreaVisible()` in
[MessageInput.ts](../../web/src/components/MessageInput.ts).

**The bug scenario:**
1. User is in agents view (input area hidden)
2. User navigates to planner while it's loading
3. Planner sets `isAgentsView = false` but the async fetch hasn't completed
4. User navigates to a conversation before planner finishes
5. Neither navigation restores the input area → input box invisible

**The fix:**
- `ensureInputAreaVisible()` is a defensive helper that removes `hidden` class from input area
- Called in multiple places to ensure coverage regardless of navigation path:
  - `navigateToPlanner()` - when coming from agents view
  - `switchToConversation()` - defensive call for all conversation switches
  - `createConversation()` - defensive call for new conversations
  - `leaveAgentsView()` - primary restore point when leaving agents
  - `leavePlannerView()` - ensures input visible after leaving planner

**Regression tests:** [navigation-input-focus.test.ts](../../web/tests/unit/navigation-input-focus.test.ts)

## Future Enhancements

- Agent conversation header status and run button (the header currently has back + edit, `AgentConversationHeader.ts`)
- Inline approval display in agent conversations
- Agent execution logs with detailed output
- Webhook triggers for agents
- Agent templates library

## Key Files

- [executor.py](../../src/agent/executor.py) - `execute_agent()`, agent context, trigger chain
- [routes/agents.py](../../src/api/routes/agents.py) - REST endpoints, `_PROMPT_TOOL_DESCRIPTIONS`
- [models/agent.py](../../src/db/models/agent.py) - agents, approvals, executions
- [dev_scheduler.py](../../src/agent/dev_scheduler.py) / [run_agent_scheduler.py](../../scripts/run_agent_scheduler.py) - scheduling
- [CommandCenter.ts](../../web/src/components/CommandCenter.ts), [AgentEditor.ts](../../web/src/components/AgentEditor.ts), [core/agents.ts](../../web/src/core/agents.ts) - UI
- [test_agents.py](../../tests/unit/test_agents.py), [test_routes_agents.py](../../tests/integration/test_routes_agents.py), [agents.spec.ts](../../web/tests/e2e/agents.spec.ts)

## See Also

- [Agent Tools](agent-tools.md) - tool table, permissions, adding a tool, K/V store, browser
- [Agent Graph](../architecture/agent-graph.md) - the loop every run goes through
- [Push Notifications](push-notifications.md) - how agents notify the user
- [Scheduled Jobs](../architecture/scheduled-jobs.md) - production scheduling
