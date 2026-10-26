/**
 * Command Center component.
 * Displays the agent dashboard with agents list and pending approvals.
 * Agent status (last execution, unreads) is shown inline on each agent card.
 */

import { escapeHtml } from '../utils/dom';
import { CHECK_ICON, CHEVRON_DOWN_ICON, CLOCK_ICON, CLOSE_ICON, COMMAND_CENTER_ICON, EDIT_ICON, HISTORY_ICON, PLAY_ICON, PLUS_ICON, REFRESH_ICON, ROBOT_ICON, WARNING_ICON } from '../utils/icons';
import { renderEmptyStateHtml } from './EmptyState';
import type { Agent, AgentExecution, AgentWindowStats, ApprovalRequest, CommandCenterResponse } from '../types/api';

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
  // A skeleton of the real layout (header, sections, agent cards) so the
  // page doesn't jump from a centred text line to the dashboard
  el.className = 'command-center command-center--loading';
  el.setAttribute('aria-busy', 'true');
  const card = `
    <div class="command-center-skeleton-card">
      <div class="command-center-skeleton-line command-center-skeleton-line--title"></div>
      <div class="command-center-skeleton-line"></div>
      <div class="command-center-skeleton-line command-center-skeleton-line--short"></div>
    </div>`;
  el.innerHTML = `
    <div class="command-center-loading">
      <span class="visually-hidden">Loading agents…</span>
      <div class="command-center-skeleton-line command-center-skeleton-line--heading"></div>
      <div class="command-center-skeleton-line command-center-skeleton-line--section"></div>
      <div class="agents-list">${card.repeat(3)}</div>
    </div>
  `;
  return el;
}

/** Observability strip: runs + cost over the trailing week (null without runs). */
function renderStatsStrip(stats: CommandCenterResponse['stats']): HTMLDivElement | null {
  if (!stats || stats.total_runs <= 0) return null;
  const successRate = Math.round((stats.total_completed / stats.total_runs) * 100);
  const strip = document.createElement('div');
  strip.className = 'command-center-stats';
  strip.innerHTML = `
    <span class="stats-window">Last ${stats.days} days</span>
    <span class="stats-item">${stats.total_runs} run${stats.total_runs === 1 ? '' : 's'}</span>
    <span class="stats-item">${successRate}% success</span>
    ${stats.total_failed > 0 ? `<span class="stats-item stats-item--failed">${stats.total_failed} failed</span>` : ''}
    <span class="stats-item stats-item--cost" title="Total agent cost over the window">${escapeHtml(stats.total_cost_display)}</span>
  `;
  return strip;
}

/** Pending Approvals section (always shown as a control panel). */
function renderApprovalsSection(data: CommandCenterResponse, onApproval: ApprovalCallback): HTMLDivElement {
  const approvalsSection = document.createElement('div');
  approvalsSection.className = `command-center-section command-center-section--approvals ${data.pending_approvals.length > 0 ? 'has-approvals' : ''}`;

  if (data.pending_approvals.length === 0) {
    approvalsSection.innerHTML = `
      <h3 class="section-title">
        <span class="section-icon">${CHECK_ICON}</span>
        Approvals
      </h3>
      <p class="section-empty-note">No pending approvals.</p>
    `;
    return approvalsSection;
  }

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
  return approvalsSection;
}

/** Agents section: a card per agent, or an empty state offering to create one. */
function renderAgentsSection(
  data: CommandCenterResponse,
  statsByAgent: Map<string, AgentWindowStats>,
  onAgentSelect: AgentSelectCallback,
  onAgentRun: AgentRunCallback,
  onAgentEdit: AgentEditCallback,
  onNewAgent: NewAgentCallback,
): HTMLDivElement {
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
    const holder = document.createElement('div');
    holder.innerHTML = renderEmptyStateHtml({
      icon: ROBOT_ICON,
      title: 'No agents yet',
      hint: 'Create an agent to automate tasks.',
      ctaHtml: `<button class="btn-create-agent">${PLUS_ICON}<span>Create Agent</span></button>`,
    });
    const emptyState = holder.firstElementChild as HTMLElement;
    emptyState.querySelector('.btn-create-agent')?.addEventListener('click', () => {
      onNewAgent();
    });
    agentsSection.appendChild(emptyState);
    return agentsSection;
  }

  const agentsList = document.createElement('div');
  agentsList.className = 'agents-list';
  data.agents.forEach(agent => {
    agentsList.appendChild(
      renderAgentCard(agent, onAgentSelect, onAgentRun, onAgentEdit, statsByAgent.get(agent.id))
    );
  });
  agentsSection.appendChild(agentsList);
  return agentsSection;
}

