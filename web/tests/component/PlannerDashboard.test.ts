/**
 * Tests for the planner dashboard rendering.
 */
import { describe, it, expect } from 'vitest';
import { createDashboardElement } from '@/components/PlannerDashboard';
import type { PlannerDashboard, PlannerDay } from '@/types/api';

function day(date: string, overrides: Partial<PlannerDay> = {}): PlannerDay {
  return { date, day_name: 'Monday', events: [], tasks: [], ...overrides };
}

function dashboard(overrides: Partial<PlannerDashboard> = {}): PlannerDashboard {
  return {
    days: [day('2026-10-09'), day('2026-10-10')],
    overdue_tasks: [],
    todoist_connected: true,
    calendar_connected: true,
    garmin_connected: false,
    weather_connected: false,
    server_time: '2026-10-09T08:00:00',
    ...overrides,
  };
}

function render(d: PlannerDashboard): HTMLElement {
  return createDashboardElement(d, () => {}, () => {});
}

describe('PlannerDashboard empty state', () => {
  it('says all clear when both sources loaded and nothing is scheduled', () => {
    expect(render(dashboard()).querySelector('.dashboard-empty')).not.toBeNull();
  });

  it('shows the empty state alone, not a "Nothing scheduled" line per day too', () => {
    const el = render(dashboard());
    expect(el.querySelector('.dashboard-day-empty')).toBeNull();
    expect(el.querySelector('.dashboard-empty')).not.toBeNull();
  });

  it('does not claim all clear when a task or calendar source failed', () => {
    for (const errors of [
      { todoist_error: 'Token expired' },
      { calendar_error: 'API rate limit exceeded' },
    ]) {
      const el = render(dashboard(errors));
      expect(el.querySelector('.dashboard-error')).not.toBeNull();
      expect(el.querySelector('.dashboard-empty')).toBeNull();
    }
  });
});

describe('PlannerDashboard week section', () => {
  const task = { id: 't1', content: 'Pay rent', priority: 1, due: null, project: null };

  it('uses the singular for one item', () => {
    const d = dashboard({
      days: [day('2026-10-09'), day('2026-10-10'), day('2026-10-11', { tasks: [task] as PlannerDay['tasks'] })],
    });
    expect(render(d).querySelector('.week summary')?.textContent).toContain('1 item');
    expect(render(d).querySelector('.week summary')?.textContent).not.toContain('1 items');
  });
});
