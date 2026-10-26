/**
 * Command Center component.
 * Displays the agent dashboard with agents list and pending approvals.
 * Agent status (last execution, unreads) is shown inline on each agent card.
 */

import { createElement } from '../utils/dom';
import { CHECK_ICON, CHEVRON_DOWN_ICON, CLOCK_ICON, CLOSE_ICON, COMMAND_CENTER_ICON, EDIT_ICON, HISTORY_ICON, PLAY_ICON, PLUS_ICON, REFRESH_ICON, ROBOT_ICON, WARNING_ICON, createIconButton, createIconElement, iconNodes, setIcon, type IconHtml } from '../utils/icons';
import { createEmptyState } from './EmptyState';
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
  const line = (modifier?: string): HTMLDivElement =>
    createElement('div', {
      class: modifier ? `command-center-skeleton-line command-center-skeleton-line--${modifier}` : 'command-center-skeleton-line',
    });
  const card = (): HTMLDivElement =>
    createElement('div', { class: 'command-center-skeleton-card' }, [line('title'), line(), line('short')]);
  el.appendChild(
    createElement('div', { class: 'command-center-loading' }, [
      createElement('span', { class: 'visually-hidden' }, ['Loading agents…']),
      line('heading'),
      line('section'),
      createElement('div', { class: 'agents-list' }, [card(), card(), card()]),
    ])
  );
  return el;
}

/** A section heading: icon, title and an optional count badge. */
function sectionTitle(icon: IconHtml, title: string, badge?: { count: number; className?: string }): HTMLHeadingElement {
  const heading = createElement('h3', { class: 'section-title' }, [createIconElement('section-icon', icon), ` ${title} `]);
  if (badge) {
    heading.appendChild(createElement('span', { class: badge.className ? `badge ${badge.className}` : 'badge' }, [String(badge.count)]));
  }
  return heading;
}

/** Observability strip: runs + cost over the trailing week (null without runs). */
function renderStatsStrip(stats: CommandCenterResponse['stats']): HTMLDivElement | null {
  if (!stats || stats.total_runs <= 0) return null;
  const successRate = Math.round((stats.total_completed / stats.total_runs) * 100);
  const strip = document.createElement('div');
  strip.className = 'command-center-stats';
  strip.append(
    createElement('span', { class: 'stats-window' }, [`Last ${stats.days} days`]),
    createElement('span', { class: 'stats-item' }, [`${stats.total_runs} run${stats.total_runs === 1 ? '' : 's'}`]),
    createElement('span', { class: 'stats-item' }, [`${successRate}% success`])
  );
  if (stats.total_failed > 0) {
    strip.appendChild(createElement('span', { class: 'stats-item stats-item--failed' }, [`${stats.total_failed} failed`]));
  }
  strip.appendChild(
    createElement('span', { class: 'stats-item stats-item--cost', title: 'Total agent cost over the window' }, [
      stats.total_cost_display,
    ])
  );
  return strip;
}

