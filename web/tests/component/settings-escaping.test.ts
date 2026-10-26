/**
 * Settings sections are HTML strings: stored text (custom instructions, the
 * connected account's email) must land as text, not markup (F3).
 */
import { describe, expect, it } from 'vitest';
import { loadInstructionsSettings, renderInstructionsSection } from '@/components/settings/instructions';
import { renderCalendarField, setCalendarStatus } from '@/components/settings/calendar';
import { renderTodoistField, setTodoistStatus } from '@/components/settings/todoist';
import type { CalendarStatus, TodoistStatus, UserSettings } from '@/types/api';

const PAYLOAD = '</textarea><img src=x onerror="alert(1)">';

function mount(html: string): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = html;
  return host;
}

describe('settings escaping', () => {
  it('keeps custom instructions as the textarea value', () => {
    loadInstructionsSettings({ custom_instructions: `Be brief & kind ${PAYLOAD}` } as UserSettings);
    const host = mount(renderInstructionsSection());
    expect(host.querySelector('img')).toBeNull();
    expect(host.querySelector<HTMLTextAreaElement>('#custom-instructions')?.value).toBe(`Be brief & kind ${PAYLOAD}`);
  });

  it('shows the connected Google Calendar email as text', () => {
    setCalendarStatus({ connected: true, calendar_email: PAYLOAD } as CalendarStatus);
    const host = mount(renderCalendarField());
    expect(host.querySelector('img')).toBeNull();
    expect(host.querySelector('.settings-calendar-status')?.textContent).toContain(PAYLOAD);
  });

  it('shows the connected Todoist email as text', () => {
    setTodoistStatus({ connected: true, todoist_email: PAYLOAD } as TodoistStatus);
    const host = mount(renderTodoistField());
    expect(host.querySelector('img')).toBeNull();
    expect(host.querySelector('.settings-todoist-status')?.textContent).toContain(PAYLOAD);
  });
});
