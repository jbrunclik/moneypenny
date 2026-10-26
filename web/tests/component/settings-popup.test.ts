/**
 * Settings popup shell: loading state, the tabbed body once settings and
 * every integration status arrive (a failing status doesn't block it), the
 * retry state when settings fail, tab switching and the close paths.
 */
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { UserSettings } from '@/types/api';

const settingsApi = vi.hoisted(() => ({ get: vi.fn(), update: vi.fn() }));
const integrations = vi.hoisted(() => {
  const status = (): { getStatus: ReturnType<typeof vi.fn> } => ({ getStatus: vi.fn() });
  return {
    todoist: status(),
    calendar: { ...status(), listCalendars: vi.fn(), getSelectedCalendars: vi.fn() },
    garmin: status(),
    rouvy: status(),
  };
});

vi.mock('@/api/settings', () => ({ settings: settingsApi }));
vi.mock('@/api/integrations', () => integrations);

import { closeSettingsPopup, openSettingsPopup } from '@/components/SettingsPopup';
import { createPopupShell } from '@/components/InfoPopup';
import { destroyPopupEscapeListener, initPopupEscapeListener } from '@/utils/popupEscapeHandler';

const SETTINGS = { custom_instructions: '', whatsapp_available: false } as unknown as UserSettings;

const popup = () => document.getElementById('settings-popup')!;
const q = <T extends HTMLElement>(selector: string) => popup().querySelector<T>(selector);
const isOpen = () => !popup().classList.contains('hidden');

describe('SettingsPopup', () => {
  beforeAll(() => {
    document.body.replaceChildren(createPopupShell('settings-popup'));
    initPopupEscapeListener();
  });
  afterAll(() => destroyPopupEscapeListener());

  beforeEach(() => {
    vi.clearAllMocks();
    settingsApi.get.mockResolvedValue(SETTINGS);
    integrations.todoist.getStatus.mockResolvedValue({ connected: false });
    integrations.calendar.getStatus.mockResolvedValue({ connected: false });
    integrations.garmin.getStatus.mockResolvedValue({ connected: false });
    integrations.rouvy.getStatus.mockResolvedValue({ connected: false });
    closeSettingsPopup();
  });

  it('shows a loading state, then the tabbed sections', async () => {
    let resolve!: (s: UserSettings) => void;
    settingsApi.get.mockReturnValue(new Promise((r) => (resolve = r)));

    const opening = openSettingsPopup();
    expect(isOpen()).toBe(true);
    expect(q('.settings-loading')!.textContent).toBe('Loading settings...');

    resolve(SETTINGS);
    await opening;
    expect(q('.settings-loading')).toBeNull();
    const tabs = [...popup().querySelectorAll<HTMLElement>('.settings-tab')].map((t) => t.dataset.settingsTab);
    expect(tabs).toEqual(['appearance', 'integrations', 'notifications', 'instructions']);
  });

  it('switches the active tab and its section', async () => {
    await openSettingsPopup();

    q('[data-settings-tab="notifications"]')!.click();

    expect(q('.settings-tab.active')!.dataset.settingsTab).toBe('notifications');
    const active = [...popup().querySelectorAll<HTMLElement>('.settings-section.active')];
    expect(active.map((s) => s.dataset.settingsSection)).toEqual(['notifications']);
  });

  it('still opens when an integration status fails', async () => {
    integrations.garmin.getStatus.mockRejectedValue(new Error('down'));
    await openSettingsPopup();
    expect(q('.settings-tabs')).not.toBeNull();
    expect(q('.settings-error')).toBeNull();
  });

  it('loads the calendar choice only when the calendar is connected', async () => {
    await openSettingsPopup();
    expect(integrations.calendar.listCalendars).not.toHaveBeenCalled();

    integrations.calendar.getStatus.mockResolvedValue({ connected: true });
    integrations.calendar.listCalendars.mockResolvedValue({ calendars: [] });
    integrations.calendar.getSelectedCalendars.mockResolvedValue({ calendar_ids: [] });
    await openSettingsPopup();
    expect(integrations.calendar.listCalendars).toHaveBeenCalledOnce();
  });

  it('offers a retry when settings fail to load, and the retry reloads', async () => {
    settingsApi.get.mockRejectedValueOnce(new Error('offline'));
    await openSettingsPopup();
    expect(q('.settings-error')!.textContent).toContain('Failed to load settings.');

    q('.settings-retry-btn')!.click();
    await vi.waitFor(() => expect(q('.settings-tabs')).not.toBeNull());
    expect(settingsApi.get).toHaveBeenCalledTimes(2);
  });

  it('closes from the close button, the backdrop and Escape', async () => {
    await openSettingsPopup();
    q('.info-popup-close')!.click();
    expect(isOpen()).toBe(false);

    await openSettingsPopup();
    popup().click();
    expect(isOpen()).toBe(false);

    await openSettingsPopup();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(isOpen()).toBe(false);
  });
});
