/**
 * Tests for the planner dashboard rendering.
 */
import { describe, it, expect } from 'vitest';
import { createDashboardElement } from '@/components/PlannerDashboard';
import type { PlannerDashboard, PlannerDay, PlannerTask } from '@/types/api';

function day(date: string, overrides: Partial<PlannerDay> = {}): PlannerDay {
  return { date, day_name: 'Monday', events: [], tasks: [], weather: null, ...overrides };
}

function dashboard(overrides: Partial<PlannerDashboard> = {}): PlannerDashboard {
  return {
    days: [day('2026-10-09'), day('2026-10-10')],
    overdue_tasks: [],
    todoist_connected: true,
    calendar_connected: true,
    garmin_connected: false,
    weather_connected: false,
    todoist_error: null,
    calendar_error: null,
    garmin_error: null,
    weather_error: null,
    weather_location: null,
    health_summary: null,
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
  const task: PlannerTask = {
    id: 't1',
    content: 'Pay rent',
    description: '',
    due_date: null,
    due_string: null,
    priority: 1,
    project_name: null,
    section_name: null,
    labels: [],
    is_recurring: false,
    url: null,
  };

  it('uses the singular for one item', () => {
    const d = dashboard({
      days: [day('2026-10-09'), day('2026-10-10'), day('2026-10-11', { tasks: [task] })],
    });
    expect(render(d).querySelector('.week summary')?.textContent).toContain('1 item');
    expect(render(d).querySelector('.week summary')?.textContent).not.toContain('1 items');
  });
});

describe('PlannerDashboard today timeline', () => {
  const event = (id: string, start: string, end: string, isAllDay = false) =>
    ({
      id,
      summary: id,
      description: null,
      start,
      end,
      is_all_day: isAllDay,
      location: null,
    }) as unknown as PlannerDay['events'][number];

  /** The order of event rows and the "Now" line in today's section */
  function timeline(events: PlannerDay['events']): string[] {
    const el = render(dashboard({ days: [day('2026-10-09', { events }), day('2026-10-10')] }));
    const section = el.querySelector('.dashboard-events') as HTMLElement;
    return [...section.querySelectorAll<HTMLElement>('.planner-item-event, .time-indicator')].map((n) =>
      n.classList.contains('time-indicator')
        ? 'NOW'
        : `${n.dataset.past ? 'past:' : ''}${n.querySelector('.planner-item-title')?.textContent ?? ''}`
    );
  }

  it('puts the Now line between past and upcoming events and dims the past ones', () => {
    const order = timeline([
      event('Standup', '2026-10-09T07:00:00', '2026-10-09T07:30:00'),
      event('Lunch', '2026-10-09T12:00:00', '2026-10-09T13:00:00'),
    ]);
    expect(order).toEqual(['past:Standup', 'NOW', 'Lunch']);
  });

  it('skips all-day events when placing the Now line', () => {
    const order = timeline([
      event('Holiday', '2026-10-09', '2026-10-10', true),
      event('Lunch', '2026-10-09T12:00:00', '2026-10-09T13:00:00'),
    ]);
    expect(order).toEqual(['Holiday', 'NOW', 'Lunch']);
  });

  it('puts the Now line last when every timed event is over', () => {
    const order = timeline([event('Standup', '2026-10-09T07:00:00', '2026-10-09T07:30:00')]);
    expect(order).toEqual(['past:Standup', 'NOW']);
  });

  it('shows no Now line among only all-day events', () => {
    expect(timeline([event('Holiday', '2026-10-09', '2026-10-10', true)])).toEqual(['Holiday']);
  });
});
