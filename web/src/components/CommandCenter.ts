/**
 * Command Center component.
 * Displays the agent dashboard with agents list and pending approvals.
 * Agent status (last execution, unreads) is shown inline on each agent card.
 */

import { escapeHtml } from '../utils/dom';
import { CHECK_ICON, CLOCK_ICON, CLOSE_ICON, COMMAND_CENTER_ICON, EDIT_ICON, HISTORY_ICON, PLAY_ICON, PLUS_ICON, REFRESH_ICON, ROBOT_ICON, WARNING_ICON } from '../utils/icons';
import type { Agent, AgentExecution, ApprovalRequest, CommandCenterResponse } from '../types/api';

type RefreshCallback = () => Promise<void>;
type ApprovalCallback = (approvalId: string, approved: boolean) => Promise<void>;
type AgentSelectCallback = (agentId: string) => Promise<void>;
type AgentRunCallback = (agentId: string, agentName: string) => Promise<void>;
type AgentEditCallback = (agent: Agent) => void;
type NewAgentCallback = () => void;

/**
 * Render loading state for command center.
 */
export function renderCommandCenterLoading(): HTMLDivElement {
  const el = document.createElement('div');
  el.className = 'command-center command-center--loading';
  el.innerHTML = `
    <div class="command-center-loading">
      <div class="loading-spinner"></div>
      <p>Loading agents...</p>
    </div>
  `;
  return el;
}

/**
 * Render the command center dashboard.
 */
export function renderCommandCenter(
  data: CommandCenterResponse,
  onRefresh: RefreshCallback,
  onApproval: ApprovalCallback,
  onAgentSelect: AgentSelectCallback,
  onAgentRun: AgentRunCallback,
  onAgentEdit: AgentEditCallback,
  onNewAgent: NewAgentCallback,
): HTMLDivElement {
  const el = document.createElement('div');
  el.className = 'command-center';

  // Header
  const header = document.createElement('div');
  header.className = 'command-center-header';
  header.innerHTML = `
    <div class="command-center-title">
      <span class="command-center-icon">${COMMAND_CENTER_ICON}</span>
      <h2>Command Center</h2>
    </div>
    <div class="command-center-header-actions">
      <button class="btn-new-agent" title="Create new agent">
        ${PLUS_ICON}
        <span>New Agent</span>
      </button>
      <button class="btn-refresh" title="Refresh">
        ${REFRESH_ICON}
      </button>
    </div>
  `;
  header.querySelector('.btn-refresh')?.addEventListener('click', () => {
    onRefresh();
  });
  header.querySelector('.btn-new-agent')?.addEventListener('click', () => {
    onNewAgent();
  });
  el.appendChild(header);

  // Pending Approvals section (always shown as a control panel)
  const approvalsSection = document.createElement('div');
  approvalsSection.className = `command-center-section command-center-section--approvals ${data.pending_approvals.length > 0 ? 'has-approvals' : ''}`;

  if (data.pending_approvals.length > 0) {
    approvalsSection.innerHTML = `
      <h3 class="section-title">
        <span class="section-icon">${WARNING_ICON}</span>
        Pending Approvals
        <span class="badge badge--warning">${data.pending_approvals.length}</span>
      </h3>
    `;

    const approvalsList = document.createElement('div');
    approvalsList.className = 'approvals-list';
    data.pending_approvals.forEach(approval => {
      // Find the agent to get schedule context
      const agent = data.agents.find(a => a.id === approval.agent_id);
      approvalsList.appendChild(renderApprovalCard(approval, agent, onApproval));
    });
    approvalsSection.appendChild(approvalsList);
  } else {
    approvalsSection.innerHTML = `
      <h3 class="section-title">
        <span class="section-icon">${CHECK_ICON}</span>
        Approvals
      </h3>
      <div class="approvals-empty">
        <p>No pending approvals</p>
        <p class="text-muted">Agents that require permission for certain actions will appear here.</p>
      </div>
    `;
  }
  el.appendChild(approvalsSection);

  // Agents section
  const agentsSection = document.createElement('div');
  agentsSection.className = 'command-center-section command-center-section--agents';
  agentsSection.innerHTML = `
    <h3 class="section-title">
      <span class="section-icon">${ROBOT_ICON}</span>
      Agents
      <span class="badge">${data.agents.length}</span>
    </h3>
  `;

  if (data.agents.length === 0) {
    const emptyState = document.createElement('div');
    emptyState.className = 'empty-state';
    emptyState.innerHTML = `
      <p>No agents yet.</p>
      <p class="text-muted">Create an agent to automate tasks.</p>
      <button class="btn-create-agent">
        ${PLUS_ICON}
        <span>Create Agent</span>
      </button>
    `;
    emptyState.querySelector('.btn-create-agent')?.addEventListener('click', () => {
      onNewAgent();
    });
    agentsSection.appendChild(emptyState);
  } else {
    const agentsList = document.createElement('div');
    agentsList.className = 'agents-list';
    data.agents.forEach(agent => {
      agentsList.appendChild(renderAgentCard(agent, onAgentSelect, onAgentRun, onAgentEdit));
    });
    agentsSection.appendChild(agentsList);
  }
  el.appendChild(agentsSection);

  // Recent Executions section (collapsible, shows last 10 executions)
  if (data.recent_executions && data.recent_executions.length > 0) {
    const executionsSection = document.createElement('div');
    executionsSection.className = 'command-center-section command-center-section--executions';
    executionsSection.innerHTML = `
      <h3 class="section-title section-title--collapsible" data-collapsed="true">
        <span class="section-icon">${HISTORY_ICON}</span>
        Recent Activity
        <span class="badge">${data.recent_executions.length}</span>
        <span class="section-toggle">▶</span>
      </h3>
    `;

    const executionsList = document.createElement('div');
    executionsList.className = 'executions-list collapsed';
    data.recent_executions.slice(0, 10).forEach(execution => {
      executionsList.appendChild(renderExecutionItem(execution, data.agents));
    });
    executionsSection.appendChild(executionsList);

    // Toggle collapsed state
    const titleEl = executionsSection.querySelector('.section-title--collapsible');
    titleEl?.addEventListener('click', () => {
      const isCollapsed = titleEl.getAttribute('data-collapsed') === 'true';
      titleEl.setAttribute('data-collapsed', isCollapsed ? 'false' : 'true');
      executionsList.classList.toggle('collapsed', !isCollapsed);
      const toggle = titleEl.querySelector('.section-toggle');
      if (toggle) {
        toggle.textContent = isCollapsed ? '▼' : '▶';
      }
    });

    el.appendChild(executionsSection);
  }

  return el;
}

