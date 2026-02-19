# Autonomous Agents

Autonomous agents run on cron schedules to perform tasks independently. Each agent has a dedicated conversation showing its activity and can request approval for dangerous operations.

## Overview

The autonomous agents feature enables:
- **Scheduled execution**: Agents run automatically based on cron schedules
- **Tool permissions**: Control which tools each agent can use
- **Approval workflow**: Dangerous operations require user approval before execution
- **Agent-to-agent communication**: Agents can trigger other agents via the `trigger_agent` tool
- **Command Center**: Dashboard UI for managing agents and approvals

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
| `src/agent/retry.py` | Transient failure retry logic |
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
| `/api/agents/evaluate-schedules` | POST | Evaluate all schedules (admin/manual) |
| `/api/agents/parse-schedule` | POST | Helper to parse/validate cron strings |
| `/api/agents/enhance-prompt` | POST | AI helper to refine system prompts |
| `/api/approvals/<id>/approve` | POST | Approve request |
| `/api/approvals/<id>/reject` | POST | Reject request |

## Tool Permissions

### Available Tools

Agents are configured with specific tool permissions. Some tools are always available to ensure basic functionality and agent-to-agent interaction.

| Tool | Description | Availability |
|------|-------------|--------------|
| `web_search` | Web search queries | Always available |
| `fetch_url` | Fetch content from URLs | Always available |
| `retrieve_file` | Retrieve files from conversations | Always available |
| `request_approval` | Request user approval | Always available |
| `trigger_agent` | Trigger another agent | Always available |
| `generate_image` | AI image generation | Requires `GEMINI_API_KEY` |
| `execute_code` | Code execution in sandbox | Requires `CODE_SANDBOX_ENABLED` |
| `todoist` | Todoist task management | Requires user integration |
| `google_calendar` | Calendar events | Requires user integration |
| `whatsapp` | WhatsApp notifications | Requires app config + user phone |

**Permission settings:**
- `tool_permissions=null` (default): All available tools enabled
- `tool_permissions=[]`: Only "always available" tools enabled
- `tool_permissions=["todoist", ...]`: Only specified tools + "always available" tools

### Adding a New Tool

When adding a new tool for autonomous agents, update these locations:

**Backend (required):**

1. **`src/agent/tools/<tool_name>.py`** - Tool implementation with `@tool` decorator
2. **`src/agent/tools/__init__.py`** - Register in `get_tools_for_request()`, add `is_<tool>_available()` function
3. **`src/agent/tool_display.py`** - Add to `TOOL_METADATA` dict for UI display (icon, label, description)
4. **`src/api/routes/agents.py`** - Add to `_PROMPT_TOOL_DESCRIPTIONS` dict for prompt enhancer

**Frontend (required):**

5. **`web/src/components/AgentEditor.ts`** - Add to `BASE_TOOLS` array for permissions UI
6. **`web/src/utils/icons.ts`** - Add icon if needed (referenced by `TOOL_METADATA`)

**Configuration (if needed):**

7. **`src/config.py`** - Add configuration variables
8. **`.env.example`** - Document new config variables

**For integration tools requiring user connection:**

9. **`src/api/routes/agents.py`** - Add `_is_<tool>_connected_for_user(user)` function that checks both app config AND user connection status

**Documentation:**

10. **`docs/features/agents.md`** - Update the Available Tools table above
11. **`docs/features/integrations.md`** - Add integration documentation (for external service tools)

**Tests:**

12. **`tests/unit/test_<tool>.py`** - Unit tests for the tool
13. **`web/tests/visual/agents.visual.ts`** - Update visual snapshots if UI changed

### LLM-Driven Approval System

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

In development (`FLASK_ENV=development`), a background thread runs every **60 seconds** to evaluate and execute scheduled agents.

### Production Mode

In production, use the systemd timer which runs every minute to check for due agents.

## Agent Execution Flow

1. **Check pending approvals**: Skip if agent has an unresolved/unexpired approval request
2. **Check budget limit**: Skip if agent has exceeded its daily budget
3. **Compact conversation**: Summarize old messages if `AGENT_COMPACTION_THRESHOLD` is reached
4. **Create execution record**: Track the run in `agent_executions`
5. **Load conversation history**: Get agent's conversation messages
6. **Set up ChatAgent**: Configure with agent's tools and permissions
7. **Run conversation**: Execute with retry logic for transient failures
8. **Save messages**: Add user trigger and assistant response to conversation
9. **Update timestamps**: Set `last_run_at` and calculate `next_run_at`

## Conversation Compaction

Long-running agents can accumulate many messages over time, potentially exceeding LLM context limits. Compaction automatically summarizes older messages to keep conversations manageable.

**How it works:**
1. Before each execution, check if message count exceeds `AGENT_COMPACTION_THRESHOLD` (default: 50)
2. If over threshold, generate a summary of older messages using a fast LLM
3. Replace old messages with a single summary message
4. Keep the most recent `AGENT_COMPACTION_KEEP_RECENT` messages (default: 10)

The summary captures:
- Key actions taken by the agent
- Important information discovered
- Ongoing tasks or goals
- Any errors or issues encountered

## Transient Failure Retries

Network issues, rate limits, and temporary service unavailability can cause agent executions to fail. The executor automatically retries transient failures with exponential backoff.

**Retry behavior:**
- Retries connection errors, timeouts, and rate limit responses
- Uses exponential backoff with jitter to prevent thundering herd
- Configurable via `AGENT_MAX_RETRIES`, `AGENT_RETRY_BASE_DELAY_SECONDS`, `AGENT_RETRY_MAX_DELAY_SECONDS`

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
| `AGENT_COMPACTION_THRESHOLD` | 50 | Message count to trigger compaction |
| `AGENT_COMPACTION_KEEP_RECENT` | 10 | Messages to keep after compaction |
| `AGENT_MAX_RETRIES` | 3 | Max retry attempts for transient failures |
| `AGENT_RETRY_BASE_DELAY_SECONDS` | 1.0 | Initial retry delay |
| `AGENT_RETRY_MAX_DELAY_SECONDS` | 30.0 | Maximum retry delay |
| `AGENT_DEFAULT_DAILY_BUDGET_USD` | 0 | Default daily budget (0 = unlimited) |
| `AGENT_MAX_TOOL_RETRIES` | 2 | Max consecutive tool errors before LLM is told to give up |
| `AGENT_PLANNING_ENABLED` | true | Enable planning node for complex multi-step requests |
| `AGENT_PLANNING_MIN_LENGTH` | 200 | Minimum message length (chars) to trigger LLM planning classifier |
| `AGENT_CHECKPOINTING_ENABLED` | true | Enable LangGraph MemorySaver checkpointing for state persistence |

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

- Agent conversation header showing status and run button
- Inline approval display in agent conversations
- Agent execution logs with detailed output
- Webhook triggers for agents
- Agent templates library
