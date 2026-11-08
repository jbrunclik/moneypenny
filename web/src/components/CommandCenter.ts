/**
 * Command Center: one list of every job - items set from chats and standing
 * jobs (agents) - with each job's schedule, next run, status and recent runs
 * (standing chats phase 3). Approvals sit above the list; the server orders
 * the jobs (needs attention first, then soonest).
 */

import { createElement } from '../utils/dom';
import {
  CHECK_ICON,
  CLOCK_ICON,
  CLOSE_ICON,
  COMMAND_CENTER_ICON,
  HISTORY_ICON,
  LANGUAGE_ICON,
  PLUS_ICON,
  REFRESH_ICON,
  ROBOT_ICON,
  SPORTS_ICON,
  WARNING_ICON,
  createIconElement,
  iconNodes,
  setIcon,
  type IconHtml,
} from '../utils/icons';
import { createEmptyState } from './EmptyState';
import { SCHEDULE_KIND_ICONS } from './messages/delivery-label';
import type { ApprovalRequest, Job, JobRun, JobsOverviewResponse } from '../types/api';

/** What the page asks its controller (core/agents.ts) to do */
export interface CommandCenterHandlers {
  onRefresh: () => Promise<void>;
  onApproval: (approvalId: string, approved: boolean) => Promise<void>;
  onOpenChat: (conversationId: string) => Promise<void>;
  onRun: (job: Job) => Promise<void>;
  onPause: (job: Job) => Promise<void>;
  onResume: (job: Job) => Promise<void>;
  onCancel: (job: Job) => Promise<void>;
  onEdit: (job: Job) => void;
  onNewAgent: () => void;
}

const AREA_ICONS: Record<string, IconHtml> = {
  agents: ROBOT_ICON,
  sports: SPORTS_ICON,
  language: LANGUAGE_ICON,
};

/**
 * Render loading state for command center.
 */
export function renderCommandCenterLoading(): HTMLDivElement {
  const el = document.createElement('div');
  // A skeleton of the real layout (header, sections, rows) so the page
  // doesn't jump from a centred text line to the list
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
      createElement('span', { class: 'visually-hidden' }, ['Loading jobs…']),
      line('heading'),
      line('section'),
      createElement('div', { class: 'jobs-list' }, [card(), card(), card()]),
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

/** "in 2h", "5m ago", ... */
function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(Math.abs(diffMs) / 60000);
  const hours = Math.round(minutes / 60);
  const days = Math.round(hours / 24);
  const amount = minutes < 60 ? `${minutes} min` : hours < 24 ? `${hours}h` : `${days}d`;
  if (diffMs < 0) return `in ${amount}`;
  return minutes < 1 ? 'just now' : `${amount} ago`;
}

/** Observability strip: the standing jobs' runs and cost over the week (null without runs). */
function renderStatsStrip(stats: JobsOverviewResponse['stats']): HTMLDivElement | null {
  if (stats.total_runs <= 0) return null;
  const successRate = Math.round((stats.total_completed / stats.total_runs) * 100);
  return createElement('div', { class: 'command-center-stats' }, [
    createElement('span', { class: 'stats-window' }, [`Last ${stats.days} days`]),
    createElement('span', { class: 'stats-item' }, [`${stats.total_runs} run${stats.total_runs === 1 ? '' : 's'}`]),
    createElement('span', { class: 'stats-item' }, [`${successRate}% success`]),
    stats.total_failed > 0 && createElement('span', { class: 'stats-item stats-item--failed' }, [`${stats.total_failed} failed`]),
    createElement('span', { class: 'stats-item stats-item--cost', title: 'Cost of the jobs’ own runs' }, [stats.total_cost_display]),
  ]);
}

function iconLabelButton(attributes: Record<string, string>, icon: IconHtml, label: string): HTMLButtonElement {
  return createElement('button', attributes, [iconNodes(icon), createElement('span', {}, [label])]);
}

