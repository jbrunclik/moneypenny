/**
 * Command Center: one list of every job - items set from chats and standing
 * jobs (agents) - needs attention first, each with its schedule, next run,
 * status and recent runs; approvals above it (standing chats phase 3, E3).
 */
import { describe, it, expect, vi } from 'vitest';
import { renderCommandCenter, type CommandCenterHandlers } from '@/components/CommandCenter';
import type { ApprovalRequest, Job, JobRun, JobsOverviewResponse } from '@/types/api';

function job(extra: Partial<Job> = {}): Job {
  return {
    id: 'j1',
    kind: 'recurring',
    standing: true,
    area: 'agents',
    title: 'Coach',
    conversation_id: 'c1',
    conversation_title: 'Agent: Coach',
    when: 'every day at 20:00',
    ends: 'until cancelled',
    status: 'active',
    paused_reason: null,
    next_run_at: '2026-11-09T19:00:00.000000+00:00',
    system_type: null,
    editable: true,
    unread_count: 0,
    has_pending_approval: false,
    cost_7d_display: '0.12 Kč',
    runs_7d: 5,
    recent_runs: [],
    ...extra,
  };
}

function run(extra: Partial<JobRun> = {}): JobRun {
  return { status: 'completed', trigger_type: 'scheduled', started_at: '2026-11-08T19:00:00.000000+00:00', error: null, ...extra };
}

function payload(extra: Partial<JobsOverviewResponse> = {}): JobsOverviewResponse {
  return {
    jobs: [],
    pending_approvals: [],
    stats: { days: 7, total_runs: 0, total_completed: 0, total_failed: 0, total_cost_display: '' },
    total_unread: 0,
    jobs_waiting: 0,
    jobs_with_errors: 0,
    ...extra,
  };
}

function handlers(): CommandCenterHandlers & Record<string, ReturnType<typeof vi.fn>> {
  return {
    onRefresh: vi.fn(async () => {}),
    onApproval: vi.fn(async () => {}),
    onOpenChat: vi.fn(async () => {}),
    onRun: vi.fn(async () => {}),
    onPause: vi.fn(async () => {}),
    onResume: vi.fn(async () => {}),
    onCancel: vi.fn(async () => {}),
    onEdit: vi.fn(),
    onNewAgent: vi.fn(),
  };
}

function rows(el: HTMLElement): HTMLElement[] {
  return [...el.querySelectorAll<HTMLElement>('.job-row')];
}