/**
 * Render an agent card.
 */
function renderAgentCard(
  agent: Agent,
  onSelect: AgentSelectCallback,
  onRun: AgentRunCallback,
  onEdit: AgentEditCallback,
): HTMLDivElement {
  const card = document.createElement('div');
  card.className = `agent-card ${agent.enabled ? '' : 'agent-card--disabled'}`;
  card.dataset.agentId = agent.id;

  // Status indicators (dot next to name)
  let statusIndicator = '';
  if (agent.has_pending_approval) {
    statusIndicator = `<span class="status-indicator status-indicator--warning" title="Waiting for approval"></span>`;
  } else if (!agent.enabled) {
    statusIndicator = `<span class="status-indicator status-indicator--disabled" title="Disabled"></span>`;
  } else if (agent.last_execution_status === 'failed') {
    statusIndicator = `<span class="status-indicator status-indicator--error" title="Last run failed"></span>`;
  } else if (agent.last_execution_status === 'completed') {
    statusIndicator = `<span class="status-indicator status-indicator--success" title="Last run completed"></span>`;
  }

  // Unread badge
  const unreadBadge = agent.unread_count > 0
    ? `<span class="unread-badge">${agent.unread_count > 99 ? '99+' : agent.unread_count}</span>`
    : '';

  // Schedule display
  let scheduleText = 'Manual only';
  if (agent.schedule) {
    scheduleText = formatSchedule(agent.schedule);
  }

  // Last run display
  let lastRunText = '';
  if (agent.last_run_at) {
    const lastRun = new Date(agent.last_run_at);
    lastRunText = formatRelativeTime(lastRun);
  }

  // Next run display
  let nextRunText = '';
  if (agent.next_run_at && agent.enabled && agent.schedule) {
    const nextRun = new Date(agent.next_run_at);
    nextRunText = formatRelativeTime(nextRun);
  }

  card.innerHTML = `
    <div class="agent-card-header">
      <div class="agent-card-title-row">
        ${statusIndicator}
        <span class="agent-name">${escapeHtml(agent.name)}</span>
        ${unreadBadge}
      </div>
      <div class="agent-card-actions">
        <button class="btn-icon btn-edit" title="Edit agent" aria-label="Edit agent">
          ${EDIT_ICON}
        </button>
        <button class="btn-icon btn-run btn-run-labeled" title="Run now" aria-label="Run agent now">
          ${PLAY_ICON}
          <span class="btn-run-label">Run</span>
        </button>
      </div>
    </div>
    ${agent.description ? `<p class="agent-description">${escapeHtml(agent.description)}</p>` : ''}
    <div class="agent-card-meta">
      <span class="agent-schedule">${escapeHtml(scheduleText)}</span>
      ${lastRunText ? `<span class="agent-last-run">Last: ${escapeHtml(lastRunText)}</span>` : ''}
      ${nextRunText ? `<span class="agent-next-run">Next: ${escapeHtml(nextRunText)}</span>` : ''}
    </div>
  `;

  // Click on card to select agent
  card.addEventListener('click', (e) => {
    // Don't trigger if clicking on action buttons
    if ((e.target as HTMLElement).closest('.agent-card-actions')) {
      return;
    }
    onSelect(agent.id);
  });

  // Edit button
  card.querySelector('.btn-edit')?.addEventListener('click', (e) => {
    e.stopPropagation();
    onEdit(agent);
  });

  // Run button
  card.querySelector('.btn-run')?.addEventListener('click', (e) => {
    e.stopPropagation();
    onRun(agent.id, agent.name);
  });

  return card;
}