/** An approval request: who asks, what for, its schedule, approve or reject. */
function renderApprovalCard(approval: ApprovalRequest, job: Job | undefined, onApproval: CommandCenterHandlers['onApproval']): HTMLDivElement {
  const approve = iconLabelButton({ class: 'btn btn-approve', title: 'Approve' }, CHECK_ICON, 'Approve');
  const reject = iconLabelButton({ class: 'btn btn-reject', title: 'Reject' }, CLOSE_ICON, 'Reject');
  approve.addEventListener('click', () => void onApproval(approval.id, true));
  reject.addEventListener('click', () => void onApproval(approval.id, false));
  return createElement('div', { class: 'approval-card' }, [
    createElement('div', { class: 'approval-card-header' }, [
      createElement('span', { class: 'approval-agent-name' }, [approval.agent_name]),
      createElement('span', { class: 'approval-time' }, [relativeTime(approval.created_at)]),
    ]),
    createElement('div', { class: 'approval-card-content' }, [
      createElement('p', { class: 'approval-description' }, [approval.description]),
      createElement('div', { class: 'approval-meta' }, [
        createElement('div', { class: 'approval-tool' }, [createElement('span', { class: 'tool-name' }, [approval.tool_name])]),
        !!job && createElement('span', { class: 'approval-schedule' }, [iconNodes(CLOCK_ICON), ` ${job.when}`]),
      ]),
    ]),
    createElement('div', { class: 'approval-card-actions' }, [approve, reject]),
  ]);
}

function renderApprovalsSection(data: JobsOverviewResponse, onApproval: CommandCenterHandlers['onApproval']): HTMLDivElement | null {
  if (data.pending_approvals.length === 0) return null;
  const jobsById = new Map(data.jobs.map((j) => [j.id, j]));
  return createElement('div', { class: 'command-center-section command-center-section--approvals has-approvals' }, [
    sectionTitle(WARNING_ICON, 'Pending Approvals', { count: data.pending_approvals.length, className: 'badge--warning' }),
    createElement(
      'div',
      { class: 'approvals-list' },
      data.pending_approvals.map((a) => renderApprovalCard(a, jobsById.get(a.agent_id), onApproval))
    ),
  ]);
}

/** Why the job needs a look, or '' when all is well. */
function jobStatus(job: Job): string {
  if (job.has_pending_approval) return 'waiting for approval';
  if (job.status === 'paused') return job.paused_reason === 'failures' ? 'paused after failing' : 'paused';
  if (job.recent_runs[0]?.status === 'failed') return 'failed';
  return '';
}

function jobMeta(job: Job): string {
  const parts = [job.when];
  if (job.next_run_at && job.status !== 'paused') parts.push(`next ${relativeTime(job.next_run_at)}`);
  if (job.standing && job.runs_7d > 0) parts.push(`7d: ${job.runs_7d} run${job.runs_7d === 1 ? '' : 's'} · ${job.cost_7d_display ?? ''}`);
  if (job.area === 'chat') parts.push(`in "${job.conversation_title}"`);
  return parts.join(' · ');
}

function runItem(run: JobRun): HTMLElement {
  return createElement('li', { class: `job-run-item job-run-item--${run.status}` }, [
    createElement('span', { class: 'job-run-when' }, [relativeTime(run.started_at)]),
    createElement('span', { class: 'job-run-status' }, [run.status === 'completed' ? 'ok' : run.status.replace('_', ' ')]),
    !!run.error && createElement('span', { class: 'job-run-error' }, [run.error]),
  ]);
}

/** The audit trail: the job's newest runs, collapsed under a summary. */
function recentRuns(job: Job): HTMLElement | null {
  if (job.recent_runs.length === 0) return null;
  return createElement('details', { class: 'job-runs' }, [
    createElement('summary', {}, [iconNodes(HISTORY_ICON), ' Recent runs']),
    createElement('ul', {}, job.recent_runs.map(runItem)),
  ]);
}

function actionButton(className: string, label: string, onClick: () => void): HTMLButtonElement {
  const button = createElement('button', { type: 'button', class: `job-action ${className}` }, [label]);
  button.addEventListener('click', (e) => {
    e.stopPropagation();
    onClick();
  });
  return button;
}

function jobActions(job: Job, h: CommandCenterHandlers): HTMLButtonElement[] {
  const actions: HTMLButtonElement[] = [];
  if (job.standing && job.status !== 'running') actions.push(actionButton('job-run', 'Run', () => void h.onRun(job)));
  if ((job.kind === 'watcher' || job.kind === 'recurring') && job.status !== 'running') {
    actions.push(
      job.status === 'paused'
        ? actionButton('job-resume', 'Resume', () => void h.onResume(job))
        : actionButton('job-pause', 'Pause', () => void h.onPause(job))
    );
  }
  if (job.editable) actions.push(actionButton('job-edit', 'Edit', () => h.onEdit(job)));
  // An agent's own job is deleted with the agent (its editor); anything else
  // set in a chat - an agent's chat included - can be cancelled here
  const agentJob = job.editable || job.system_type !== null;
  if (!agentJob) actions.push(actionButton('job-cancel', 'Cancel', () => void h.onCancel(job)));
  return actions;
}

