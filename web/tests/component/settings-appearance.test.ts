/**
 * Appearance & Language settings tab: the color scheme options (selected
 * one marked, a click applies and saves a new scheme), the sidebar-preview
 * and swipe-to-delete toggles (stored per device, sidebar re-rendered) and
 * the primary language (saved immediately, restored on failure).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { UserSettings } from '@/types/api';

const theme = vi.hoisted(() => ({
  getStoredColorScheme: vi.fn(() => 'system' as 'light' | 'dark' | 'system'),
  saveColorScheme: vi.fn(),
  applyColorScheme: vi.fn(),
}));
const prefs = vi.hoisted(() => ({
  isSidebarPreviewsEnabled: vi.fn(() => true),
  setSidebarPreviewsEnabled: vi.fn(),
  getSwipeQuickAction: vi.fn(() => 'archive' as 'archive' | 'delete'),
  setSwipeQuickAction: vi.fn(),
}));
const settingsApi = vi.hoisted(() => ({ update: vi.fn<(data: Partial<UserSettings>) => Promise<void>>() }));
const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const renderConversationsList = vi.hoisted(() => vi.fn());

vi.mock('@/utils/theme', () => theme);
vi.mock('@/utils/preferences', () => prefs);
vi.mock('@/api/settings', () => ({ settings: settingsApi }));
vi.mock('@/components/Toast', () => ({ toast: toastMock }));
vi.mock('@/components/Sidebar', () => ({ renderConversationsList }));

import {
  bindColorSchemeOptions,
  handleAppearanceChange,
  loadAppearanceSettings,
  loadColorScheme,
  renderAppearanceSection,
} from '@/components/settings/appearance';

function mount(): HTMLElement {
  document.body.innerHTML = `<div id="popup">${renderAppearanceSection()}</div>`;
  const popup = document.getElementById('popup') as HTMLElement;
  bindColorSchemeOptions(popup);
  return popup;
}

function q<T extends HTMLElement>(selector: string): T {
  const el = document.querySelector<T>(selector);
  if (!el) throw new Error(`${selector} not rendered`);
  return el;
}

const selectedScheme = () =>
  Array.from(document.querySelectorAll<HTMLElement>('.settings-color-scheme-option.selected')).map(
    (o) => o.dataset.colorScheme
  );

beforeEach(() => {
  vi.clearAllMocks();
  settingsApi.update.mockResolvedValue(undefined);
  theme.getStoredColorScheme.mockReturnValue('system');
  prefs.isSidebarPreviewsEnabled.mockReturnValue(true);
  prefs.getSwipeQuickAction.mockReturnValue('archive');
  loadColorScheme();
  loadAppearanceSettings({ preferred_language: '' } as UserSettings);
});

describe('color scheme', () => {
  it('marks the stored scheme as selected', () => {
    theme.getStoredColorScheme.mockReturnValue('dark');
    loadColorScheme();
    mount();
    expect(selectedScheme()).toEqual(['dark']);
  });

  it('applies and saves a newly picked scheme', () => {
    mount();
    q('[data-color-scheme="light"]').click();
    expect(selectedScheme()).toEqual(['light']);
    expect(theme.saveColorScheme).toHaveBeenCalledWith('light');
    expect(theme.applyColorScheme).toHaveBeenCalledWith('light');
  });

  it('does nothing when the current scheme is picked again', () => {
    mount();
    q('[data-color-scheme="system"]').click();
    expect(theme.saveColorScheme).not.toHaveBeenCalled();
  });
});

describe('device toggles', () => {
  it('reflect the stored preferences', () => {
    prefs.isSidebarPreviewsEnabled.mockReturnValue(false);
    prefs.getSwipeQuickAction.mockReturnValue('delete');
    mount();
    expect(q<HTMLInputElement>('#sidebar-previews-enabled').checked).toBe(false);
    expect(q<HTMLInputElement>('#swipe-quick-delete').checked).toBe(true);
  });

  it('store the sidebar-preview toggle and re-render the sidebar', () => {
    mount();
    const box = q<HTMLInputElement>('#sidebar-previews-enabled');
    box.checked = false;
    handleAppearanceChange(box);
    expect(prefs.setSidebarPreviewsEnabled).toHaveBeenCalledWith(false);
    expect(renderConversationsList).toHaveBeenCalledTimes(1);
  });

  it('store the swipe action as delete or archive', () => {
    mount();
    const box = q<HTMLInputElement>('#swipe-quick-delete');
    box.checked = true;
    handleAppearanceChange(box);
    box.checked = false;
    handleAppearanceChange(box);
    expect(prefs.setSwipeQuickAction.mock.calls).toEqual([['delete'], ['archive']]);
    expect(renderConversationsList).toHaveBeenCalledTimes(2);
  });
});

describe('primary language', () => {
  it('selects the stored language', () => {
    loadAppearanceSettings({ preferred_language: 'German' } as UserSettings);
    mount();
    expect(q<HTMLSelectElement>('#preferred-language').value).toBe('German');
  });

  it('saves a new language and names it in the toast', async () => {
    mount();
    const select = q<HTMLSelectElement>('#preferred-language');
    select.value = 'Czech';
    handleAppearanceChange(select);
    await vi.waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Primary language set to Čeština'));
    expect(settingsApi.update).toHaveBeenCalledWith({ preferred_language: 'Czech' });
  });

  it('confirms going back to auto', async () => {
    loadAppearanceSettings({ preferred_language: 'English' } as UserSettings);
    mount();
    const select = q<HTMLSelectElement>('#preferred-language');
    select.value = '';
    handleAppearanceChange(select);
    await vi.waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Language set to auto'));
  });

  it('restores the previous language when saving fails', async () => {
    settingsApi.update.mockRejectedValue(new Error('boom'));
    loadAppearanceSettings({ preferred_language: 'English' } as UserSettings);
    mount();
    const select = q<HTMLSelectElement>('#preferred-language');
    select.value = 'Polish';
    handleAppearanceChange(select);
    await vi.waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Failed to update language.'));
    expect(select.value).toBe('English');
  });
});