describe('renderCommandCenter', () => {
  it('renders one row per job with its schedule and next run', () => {
    const el = renderCommandCenter(
      payload({ jobs: [job(), job({ id: 'j2', standing: false, area: 'chat', kind: 'watcher', title: "the school's job board", editable: false })] }),
      handlers()
    );

    const [coach, watcher] = rows(el);
    expect(coach?.querySelector('.job-title')?.textContent).toBe('Coach');
    expect(coach?.querySelector('.job-meta')?.textContent).toContain('every day at 20:00');
    expect(coach?.querySelector('.job-meta')?.textContent).toContain('7d: 5 runs');
    expect(watcher?.querySelector('.job-meta')?.textContent).toContain('Agent: Coach');
  });

  it('keeps the server order: needs attention first', () => {
    const el = renderCommandCenter(
      payload({ jobs: [job({ id: 'failing', recent_runs: [run({ status: 'failed', error: 'Garmin login expired' })] }), job({ id: 'ok' })] }),
      handlers()
    );

    expect(rows(el).map((r) => r.dataset.jobId)).toEqual(['failing', 'ok']);
    expect(rows(el)[0]?.querySelector('.job-status')?.textContent).toBe('failed');
  });

  it('shows why a job is paused or waiting', () => {
    const el = renderCommandCenter(
      payload({
        jobs: [
          job({ id: 'p', status: 'paused', paused_reason: 'failures' }),
          job({ id: 'w', has_pending_approval: true }),
          job({ id: 'd', status: 'paused', paused_reason: 'disabled' }),
        ],
      }),
      handlers()
    );

    expect(rows(el).map((r) => r.querySelector('.job-status')?.textContent)).toEqual([
      'paused after failing',
      'waiting for approval',
      'paused',
    ]);
    // Only trouble gets the attention border: paused by the user is a state,
    // and a waiting job's approval card above already asks
    expect(rows(el).map((r) => r.classList.contains('job-row--attention'))).toEqual([true, false, false]);
  });

  it('run, pause, resume, cancel and edit call their handlers', () => {
    const h = handlers();
    const el = renderCommandCenter(
      payload({
        jobs: [
          job({ id: 'a' }),
          job({ id: 'b', status: 'paused', paused_reason: 'disabled' }),
          job({ id: 'c', standing: false, area: 'chat', kind: 'watcher', editable: false }),
        ],
      }),
      h
    );
    const [a, b, c] = rows(el);

    a?.querySelector<HTMLButtonElement>('.job-run')?.click();
    a?.querySelector<HTMLButtonElement>('.job-pause')?.click();
    a?.querySelector<HTMLButtonElement>('.job-edit')?.click();
    b?.querySelector<HTMLButtonElement>('.job-resume')?.click();
    c?.querySelector<HTMLButtonElement>('.job-cancel')?.click();

    expect(h.onRun).toHaveBeenCalledWith(expect.objectContaining({ id: 'a' }));
    expect(h.onPause).toHaveBeenCalledWith(expect.objectContaining({ id: 'a' }));
    expect(h.onEdit).toHaveBeenCalledWith(expect.objectContaining({ id: 'a' }));
    expect(h.onResume).toHaveBeenCalledWith(expect.objectContaining({ id: 'b' }));
    expect(h.onCancel).toHaveBeenCalledWith(expect.objectContaining({ id: 'c' }));
    expect(h.onOpenChat).not.toHaveBeenCalled();
    expect(c?.querySelector('.job-run')).toBeNull(); // light items run on their schedule
  });

  it('a row click opens its chat', () => {
    const h = handlers();
    const el = renderCommandCenter(payload({ jobs: [job()] }), h);

    rows(el)[0]?.querySelector<HTMLElement>('.job-title')?.click();

    expect(h.onOpenChat).toHaveBeenCalledWith('c1');
  });

  it('a built-in job has no edit and says so', () => {
    const el = renderCommandCenter(payload({ jobs: [job({ system_type: 'daily_briefing', editable: false })] }), handlers());

    expect(el.querySelector('.job-edit')).toBeNull();
    expect(el.querySelector('.job-builtin')?.textContent).toBe('Built-in');
  });

  it('recent runs expand from a summary', () => {
    const el = renderCommandCenter(
      payload({ jobs: [job({ recent_runs: [run({ status: 'failed', error: 'Garmin login expired' }), run()] })] }),
      handlers()
    );

    const details = el.querySelector<HTMLDetailsElement>('.job-runs');
    expect(details?.open).toBe(false);
    expect(details?.querySelectorAll('.job-run-item')).toHaveLength(2);
    expect(details?.textContent).toContain('Garmin login expired');
  });

  it('shows an empty state with New agent and no suggestions', () => {
    const h = handlers();
    const el = renderCommandCenter(payload(), h);

    expect(el.querySelector('.jobs-empty')?.textContent).toContain('Nothing scheduled yet');
    el.querySelector<HTMLButtonElement>('.jobs-empty .btn-create-agent')?.click();
    expect(h.onNewAgent).toHaveBeenCalled();
  });

  it('lists pending approvals above the jobs, with the job schedule', () => {
    const approval = {
      id: 'ap1',
      item_id: 'j1',
      job_name: 'Coach',
      tool_name: 'todoist',
      tool_args: {},
      description: 'Add a task',
      status: 'pending',
      created_at: '2026-11-08T19:00:00.000000+00:00',
      resolved_at: null,
    } as ApprovalRequest;
    const h = handlers();
    const el = renderCommandCenter(payload({ jobs: [job({ has_pending_approval: true })], pending_approvals: [approval] }), h);

    const card = el.querySelector('.approval-card');
    expect(card?.textContent).toContain('every day at 20:00');
    card?.querySelector<HTMLButtonElement>('.btn-approve')?.click();
    expect(h.onApproval).toHaveBeenCalledWith('ap1', true);
  });

  it('shows the week stats only with runs', () => {
    expect(renderCommandCenter(payload(), handlers()).querySelector('.command-center-stats')).toBeNull();
    const el = renderCommandCenter(
      payload({ stats: { days: 7, total_runs: 4, total_completed: 3, total_failed: 1, total_cost_display: '1.20 Kč' } }),
      handlers()
    );
    expect(el.querySelector('.command-center-stats')?.textContent).toContain('75% success');
  });

  it('a chat item in an agent\'s chat can be cancelled; the agent job cannot', () => {
    const el = renderCommandCenter(
      payload({
        jobs: [
          job({ id: 'agent' }),
          job({ id: 'item', standing: false, kind: 'reminder', editable: false, system_type: null }),
        ],
      }),
      handlers()
    );
    const [agentRow, itemRow] = rows(el);
    expect(agentRow?.querySelector('.job-cancel')).toBeNull();
    expect(itemRow?.querySelector('.job-cancel')).not.toBeNull();
  });

  it('a paused job offers Resume, not Run', () => {
    const el = renderCommandCenter(payload({ jobs: [job({ status: 'paused', paused_reason: 'disabled' })] }), handlers());
    expect(el.querySelector('.job-run')).toBeNull();
    expect(el.querySelector('.job-resume')?.getAttribute('aria-label')).toBe('Resume');
  });

  it('actions are labelled icon buttons', () => {
    const el = renderCommandCenter(payload({ jobs: [job()] }), handlers());
    const run = el.querySelector<HTMLButtonElement>('.job-run')!;
    expect(run.querySelector('svg')).not.toBeNull();
    expect([run.title, run.getAttribute('aria-label')]).toEqual(['Run now', 'Run now']);
  });

  it('no count on an empty job list', () => {
    const el = renderCommandCenter(payload(), handlers());
    expect(el.querySelector('.command-center-section--jobs .badge')).toBeNull();
  });

  it('a running job offers neither Run nor Pause', () => {
    const el = renderCommandCenter(payload({ jobs: [job({ status: 'running' })] }), handlers());
    expect(el.querySelector('.job-run')).toBeNull();
    expect(el.querySelector('.job-pause')).toBeNull();
  });

  it('a row is reachable by keyboard and opens its chat on Enter', () => {
    const h = handlers();
    const el = renderCommandCenter(payload({ jobs: [job()] }), h);
    const row = rows(el)[0]!;
    expect(row.getAttribute('tabindex')).toBe('0');
    row.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(h.onOpenChat).toHaveBeenCalledWith('c1');
  });
});