function renderJobRow(job: Job, h: CommandCenterHandlers): HTMLElement {
  const status = jobStatus(job);
  const icon = AREA_ICONS[job.area] ?? SCHEDULE_KIND_ICONS[job.kind];
  // Paused by the user is a state, not a problem: no attention border
  const attention = status !== '' && status !== 'paused';
  const row = createElement('div', {
    class: `job-row${attention ? ' job-row--attention' : ''}`,
    'data-job-id': job.id,
    tabindex: '0',
    role: 'button',
    'aria-label': `Open the chat of ${job.title}`,
  }, [
    createIconElement('job-icon', icon),
    createElement('div', { class: 'job-body' }, [
      createElement('div', { class: 'job-head' }, [
        createElement('span', { class: 'job-title' }, [job.title]),
        job.system_type !== null && createElement('span', { class: 'job-builtin', title: 'Schedule and delivery are set in Settings' }, ['Built-in']),
        job.unread_count > 0 && createElement('span', { class: 'job-unread' }, [job.unread_count > 99 ? '99+' : String(job.unread_count)]),
        !!status && createElement('span', { class: 'job-status' }, [status]),
      ]),
      createElement('div', { class: 'job-meta' }, [jobMeta(job)]),
      recentRuns(job),
    ]),
    createElement('div', { class: 'job-actions' }, jobActions(job, h)),
  ]);
  // The row opens the job's chat; buttons and the runs summary do their own thing
  row.addEventListener('click', (e) => {
    if ((e.target as HTMLElement).closest('button, details')) return;
    void h.onOpenChat(job.conversation_id);
  });
  row.addEventListener('keydown', (e) => {
    if (e.target !== row || (e.key !== 'Enter' && e.key !== ' ')) return;
    e.preventDefault();
    void h.onOpenChat(job.conversation_id);
  });
  return row;
}

function renderJobsSection(data: JobsOverviewResponse, h: CommandCenterHandlers): HTMLDivElement {
  const section = createElement('div', { class: 'command-center-section command-center-section--jobs' }, [
    sectionTitle(CLOCK_ICON, 'Jobs', { count: data.jobs.length }),
  ]);
  if (data.jobs.length === 0) {
    const cta = createElement('button', { class: 'btn-create-agent' });
    setIcon(cta, PLUS_ICON);
    cta.append(createElement('span', {}, ['New Agent']));
    cta.addEventListener('click', () => h.onNewAgent());
    const empty = createEmptyState({
      icon: CLOCK_ICON,
      title: 'Nothing scheduled yet',
      hint: 'Reminders, watchers and agents you set up show here.',
      cta,
    });
    empty.classList.add('jobs-empty');
    section.appendChild(empty);
    return section;
  }
  section.appendChild(createElement('div', { class: 'jobs-list' }, data.jobs.map((j) => renderJobRow(j, h))));
  return section;
}

function renderHeader(h: CommandCenterHandlers): HTMLDivElement {
  const newAgentBtn = createElement('button', { class: 'btn-new-agent', title: 'Create new agent' });
  setIcon(newAgentBtn, PLUS_ICON);
  newAgentBtn.appendChild(createElement('span', {}, ['New Agent']));
  newAgentBtn.addEventListener('click', () => h.onNewAgent());
  const refreshBtn = createElement('button', { class: 'btn-refresh', title: 'Refresh' });
  setIcon(refreshBtn, REFRESH_ICON);
  refreshBtn.addEventListener('click', () => void h.onRefresh());
  return createElement('div', { class: 'command-center-header' }, [
    createElement('div', { class: 'command-center-title' }, [
      createIconElement('command-center-icon', COMMAND_CENTER_ICON),
      createElement('h2', {}, ['Command Center']),
    ]),
    createElement('div', { class: 'command-center-header-actions' }, [newAgentBtn, refreshBtn]),
  ]);
}

/**
 * Render the command center: header, week stats, approvals, the job list.
 */
export function renderCommandCenter(data: JobsOverviewResponse, handlers: CommandCenterHandlers): HTMLDivElement {
  return createElement('div', { class: 'command-center' }, [
    renderHeader(handlers),
    renderStatsStrip(data.stats),
    renderApprovalsSection(data, handlers.onApproval),
    renderJobsSection(data, handlers),
  ]);
}
