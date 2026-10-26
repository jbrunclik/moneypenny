/**
 * Google Calendar selection: a calendar's colour dot takes its colour from
 * the server only when it is a plain hex or rgb() colour - anything else
 * (extra declarations, url(), expressions) gets no dot rather than landing
 * in a style attribute.
 */
import { describe, it, expect, vi } from 'vitest';

const api = vi.hoisted(() => ({ listCalendars: vi.fn(), getSelectedCalendars: vi.fn() }));
vi.mock('@/api/integrations', () => ({ calendar: api }));

import { loadCalendarSelection, renderCalendarField, setCalendarStatus } from '@/components/settings/calendar';
import { POPUP_ID } from '@/components/settings/shared';
import type { CalendarStatus } from '@/types/api';

async function render(colors: (string | null)[]): Promise<HTMLElement[]> {
  setCalendarStatus({ connected: true, calendar_email: 'a@b.c', connected_at: null, needs_reconnect: false } as CalendarStatus);
  api.listCalendars.mockResolvedValue({
    calendars: colors.map((background_color, i) => ({
      id: `c${i}`,
      summary: `Cal ${i}`,
      primary: false,
      background_color,
      access_role: 'owner',
    })),
  });
  api.getSelectedCalendars.mockResolvedValue({ calendar_ids: ['primary'] });
  const popup = document.createElement('div');
  popup.id = POPUP_ID;
  popup.append(renderCalendarField());
  document.body.replaceChildren(popup);
  await loadCalendarSelection();
  return [...document.querySelectorAll<HTMLElement>('.settings-calendar-item')];
}

const dot = (item: HTMLElement | undefined): HTMLElement | null | undefined => item?.querySelector('.calendar-color-dot');

describe('calendar colour dots', () => {
  it('shows hex and rgb() colours', async () => {
    const items = await render(['#ff0000', '#0F0', 'rgb(0, 0, 255)']);
    expect(dot(items[0])?.style.backgroundColor).toBe('rgb(255, 0, 0)');
    expect(dot(items[1])?.style.backgroundColor).toBe('rgb(0, 255, 0)');
    expect(dot(items[2])?.style.backgroundColor).toBe('rgb(0, 0, 255)');
  });

  it('drops a value that is not a plain colour', async () => {
    const items = await render([
      'red; background-image: url(https://evil.example/x)',
      'url(https://evil.example/x)',
      '#ff0000" onclick="x',
      'expression(alert(1))',
      null,
    ]);
    for (const item of items) expect(dot(item)).toBeNull();
    expect(document.querySelector('[style*="url"]')).toBeNull();
  });
});