/** Pending Approvals section (always shown as a control panel). */
function renderApprovalsSection(data: CommandCenterResponse, onApproval: ApprovalCallback): HTMLDivElement {
  const approvalsSection = document.createElement('div');
  approvalsSection.className = `command-center-section command-center-section--approvals ${data.pending_approvals.length > 0 ? 'has-approvals' : ''}`;

  if (data.pending_approvals.length === 0) {
    approvalsSection.append(
      sectionTitle(CHECK_ICON, 'Approvals'),
      createElement('p', { class: 'section-empty-note' }, ['No pending approvals.'])
    );
    return approvalsSection;
  }

  approvalsSection.appendChild(
    sectionTitle(WARNING_ICON, 'Pending Approvals', { count: data.pending_approvals.length, className: 'badge--warning' })
  );
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
  agentsSection.appendChild(sectionTitle(ROBOT_ICON, 'Agents', { count: data.agents.length }));

  if (data.agents.length === 0) {
    const cta = createElement('button', { class: 'btn-create-agent' });
    setIcon(cta, PLUS_ICON);
    cta.append(createElement('span', {}, ['Create Agent']));
    cta.addEventListener('click', () => {
      onNewAgent();
    });
    agentsSection.appendChild(createEmptyState({
      icon: ROBOT_ICON,
      title: 'No agents yet',
      hint: 'Create an agent to automate tasks.',
      cta,
    }));
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
  const executionsTitle = sectionTitle(HISTORY_ICON, 'Recent Activity', { count: data.recent_executions.length });
  executionsTitle.classList.add('section-title--collapsible');
  executionsTitle.dataset.collapsed = 'false';
  executionsTitle.appendChild(createIconElement('section-toggle', CHEVRON_DOWN_ICON));
  executionsSection.appendChild(executionsTitle);

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
  const newAgentBtn = createElement('button', { class: 'btn-new-agent', title: 'Create new agent' });
  setIcon(newAgentBtn, PLUS_ICON);
  newAgentBtn.appendChild(createElement('span', {}, ['New Agent']));
  newAgentBtn.addEventListener('click', () => {
    onNewAgent();
  });
  const refreshBtn = createElement('button', { class: 'btn-refresh', title: 'Refresh' });
  setIcon(refreshBtn, REFRESH_ICON);
  refreshBtn.addEventListener('click', () => {
    void onRefresh();
  });
  header.append(
    createElement('div', { class: 'command-center-title' }, [
      createIconElement('command-center-icon', COMMAND_CENTER_ICON),
      createElement('h2', {}, ['Command Center']),
    ]),
    createElement('div', { class: 'command-center-header-actions' }, [newAgentBtn, refreshBtn])
  );
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
function agentStatusIndicator(agent: Agent): HTMLElement | null {
  const dot = (kind: string, title: string): HTMLElement =>
    createElement('span', { class: `status-indicator status-indicator--${kind}`, title });
  if (agent.has_pending_approval) return dot('warning', 'Waiting for approval');
  if (!agent.enabled) return dot('disabled', 'Disabled');
  if (agent.last_execution_status === 'failed') return dot('error', 'Last run failed');
  if (agent.last_execution_status === 'completed') return dot('success', 'Last run completed');
  return null;
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
function agentSystemBadge(agent: Agent): HTMLElement | null {
  const systemTypeLabels: Record<string, string> = {
    daily_briefing: 'Built-in',
  };
  return agent.system_type
    ? createElement(
        'span',
        { class: 'agent-system-badge', title: 'Built-in agent - schedule and delivery are configured in Settings' },
        [systemTypeLabels[agent.system_type] ?? 'Built-in']
      )
    : null;
}

/** The agent's runs and cost over the stats window (null when it did not run). */
function agentWindowStats(windowStats: AgentWindowStats | undefined): HTMLElement | null {
  if (!windowStats || windowStats.runs <= 0) return null;
  const runs = `7d: ${windowStats.runs} run${windowStats.runs === 1 ? '' : 's'}`;
  const cost = ` · ${windowStats.cost_display}`;
  const text =
    windowStats.failed > 0
      ? [`${runs} · `, createElement('span', { class: 'agent-window-stats--failed' }, [`${windowStats.failed} failed`]), cost]
      : [`${runs}${cost}`];
  return createElement('span', { class: 'agent-window-stats', title: 'Runs and cost over the last 7 days' }, text);
}

/** A button with an icon and a text label (Run, Approve, Reject). */
function iconLabelButton(attributes: Record<string, string>, icon: IconHtml, label: Node): HTMLButtonElement {
  return createElement('button', attributes, [iconNodes(icon), label]);
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

  const { scheduleText, lastRunText, nextRunText } = agentScheduleTexts(agent);

  card.append(
    createElement('div', { class: 'agent-card-header' }, [
      createElement('div', { class: 'agent-card-title-row' }, [
        agentStatusIndicator(agent),
        createElement('span', { class: 'agent-name' }, [agent.name]),
        agentSystemBadge(agent),
        // Unread badge
        agent.unread_count > 0 &&
          createElement('span', { class: 'unread-badge' }, [agent.unread_count > 99 ? '99+' : String(agent.unread_count)]),
      ]),
      createElement('div', { class: 'agent-card-actions' }, [
        !agent.system_type &&
          createIconButton({ class: 'btn-icon btn-edit', title: 'Edit agent', 'aria-label': 'Edit agent' }, EDIT_ICON),
        iconLabelButton(
          { class: 'btn-icon btn-run btn-run-labeled', title: 'Run now', 'aria-label': 'Run agent now' },
          PLAY_ICON,
          createElement('span', { class: 'btn-run-label' }, ['Run'])
        ),
      ]),
    ]),
    ...(agent.description ? [createElement('p', { class: 'agent-description' }, [agent.description])] : []),
    createElement('div', { class: 'agent-card-meta' }, [
      createElement('span', { class: 'agent-schedule' }, [scheduleText]),
      !!lastRunText && createElement('span', { class: 'agent-last-run' }, [`Last: ${lastRunText}`]),
      !!nextRunText && createElement('span', { class: 'agent-next-run' }, [`Next: ${nextRunText}`]),
      agentWindowStats(windowStats),
    ])
  );

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
  let toolArgs: HTMLElement | null = null;
  if (approval.tool_args && Object.keys(approval.tool_args).length > 0) {
    const argsPreview = Object.entries(approval.tool_args)
      .slice(0, 3) // Show max 3 args
      .map(([key, value]) => {
        const valueStr = typeof value === 'string' ? value : JSON.stringify(value);
        const truncated = valueStr.length > 50 ? valueStr.slice(0, 50) + '...' : valueStr;
        return createElement('span', { class: 'tool-arg' }, [
          createElement('span', { class: 'tool-arg-key' }, [`${key}:`]),
          ` ${truncated}`,
        ]);
      });
    const moreCount = Object.keys(approval.tool_args).length - 3;
    toolArgs = createElement('div', { class: 'tool-args' }, [
      ...argsPreview,
      moreCount > 0 && createElement('span', { class: 'tool-args-more' }, [`+${moreCount} more`]),
    ]);
  }

  // Build schedule context from agent data
  const scheduleText = agent?.schedule ? formatSchedule(agent.schedule) : '';
  const scheduleContext =
    !!scheduleText &&
    createElement('span', { class: 'approval-schedule', title: `Agent schedule: ${scheduleText}` }, [
      iconNodes(CLOCK_ICON),
      ` ${scheduleText}`,
    ]);

  card.append(
    createElement('div', { class: 'approval-card-header' }, [
      createElement('span', { class: 'approval-agent-name' }, [approval.agent_name]),
      createElement('span', { class: 'approval-time' }, [formatRelativeTime(new Date(approval.created_at))]),
    ]),
    createElement('div', { class: 'approval-card-content' }, [
      createElement('p', { class: 'approval-description' }, [approval.description]),
      createElement('div', { class: 'approval-meta' }, [
        createElement('div', { class: 'approval-tool' }, [createElement('span', { class: 'tool-name' }, [approval.tool_name])]),
        scheduleContext,
      ]),
      toolArgs,
    ]),
    createElement('div', { class: 'approval-card-actions' }, [
      iconLabelButton({ class: 'btn btn-approve', title: 'Approve' }, CHECK_ICON, createElement('span', {}, ['Approve'])),
      iconLabelButton({ class: 'btn btn-reject', title: 'Reject' }, CLOSE_ICON, createElement('span', {}, ['Reject'])),
    ])
  );

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

  item.append(
    createElement('div', { class: 'execution-item-main' }, [
      createElement('span', { class: 'execution-status' }, [statusInfo.icon]),
      createElement('span', { class: 'execution-agent-name' }, [agentName]),
      createElement('span', { class: 'execution-trigger' }, [triggerLabel]),
    ]),
    createElement('div', { class: 'execution-item-meta' }, [
      createElement('span', { class: 'execution-time' }, [formatRelativeTime(new Date(execution.started_at))]),
      !!durationText && createElement('span', { class: 'execution-duration' }, [durationText]),
    ])
  );

  return item;
}