/**
 * Render an approval request card.
 */
function renderApprovalCard(
  approval: ApprovalRequest,
  agent: Agent | undefined,
  onApproval: ApprovalCallback,
): HTMLDivElement {
  const card = document.createElement('div');
  card.className = 'approval-card';

  // Format tool args for display if available
  let toolArgsHtml = '';
  if (approval.tool_args && Object.keys(approval.tool_args).length > 0) {
    const argsPreview = Object.entries(approval.tool_args)
      .slice(0, 3) // Show max 3 args
      .map(([key, value]) => {
        const valueStr = typeof value === 'string' ? value : JSON.stringify(value);
        const truncated = valueStr.length > 50 ? valueStr.slice(0, 50) + '...' : valueStr;
        return `<span class="tool-arg"><span class="tool-arg-key">${escapeHtml(key)}:</span> ${escapeHtml(truncated)}</span>`;
      })
      .join('');
    const moreCount = Object.keys(approval.tool_args).length - 3;
    const moreText = moreCount > 0 ? `<span class="tool-args-more">+${moreCount} more</span>` : '';
    toolArgsHtml = `<div class="tool-args">${argsPreview}${moreText}</div>`;
  }

  // Build schedule context from agent data
  let scheduleContextHtml = '';
  if (agent?.schedule) {
    const scheduleText = formatSchedule(agent.schedule);
    scheduleContextHtml = `<span class="approval-schedule" title="Agent schedule: ${escapeHtml(scheduleText)}">${CLOCK_ICON} ${escapeHtml(scheduleText)}</span>`;
  }

  card.innerHTML = `
    <div class="approval-card-header">
      <span class="approval-agent-name">${escapeHtml(approval.agent_name)}</span>
      <span class="approval-time">${formatRelativeTime(new Date(approval.created_at))}</span>
    </div>
    <div class="approval-card-content">
      <p class="approval-description">${escapeHtml(approval.description)}</p>
      <div class="approval-meta">
        <div class="approval-tool">
          <span class="tool-name">${escapeHtml(approval.tool_name)}</span>
        </div>
        ${scheduleContextHtml}
      </div>
      ${toolArgsHtml}
    </div>
    <div class="approval-card-actions">
      <button class="btn btn-approve" title="Approve">
        ${CHECK_ICON}
        <span>Approve</span>
      </button>
      <button class="btn btn-reject" title="Reject">
        ${CLOSE_ICON}
        <span>Reject</span>
      </button>
    </div>
  `;

  // Approve button
  card.querySelector('.btn-approve')?.addEventListener('click', () => {
    onApproval(approval.id, true);
  });

  // Reject button
  card.querySelector('.btn-reject')?.addEventListener('click', () => {
    onApproval(approval.id, false);
  });

  return card;
}

/**
 * Format a cron schedule to human-readable text.
 */