/** Recent Executions section (collapsible, shows last 10 executions); null when there are none. */
function renderExecutionsSection(data: CommandCenterResponse): HTMLDivElement | null {
  if (!data.recent_executions || data.recent_executions.length === 0) return null;
  const executionsSection = document.createElement('div');
  executionsSection.className = 'command-center-section command-center-section--executions';
  executionsSection.innerHTML = `
    <h3 class="section-title section-title--collapsible" data-collapsed="false">
      <span class="section-icon">${HISTORY_ICON}</span>
      Recent Activity
      <span class="badge">${data.recent_executions.length}</span>
      <span class="section-toggle">${CHEVRON_DOWN_ICON}</span>
    </h3>
  `;

  // Show the latest 3 by default; "Show all" reveals the rest
  const executions = data.recent_executions.slice(0, 10);
  const executionsList = document.createElement('div');
  executionsList.className = 'executions-list executions-list--limited';
  executions.forEach(execution => {
    executionsList.appendChild(renderExecutionItem(execution, data.agents));
  });
  executionsSection.appendChild(executionsList);

  if (executions.length > 3) {
    const showAllBtn = document.createElement('button');
    showAllBtn.className = 'executions-show-all';
    showAllBtn.textContent = `Show all (${executions.length})`;
    showAllBtn.addEventListener('click', () => {
      executionsList.classList.remove('executions-list--limited');
      showAllBtn.remove();
    });
    executionsSection.appendChild(showAllBtn);
  }

  // Toggle collapsed state (chevron rotates via CSS)
  const titleEl = executionsSection.querySelector('.section-title--collapsible');
  titleEl?.addEventListener('click', () => {
    const isCollapsed = titleEl.getAttribute('data-collapsed') === 'true';
    titleEl.setAttribute('data-collapsed', isCollapsed ? 'false' : 'true');
    executionsList.classList.toggle('collapsed', !isCollapsed);
    executionsSection.querySelector('.executions-show-all')?.classList.toggle('hidden', !isCollapsed);
  });
  return executionsSection;
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
    void onRefresh();
  });
  header.querySelector('.btn-new-agent')?.addEventListener('click', () => {
    onNewAgent();
  });
  el.appendChild(header);

  const stats = data.stats;
  const strip = renderStatsStrip(stats);
  if (strip) el.appendChild(strip);

  const statsByAgent = new Map((stats?.per_agent ?? []).map((s) => [s.agent_id, s]));
  el.appendChild(renderApprovalsSection(data, onApproval));
  el.appendChild(renderAgentsSection(data, statsByAgent, onAgentSelect, onAgentRun, onAgentEdit, onNewAgent));
  const executionsSection = renderExecutionsSection(data);
  if (executionsSection) el.appendChild(executionsSection);

  return el;
}

/** The status dot next to an agent's name (pending approval, disabled, last run outcome). */
function agentStatusIndicatorHtml(agent: Agent): string {
  if (agent.has_pending_approval) {
    return `<span class="status-indicator status-indicator--warning" title="Waiting for approval"></span>`;
  }
  if (!agent.enabled) {
    return `<span class="status-indicator status-indicator--disabled" title="Disabled"></span>`;
  }
  if (agent.last_execution_status === 'failed') {
    return `<span class="status-indicator status-indicator--error" title="Last run failed"></span>`;
  }
  if (agent.last_execution_status === 'completed') {
    return `<span class="status-indicator status-indicator--success" title="Last run completed"></span>`;
  }
  return '';
}

/** An agent's schedule, last run and next run as display text ('' when absent). */
function agentScheduleTexts(agent: Agent): { scheduleText: string; lastRunText: string; nextRunText: string } {
  const scheduleText = agent.schedule ? formatSchedule(agent.schedule) : 'Manual only';
  const lastRunText = agent.last_run_at ? formatRelativeTime(new Date(agent.last_run_at)) : '';
  const nextRunText =
    agent.next_run_at && agent.enabled && agent.schedule ? formatRelativeTime(new Date(agent.next_run_at)) : '';
  return { scheduleText, lastRunText, nextRunText };
}

/**
 * System-managed agents get a badge so it's clear the app owns their
 * lifecycle; extend the map for future special agent types.
 */
function agentSystemBadgeHtml(agent: Agent): string {
  const systemTypeLabels: Record<string, string> = {
    daily_briefing: 'Built-in',
  };
  return agent.system_type
    ? `<span class="agent-system-badge" title="Built-in agent - schedule and delivery are configured in Settings">${escapeHtml(systemTypeLabels[agent.system_type] ?? 'Built-in')}</span>`
    : '';
}

/** The agent's runs and cost over the stats window ('' when it did not run). */
function agentWindowStatsHtml(windowStats: AgentWindowStats | undefined): string {
  if (!windowStats || windowStats.runs <= 0) return '';
  const failed = windowStats.failed > 0
    ? ` · <span class="agent-window-stats--failed">${windowStats.failed} failed</span>`
    : '';
  return `<span class="agent-window-stats" title="Runs and cost over the last 7 days">7d: ${windowStats.runs} run${windowStats.runs === 1 ? '' : 's'}${failed} · ${escapeHtml(windowStats.cost_display)}</span>`;
}

