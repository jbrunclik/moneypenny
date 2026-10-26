/**
 * Finishing an integration's OAuth redirect: only while that flow is in
 * progress (its state key in sessionStorage) and the URL is a callback.
 * The URL params are cleared, a provider error or a state mismatch fails
 * with a toast, and a matching state exchanges the code, adopts the new
 * status, flags the user connected and reopens Settings.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const api = vi.hoisted(() => ({
  todoistConnect: vi.fn(),
  calendarConnect: vi.fn(),
}));
const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const ui = vi.hoisted(() => ({
  renderConversationsList: vi.fn(),
  openSettingsPopup: vi.fn(() => Promise.resolve()),
}));

vi.mock('@/api/integrations', () => ({
  todoist: { connect: api.todoistConnect },
  calendar: { connect: api.calendarConnect },
}));
vi.mock('@/components/Toast', () => ({ toast: toastMock }));
vi.mock('@/components/Sidebar', () => ({ renderConversationsList: ui.renderConversationsList }));
vi.mock('@/components/SettingsPopup', () => ({ openSettingsPopup: ui.openSettingsPopup }));
vi.mock('@/components/settings/todoist', () => ({
  TODOIST_STATE_KEY: 'todoist-oauth-state',
}));
vi.mock('@/components/settings/calendar', () => ({
  CALENDAR_STATE_KEY: 'calendar-oauth-state',
}));

import { checkCalendarOAuthCallback, checkTodoistOAuthCallback } from '@/components/settings/oauth';
import { useStore } from '@/state/store';
import type { User } from '@/types/api';

function setUrl(search: string, hash = ''): void {
  window.history.replaceState({}, '', `/${search}${hash}`);
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  setUrl('');
  api.todoistConnect.mockResolvedValue({ connected: true, todoist_email: 'me@example.com' });
  api.calendarConnect.mockResolvedValue({ connected: true, calendar_email: 'me@example.com' });
  useStore.setState({ user: { id: 'u1', email: 'me@example.com', name: 'Me' } as User });
});

describe('integration OAuth callback', () => {
  it('is not handled when the flow is not in progress', async () => {
    setUrl('?code=abc&state=s1');
    expect(await checkTodoistOAuthCallback()).toBe(false);
    expect(api.todoistConnect).not.toHaveBeenCalled();
    expect(window.location.search).toBe('?code=abc&state=s1');
  });

  it('is not handled when the URL is not a callback', async () => {
    sessionStorage.setItem('todoist-oauth-state', 's1');
    expect(await checkTodoistOAuthCallback()).toBe(false);
    expect(sessionStorage.getItem('todoist-oauth-state')).toBe('s1');
  });

  it('completes Todoist: exchanges the code, flags the user and reopens Settings', async () => {
    sessionStorage.setItem('todoist-oauth-state', 's1');
    setUrl('?code=abc&state=s1', '#/c/42');

    expect(await checkTodoistOAuthCallback()).toBe(true);

    expect(api.todoistConnect).toHaveBeenCalledWith('abc', 's1');
    expect(window.location.search).toBe('');
    expect(window.location.hash).toBe('#/c/42');
    expect(sessionStorage.getItem('todoist-oauth-state')).toBeNull();
    expect(useStore.getState().integrationStatuses.todoist).toEqual(
      expect.objectContaining({ connected: true, todoist_email: 'me@example.com', needs_reconnect: false })
    );
    expect(useStore.getState().user?.todoist_connected).toBe(true);
    expect(ui.renderConversationsList).toHaveBeenCalled();
    expect(ui.openSettingsPopup).toHaveBeenCalled();
    expect(toastMock.success).toHaveBeenCalledWith('Todoist connected successfully');
  });

  it('completes Google Calendar the same way', async () => {
    sessionStorage.setItem('calendar-oauth-state', 's2');
    setUrl('?code=xyz&state=s2');

    expect(await checkCalendarOAuthCallback()).toBe(true);

    expect(api.calendarConnect).toHaveBeenCalledWith('xyz', 's2');
    expect(useStore.getState().integrationStatuses.calendar).toEqual(expect.objectContaining({ connected: true }));
    expect(useStore.getState().user?.calendar_connected).toBe(true);
    expect(toastMock.success).toHaveBeenCalledWith('Google Calendar connected successfully');
  });

  it('leaves the other flow alone', async () => {
    sessionStorage.setItem('calendar-oauth-state', 's2');
    setUrl('?code=xyz&state=s2');
    expect(await checkTodoistOAuthCallback()).toBe(false);
    expect(await checkCalendarOAuthCallback()).toBe(true);
    expect(api.todoistConnect).not.toHaveBeenCalled();
  });

  it('reports a provider error and ends the flow', async () => {
    sessionStorage.setItem('todoist-oauth-state', 's1');
    setUrl('?error=access_denied');

    expect(await checkTodoistOAuthCallback()).toBe(true);

    expect(toastMock.error).toHaveBeenCalledWith('Failed to connect Todoist: access_denied');
    expect(sessionStorage.getItem('todoist-oauth-state')).toBeNull();
    expect(window.location.search).toBe('');
    expect(api.todoistConnect).not.toHaveBeenCalled();
  });

  it('rejects a state mismatch without exchanging the code', async () => {
    sessionStorage.setItem('todoist-oauth-state', 's1');
    setUrl('?code=abc&state=forged');

    expect(await checkTodoistOAuthCallback()).toBe(true);

    expect(toastMock.error).toHaveBeenCalledWith('Failed to connect Todoist: Invalid state');
    expect(api.todoistConnect).not.toHaveBeenCalled();
    expect(sessionStorage.getItem('todoist-oauth-state')).toBeNull();
  });

  it('reports a failed code exchange and does not reopen Settings', async () => {
    api.todoistConnect.mockRejectedValue(new Error('exchange failed'));
    sessionStorage.setItem('todoist-oauth-state', 's1');
    setUrl('?code=abc&state=s1');

    expect(await checkTodoistOAuthCallback()).toBe(true);

    expect(toastMock.error).toHaveBeenCalledWith('Failed to connect Todoist');
    expect(ui.openSettingsPopup).not.toHaveBeenCalled();
    expect(useStore.getState().user?.todoist_connected).toBeUndefined();
  });

  it('skips the user flag when nobody is signed in', async () => {
    useStore.setState({ user: null });
    sessionStorage.setItem('todoist-oauth-state', 's1');
    setUrl('?code=abc&state=s1');

    expect(await checkTodoistOAuthCallback()).toBe(true);

    expect(useStore.getState().user).toBeNull();
    expect(ui.renderConversationsList).not.toHaveBeenCalled();
    expect(ui.openSettingsPopup).toHaveBeenCalled();
  });
});
