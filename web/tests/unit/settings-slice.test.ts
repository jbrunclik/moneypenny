/**
 * Settings slice: the settings popup's data (server settings, integration
 * statuses, calendar choice, push state, Garmin MFA step), wiped on logout
 * with the rest of the user's data.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '@/state/store';
import { initialCalendarChoice } from '@/state/slices/settings';
import type { UserSettings } from '@/types/api';

const SETTINGS: UserSettings = {
  custom_instructions: 'Be brief',
  whatsapp_phone: '+420123456789',
  whatsapp_available: true,
  preferred_language: 'Czech',
  daily_briefing: { enabled: true, time: '07:30', timezone: 'Europe/Prague' },
};

const s = () => useStore.getState();

describe('settings slice', () => {
  beforeEach(() => {
    useStore.setState(useStore.getInitialState(), true);
  });

  it('starts with nothing fetched', () => {
    expect(s().userSettings).toBeNull();
    expect(s().integrationStatuses).toEqual({ todoist: null, calendar: null, garmin: null, rouvy: null });
    expect(s().calendarChoice).toEqual(initialCalendarChoice());
    expect(s().pushState).toBe('unsupported');
    expect(s().garminMfaRequired).toBe(false);
  });

  it('patches saved changes onto the fetched settings, not before the fetch', () => {
    s().patchUserSettings({ custom_instructions: 'ignored' });
    expect(s().userSettings).toBeNull();

    s().setUserSettings(SETTINGS);
    s().patchUserSettings({ preferred_language: 'English' });
    expect(s().userSettings).toEqual({ ...SETTINGS, preferred_language: 'English' });
  });

  it('sets one integration status without touching the others', () => {
    s().setIntegrationStatus('rouvy', { connected: true, connected_at: null, needs_reconnect: false });
    s().setIntegrationStatus('garmin', { connected: false, connected_at: null, needs_reconnect: false });

    expect(s().integrationStatuses.rouvy?.connected).toBe(true);
    expect(s().integrationStatuses.garmin?.connected).toBe(false);
    expect(s().integrationStatuses.todoist).toBeNull();
  });

  it('merges calendar choice changes', () => {
    s().updateCalendarChoice({ loading: true });
    s().updateCalendarChoice({ selectedIds: ['primary', 'work'], loading: false });
    expect(s().calendarChoice).toEqual({ calendars: null, selectedIds: ['primary', 'work'], loading: false, error: null });
  });

  it('is wiped on logout: the next account must not see this one', () => {
    s().setUserSettings(SETTINGS);
    s().setIntegrationStatus('todoist', { connected: true, todoist_email: 'a@b.c', connected_at: null, needs_reconnect: false });
    s().updateCalendarChoice({ selectedIds: ['work'] });
    s().setPushState('subscribed');
    s().setGarminMfaRequired(true);

    s().logout();

    expect(s().userSettings).toBeNull();
    expect(s().integrationStatuses.todoist).toBeNull();
    expect(s().calendarChoice).toEqual(initialCalendarChoice());
    expect(s().pushState).toBe('unsupported');
    expect(s().garminMfaRequired).toBe(false);
  });
});
