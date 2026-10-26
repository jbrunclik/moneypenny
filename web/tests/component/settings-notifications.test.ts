/**
 * Notifications settings tab: the push body for each device push state,
 * enabling/disabling push and sending a test notification, the Daily
 * Briefing toggle/time (saved immediately, restored on failure) and the
 * WhatsApp number (shown only when available, saved on blur when changed).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { PushState } from '@/core/push';
import type { UserSettings } from '@/types/api';

const push = vi.hoisted(() => ({
  enablePush: vi.fn<() => Promise<PushState>>(),
  disablePush: vi.fn<() => Promise<PushState>>(),
  sendTestNotification: vi.fn<() => Promise<string>>(),
}));
const settingsApi = vi.hoisted(() => ({ update: vi.fn<(data: Partial<UserSettings>) => Promise<void>>() }));
const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn() }));

vi.mock('@/core/push', () => push);
vi.mock('@/api/settings', () => ({ settings: settingsApi }));
vi.mock('@/components/Toast', () => ({ toast: toastMock }));

import {
  bindWhatsappField,
  handleNotificationsChange,
  handleNotificationsClick,
  loadNotificationSettings,
  renderNotificationsSection,
} from '@/components/settings/notifications';

function load(data: Partial<UserSettings>, state: PushState = 'not-subscribed'): void {
  loadNotificationSettings(data as UserSettings, state);
}

function mount(): void {
  document.body.innerHTML = renderNotificationsSection();
  bindWhatsappField();
}

function q<T extends HTMLElement>(selector: string): T {
  const el = document.querySelector<T>(selector);
  if (!el) throw new Error(`${selector} not rendered`);
  return el;
}

const pushBodyText = () => q('.settings-push-body').textContent ?? '';

beforeEach(() => {
  vi.clearAllMocks();
  settingsApi.update.mockResolvedValue(undefined);
  push.sendTestNotification.mockResolvedValue('sent');
  load({ daily_briefing: { enabled: false, time: '08:00', timezone: 'UTC' }, whatsapp_available: false });
});

describe('push section', () => {
  it.each<[PushState, string]>([
    ['subscribed', 'enabled on this device'],
    ['not-subscribed', 'Get notified'],
    ['denied', 'blocked for this site'],
    ['ios-needs-install', 'Home Screen'],
    ['server-disabled', 'VAPID keys missing'],
    ['unsupported', 'Not supported in this browser'],
  ])('describes the %s state', (state, text) => {
    load({}, state);
    mount();
    expect(pushBodyText()).toContain(text);
  });

  it('enables push and re-renders the section', async () => {
    push.enablePush.mockResolvedValue('subscribed');
    mount();
    handleNotificationsClick(q('.push-toggle-btn[data-action="enable"]'));
    await vi.waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Notifications enabled'));
    expect(document.querySelector('.push-toggle-btn[data-action="disable"]')).not.toBeNull();
    expect(document.querySelector('.push-test-btn')).not.toBeNull();
  });

  it('disables push', async () => {
    load({}, 'subscribed');
    push.disablePush.mockResolvedValue('not-subscribed');
    mount();
    handleNotificationsClick(q('.push-toggle-btn[data-action="disable"]'));
    await vi.waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Notifications disabled'));
    expect(document.querySelector('.push-toggle-btn[data-action="enable"]')).not.toBeNull();
  });

  it('warns when the browser blocks the permission', async () => {
    push.enablePush.mockResolvedValue('denied');
    mount();
    handleNotificationsClick(q('.push-toggle-btn'));
    await vi.waitFor(() =>
      expect(toastMock.warning).toHaveBeenCalledWith('Notifications are blocked in your browser settings.')
    );
    expect(pushBodyText()).toContain('blocked for this site');
  });

  it('reports a failed enable and re-renders the unchanged state', async () => {
    push.enablePush.mockRejectedValue(new Error('boom'));
    mount();
    const btn = q<HTMLButtonElement>('.push-toggle-btn');
    handleNotificationsClick(btn);
    expect(btn.disabled).toBe(true);
    await vi.waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Failed to enable notifications.'));
    expect(q<HTMLButtonElement>('.push-toggle-btn').disabled).toBe(false);
  });

  it('sends a test notification', async () => {
    load({}, 'subscribed');
    mount();
    handleNotificationsClick(q('.push-test-btn'));
    await vi.waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Test notification sent'));
    expect(q<HTMLButtonElement>('.push-test-btn').disabled).toBe(false);
  });

  it('warns when no device is subscribed for the test', async () => {
    load({}, 'subscribed');
    push.sendTestNotification.mockResolvedValue('no_subscriptions');
    mount();
    handleNotificationsClick(q('.push-test-btn'));
    await vi.waitFor(() => expect(toastMock.warning).toHaveBeenCalledWith('No subscribed devices found.'));
  });

  it('reports a failed test notification', async () => {
    load({}, 'subscribed');
    push.sendTestNotification.mockRejectedValue(new Error('boom'));
    mount();
    handleNotificationsClick(q('.push-test-btn'));
    await vi.waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Failed to send test notification.'));
  });
});

describe('daily briefing', () => {
  it('renders the stored settings', () => {
    load({ daily_briefing: { enabled: true, time: '07:30', timezone: 'Europe/Prague' } });
    mount();
    expect(q<HTMLInputElement>('#briefing-enabled').checked).toBe(true);
    expect(q<HTMLInputElement>('#briefing-time').value).toBe('07:30');
  });

  it('saves a change with the browser timezone', async () => {
    mount();
    q<HTMLInputElement>('#briefing-enabled').checked = true;
    q<HTMLInputElement>('#briefing-time').value = '06:45';
    handleNotificationsChange(q('#briefing-enabled'));
    await vi.waitFor(() =>
      expect(toastMock.success).toHaveBeenCalledWith('Daily briefing scheduled for 06:45')
    );
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    expect(settingsApi.update).toHaveBeenCalledWith({
      daily_briefing: { enabled: true, time: '06:45', timezone },
    });
  });

  it('confirms disabling', async () => {
    load({ daily_briefing: { enabled: true, time: '08:00', timezone: 'UTC' } });
    mount();
    q<HTMLInputElement>('#briefing-enabled').checked = false;
    handleNotificationsChange(q('#briefing-enabled'));
    await vi.waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Daily briefing disabled'));
  });

  it('restores the controls when saving fails', async () => {
    settingsApi.update.mockRejectedValue(new Error('boom'));
    mount();
    q<HTMLInputElement>('#briefing-enabled').checked = true;
    q<HTMLInputElement>('#briefing-time').value = '05:00';
    handleNotificationsChange(q('#briefing-time'));
    await vi.waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Failed to update daily briefing.'));
    expect(q<HTMLInputElement>('#briefing-enabled').checked).toBe(false);
    expect(q<HTMLInputElement>('#briefing-time').value).toBe('08:00');
  });

  it('ignores changes from other controls', () => {
    mount();
    const other = document.createElement('input');
    other.id = 'something-else';
    handleNotificationsChange(other);
    expect(settingsApi.update).not.toHaveBeenCalled();
  });
});

describe('whatsapp number', () => {
  it('is hidden when WhatsApp is not available', () => {
    mount();
    expect(document.getElementById('whatsapp-phone')).toBeNull();
  });

  it('saves a changed number on blur and shows Saved', async () => {
    load({ whatsapp_available: true, whatsapp_phone: '+420111' });
    mount();
    const input = q<HTMLInputElement>('#whatsapp-phone');
    expect(input.value).toBe('+420111');
    input.value = ' +420222 ';
    input.dispatchEvent(new Event('blur'));
    await vi.waitFor(() =>
      expect(q('[data-saved-for="whatsapp-phone"]').classList.contains('visible')).toBe(true)
    );
    expect(settingsApi.update).toHaveBeenCalledWith({ whatsapp_phone: '+420222' });
  });

  it('does not save an unchanged number', () => {
    load({ whatsapp_available: true, whatsapp_phone: '+420111' });
    mount();
    q('#whatsapp-phone').dispatchEvent(new Event('blur'));
    expect(settingsApi.update).not.toHaveBeenCalled();
  });

  it('reports a failed save', async () => {
    settingsApi.update.mockRejectedValue(new Error('boom'));
    load({ whatsapp_available: true, whatsapp_phone: '' });
    mount();
    const input = q<HTMLInputElement>('#whatsapp-phone');
    input.value = '+420333';
    input.dispatchEvent(new Event('blur'));
    await vi.waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Failed to save WhatsApp number'));
  });
});