/**
 * Render an agent card.
 */
function renderAgentCard(
  agent: Agent,
  onSelect: AgentSelectCallback,
  onRun: AgentRunCallback,
  onEdit: AgentEditCallback,
  windowStats?: AgentWindowStats,
): HTMLDivElement {
  const card = document.createElement('div');
  card.className = `agent-card ${agent.enabled ? '' : 'agent-card--disabled'}`;
  card.dataset.agentId = agent.id;

  const statusIndicator = agentStatusIndicatorHtml(agent);

  // Unread badge
  const unreadBadge = agent.unread_count > 0
    ? `<span class="unread-badge">${agent.unread_count > 99 ? '99+' : agent.unread_count}</span>`
    : '';

  const { scheduleText, lastRunText, nextRunText } = agentScheduleTexts(agent);
  const systemBadge = agentSystemBadgeHtml(agent);

  card.innerHTML = `
    <div class="agent-card-header">
      <div class="agent-card-title-row">
        ${statusIndicator}
        <span class="agent-name">${escapeHtml(agent.name)}</span>
        ${systemBadge}
        ${unreadBadge}
      </div>
      <div class="agent-card-actions">
        ${agent.system_type ? '' : `
        <button class="btn-icon btn-edit" title="Edit agent" aria-label="Edit agent">
          ${EDIT_ICON}
        </button>`}
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
      ${agentWindowStatsHtml(windowStats)}
    </div>
  `;

  // Click on card to select agent
  card.addEventListener('click', (e) => {
    // Don't trigger if clicking on action buttons
    if ((e.target as HTMLElement).closest('.agent-card-actions')) {
      return;
    }
    void onSelect(agent.id);
  });

  // Edit button
  card.querySelector('.btn-edit')?.addEventListener('click', (e) => {
    e.stopPropagation();
    onEdit(agent);
  });

  // Run button
  card.querySelector('.btn-run')?.addEventListener('click', (e) => {
    e.stopPropagation();
    void onRun(agent.id, agent.name);
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
    void onApproval(approval.id, true);
  });

  // Reject button
  card.querySelector('.btn-reject')?.addEventListener('click', () => {
    void onApproval(approval.id, false);
  });

  return card;
}

/** Whether a cron field is a plain number (not a step, range or list). */
function isPlainNumber(val: string): boolean {
  return /^\d+$/.test(val);
}

/** HH:MM of plain-number cron hour and minute fields. */
function clockTime(hour: string, minute: string): string {
  const h = parseInt(hour, 10);
  const m = parseInt(minute, 10);
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
}

/** Step schedules: every N hours or every N minutes. */
function formatStepSchedule(minute: string, hour: string): string | null {
  if (hour.startsWith('*/') && minute !== '*') {
    const interval = parseInt(hour.slice(2), 10);
    if (!isNaN(interval)) {
      return `Every ${interval}h at :${minute.padStart(2, '0')}`;
    }
  }
  if (minute.startsWith('*/')) {
    const interval = parseInt(minute.slice(2), 10);
    if (!isNaN(interval)) {
      return `Every ${interval} min`;
    }
  }
  return null;
}

/** Daily, hourly, weekly and weekday schedules. */
function formatCalendarSchedule(
  minute: string,
  hour: string,
  dayOfMonth: string,
  month: string,
  dayOfWeek: string
): string | null {
  const atTime = isPlainNumber(hour) && isPlainNumber(minute);
  // Daily at specific time - only if hour is a plain number
  if (dayOfMonth === '*' && month === '*' && dayOfWeek === '*' && atTime) {
    return `Daily at ${clockTime(hour, minute)}`;
  }
  if (hour === '*' && isPlainNumber(minute)) {
    return `Every hour at :${minute.padStart(2, '0')}`;
  }
  // Weekly - only if dayOfWeek is a plain number
  if (isPlainNumber(dayOfWeek)) {
    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    return `Weekly on ${days[parseInt(dayOfWeek, 10)] || dayOfWeek}`;
  }
  if (dayOfWeek === '1-5' && atTime) {
    return `Weekdays at ${clockTime(hour, minute)}`;
  }
  return null;
}

/**
 * Format a cron schedule to human-readable text (the raw expression when
 * it is none of the common shapes).
 */
export function formatSchedule(schedule: string): string {
  // Simple cron parsing - could be enhanced with a library
  const parts = schedule.split(' ');
  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;
  if (
    parts.length !== 5 ||
    minute === undefined ||
    hour === undefined ||
    dayOfMonth === undefined ||
    month === undefined ||
    dayOfWeek === undefined
  ) {
    return schedule;
  }
  return (
    formatStepSchedule(minute, hour) ??
    formatCalendarSchedule(minute, hour, dayOfMonth, month, dayOfWeek) ??
    schedule
  );
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

