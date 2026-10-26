/**
 * Command Center: cron schedules read as plain text, and the dashboard's
 * sections (stats, approvals, agents, recent activity) and agent cards
 * render from the command-center payload.
 */
import { describe, it, expect, vi } from 'vitest';
import { formatSchedule, renderCommandCenter } from '@/components/CommandCenter';
import type { Agent, AgentExecution, ApprovalRequest, CommandCenterResponse } from '@/types/api';

describe('formatSchedule', () => {
  it.each([
    ['0 */2 * * *', 'Every 2h at :00'],
    ['*/15 * * * *', 'Every 15 min'],
    ['30 7 * * *', 'Daily at 07:30'],
    ['5 * * * *', 'Every hour at :05'],
    ['0 9 * * 1', 'Weekly on Mon'],
    ['0 9 * * 9', 'Weekly on 9'],
    ['0 8 * * 1-5', 'Weekdays at 08:00'],
  ])('%s reads as "%s"', (cron, text) => {
    expect(formatSchedule(cron)).toBe(text);
  });

  it.each([['0 9 * *'], ['0 9-17 * * *'], ['0 9 1 * *'], ['0 9 * * 1,3'], ['* */x * * *']])(
    'falls back to the raw expression for %s',
    (cron) => {
      expect(formatSchedule(cron)).toBe(cron);
    }
  );
});

function agent(extra: Partial<Agent> = {}): Agent {
  return {
    id: 'a1',
    name: 'Watcher',
    description: null,
    enabled: true,
    schedule: null,
    unread_count: 0,
    has_pending_approval: false,
    last_execution_status: null,
    last_run_at: null,
    next_run_at: null,
    system_type: null,
    ...extra,
  } as unknown as Agent;
}

function payload(extra: Partial<CommandCenterResponse> = {}): CommandCenterResponse {
  return {
    agents: [],
    pending_approvals: [],
    recent_executions: [],
    total_unread: 0,
    agents_waiting: 0,
    ...extra,
  } as unknown as CommandCenterResponse;
}

function render(data: CommandCenterResponse, callbacks: Partial<Record<string, ReturnType<typeof vi.fn>>> = {}) {
  const cb = {
    refresh: vi.fn(async () => {}),
    approval: vi.fn(async () => {}),
    select: vi.fn(async () => {}),
    run: vi.fn(async () => {}),
    edit: vi.fn(),
    create: vi.fn(),
    ...callbacks,
  };
  const el = renderCommandCenter(data, cb.refresh, cb.approval, cb.select, cb.run, cb.edit, cb.create);
  return { el, cb };
}

describe('renderCommandCenter', () => {
  it('wires the header buttons', () => {
    const { el, cb } = render(payload());
    el.querySelector<HTMLButtonElement>('.btn-refresh')?.click();
    el.querySelector<HTMLButtonElement>('.btn-new-agent')?.click();
    expect(cb.refresh).toHaveBeenCalled();
    expect(cb.create).toHaveBeenCalled();
  });

  it('shows the stats strip only when there were runs', () => {
    expect(render(payload()).el.querySelector('.command-center-stats')).toBeNull();

    const stats = {
      days: 7,
      total_runs: 4,
      total_completed: 3,
      total_failed: 1,
      total_cost_display: '$0.12',
      per_agent: [{ agent_id: 'a1', runs: 1, failed: 0, cost_display: '$0.01' }],
    };
    const { el } = render(payload({ stats, agents: [agent()] } as never));
    const strip = el.querySelector('.command-center-stats')?.textContent ?? '';
    expect(strip).toContain('4 runs');
    expect(strip).toContain('75% success');
    expect(strip).toContain('1 failed');
    expect(el.querySelector('.agent-window-stats')?.textContent).toContain('7d: 1 run');
  });

  it('lists pending approvals with their agent schedule, or an empty note', () => {
    expect(render(payload()).el.querySelector('.section-empty-note')?.textContent).toBe('No pending approvals.');

    const approval = {
      id: 'p1',
      agent_id: 'a1',
      agent_name: 'Watcher',
      description: 'Send the report',
      tool_name: 'send_email',
      tool_args: { to: 'x', subject: 'y', body: 'z'.repeat(60), cc: 'w' },
      created_at: new Date().toISOString(),
    } as unknown as ApprovalRequest;
    const { el, cb } = render(
      payload({ pending_approvals: [approval], agents: [agent({ schedule: '30 7 * * *' })] })
    );
    expect(el.querySelector('.has-approvals')).not.toBeNull();
    expect(el.querySelector('.approval-schedule')?.textContent).toContain('Daily at 07:30');
    expect(el.querySelectorAll('.tool-arg')).toHaveLength(3);
    expect(el.querySelector('.tool-args-more')?.textContent).toBe('+1 more');
    el.querySelector<HTMLButtonElement>('.btn-reject')?.click();
    expect(cb.approval).toHaveBeenCalledWith('p1', false);
  });

  it('offers to create the first agent', () => {
    const { el, cb } = render(payload());
    el.querySelector<HTMLButtonElement>('.btn-create-agent')?.click();
    expect(cb.create).toHaveBeenCalled();
  });

  it('collapses recent activity to three items with a Show all button', () => {
    const executions = Array.from({ length: 5 }, (_, i) => ({
      id: `e${i}`,
      agent_id: 'a1',
      status: 'completed',
      trigger_type: 'manual',
      started_at: new Date().toISOString(),
      completed_at: null,
    })) as unknown as AgentExecution[];
    const { el } = render(payload({ recent_executions: executions, agents: [agent()] }));
    const list = el.querySelector('.executions-list') as HTMLElement;
    expect(list.children).toHaveLength(5);
    expect(list.classList.contains('executions-list--limited')).toBe(true);

    el.querySelector<HTMLButtonElement>('.executions-show-all')?.click();
    expect(list.classList.contains('executions-list--limited')).toBe(false);
    expect(el.querySelector('.executions-show-all')).toBeNull();

    el.querySelector<HTMLElement>('.section-title--collapsible')?.click();
    expect(list.classList.contains('collapsed')).toBe(true);
  });
});