function formatSchedule(schedule: string): string {
  // Simple cron parsing - could be enhanced with a library
  const parts = schedule.split(' ');
  if (parts.length !== 5) return schedule;

  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;

  // Helper to check if a value is a plain number (not a step or range)
  const isPlainNumber = (val: string): boolean => /^\d+$/.test(val);

  // Every N hours (step value like */2)
  if (hour.startsWith('*/') && minute !== '*') {
    const interval = parseInt(hour.slice(2), 10);
    if (!isNaN(interval)) {
      return `Every ${interval}h at :${minute.padStart(2, '0')}`;
    }
  }

  // Every N minutes (step value like */15)
  if (minute.startsWith('*/')) {
    const interval = parseInt(minute.slice(2), 10);
    if (!isNaN(interval)) {
      return `Every ${interval} min`;
    }
  }

  // Daily at specific time - only if hour is a plain number
  if (dayOfMonth === '*' && month === '*' && dayOfWeek === '*' && isPlainNumber(hour) && isPlainNumber(minute)) {
    const h = parseInt(hour, 10);
    const m = parseInt(minute, 10);
    const time = `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
    return `Daily at ${time}`;
  }

  // Every hour
  if (hour === '*' && isPlainNumber(minute)) {
    return `Every hour at :${minute.padStart(2, '0')}`;
  }

  // Weekly - only if dayOfWeek is a plain number or range
  if (dayOfWeek !== '*' && isPlainNumber(dayOfWeek)) {
    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const dayName = days[parseInt(dayOfWeek, 10)] || dayOfWeek;
    return `Weekly on ${dayName}`;
  }

  // Weekday range (1-5)
  if (dayOfWeek === '1-5' && isPlainNumber(hour) && isPlainNumber(minute)) {
    const h = parseInt(hour, 10);
    const m = parseInt(minute, 10);
    const time = `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
    return `Weekdays at ${time}`;
  }

  return schedule;
}

/**
 * Format a date to relative time (e.g., "5 minutes ago").
 */
function formatRelativeTime(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMs < 0) {
    // Future time
    const absDiffMins = Math.abs(diffMins);
    const absDiffHours = Math.abs(diffHours);
    const absDiffDays = Math.abs(diffDays);

    if (absDiffMins < 60) {
      return `in ${absDiffMins} min`;
    } else if (absDiffHours < 24) {
      return `in ${absDiffHours}h`;
    } else {
      return `in ${absDiffDays}d`;
    }
  }

  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString();
}

/**
 * Render a recent execution item.
 */
function renderExecutionItem(
  execution: AgentExecution,
  agents: Agent[],
): HTMLDivElement {
  const item = document.createElement('div');
  item.className = `execution-item execution-item--${execution.status}`;

  // Find agent name
  const agent = agents.find(a => a.id === execution.agent_id);
  const agentName = agent?.name || 'Unknown Agent';

  // Status display
  const statusMap: Record<string, { label: string; icon: string }> = {
    completed: { label: 'Completed', icon: '✓' },
    failed: { label: 'Failed', icon: '✗' },
    running: { label: 'Running', icon: '⟳' },
    waiting_approval: { label: 'Waiting', icon: '⏳' },
  };
  const statusInfo = statusMap[execution.status] || { label: execution.status, icon: '?' };

  // Trigger type display
  const triggerMap: Record<string, string> = {
    scheduled: 'Scheduled',
    manual: 'Manual',
    agent_trigger: 'Agent Chain',
  };
  const triggerLabel = triggerMap[execution.trigger_type] || execution.trigger_type;

  // Duration
  let durationText = '';
  if (execution.completed_at && execution.started_at) {
    const duration = new Date(execution.completed_at).getTime() - new Date(execution.started_at).getTime();
    if (duration < 60000) {
      durationText = `${Math.round(duration / 1000)}s`;
    } else {
      durationText = `${Math.round(duration / 60000)}m`;
    }
  }

  item.innerHTML = `
    <div class="execution-item-main">
      <span class="execution-status">${statusInfo.icon}</span>
      <span class="execution-agent-name">${escapeHtml(agentName)}</span>
      <span class="execution-trigger">${escapeHtml(triggerLabel)}</span>
    </div>
    <div class="execution-item-meta">
      <span class="execution-time">${formatRelativeTime(new Date(execution.started_at))}</span>
      ${durationText ? `<span class="execution-duration">${durationText}</span>` : ''}
    </div>
  `;

  return item;
}