describe('agent cards', () => {
  const card = (a: Agent) => render(payload({ agents: [a] })).el.querySelector('.agent-card') as HTMLElement;

  it.each([
    [{ has_pending_approval: true }, 'status-indicator--warning'],
    [{ enabled: false }, 'status-indicator--disabled'],
    [{ last_execution_status: 'failed' }, 'status-indicator--error'],
    [{ last_execution_status: 'completed' }, 'status-indicator--success'],
  ] as const)('%o shows %s', (extra, cls) => {
    expect(card(agent(extra as Partial<Agent>)).querySelector(`.${cls}`)).not.toBeNull();
  });

  it('shows no status dot for an agent that never ran', () => {
    expect(card(agent()).querySelector('.status-indicator')).toBeNull();
  });

  it('caps the unread badge and shows the schedule and run times', () => {
    const el = card(
      agent({
        unread_count: 150,
        schedule: '*/15 * * * *',
        last_run_at: new Date(Date.now() - 5 * 60000).toISOString(),
        next_run_at: new Date(Date.now() + 10 * 60000 + 1000).toISOString(),
      })
    );
    expect(el.querySelector('.unread-badge')?.textContent).toBe('99+');
    expect(el.querySelector('.agent-schedule')?.textContent).toBe('Every 15 min');
    expect(el.querySelector('.agent-last-run')?.textContent).toBe('Last: 5m ago');
    expect(el.querySelector('.agent-next-run')?.textContent).toMatch(/^Next: in \d+ min$/);
  });

  it('reads "Manual only" without a schedule and hides the next run', () => {
    const el = card(agent({ next_run_at: new Date().toISOString() }));
    expect(el.querySelector('.agent-schedule')?.textContent).toBe('Manual only');
    expect(el.querySelector('.agent-next-run')).toBeNull();
  });

  it('marks a built-in agent and hides its edit button', () => {
    const el = card(agent({ system_type: 'daily_briefing' }));
    expect(el.querySelector('.agent-system-badge')?.textContent).toBe('Built-in');
    expect(el.querySelector('.btn-edit')).toBeNull();
  });

  it('selects on a card click, runs and edits from the buttons without selecting', () => {
    const a = agent({ description: 'Checks things' });
    const { el, cb } = render(payload({ agents: [a] }));
    const cardEl = el.querySelector('.agent-card') as HTMLElement;
    expect(cardEl.querySelector('.agent-description')?.textContent).toBe('Checks things');

    cardEl.querySelector<HTMLButtonElement>('.btn-run')?.click();
    cardEl.querySelector<HTMLButtonElement>('.btn-edit')?.click();
    expect(cb.run).toHaveBeenCalledWith('a1', 'Watcher');
    expect(cb.edit).toHaveBeenCalledWith(a);
    expect(cb.select).not.toHaveBeenCalled();

    cardEl.click();
    expect(cb.select).toHaveBeenCalledWith('a1');
  });
});
