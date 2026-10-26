/**
 * Integrations settings tab: every integration field plus the device
 * location toggle. Enabling location asks for a fix right away and turns
 * the toggle back off (with the reason) when the browser can't give one.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { LocationFixResult } from '@/utils/location';

const location = vi.hoisted(() => ({
  isLocationSharingEnabled: vi.fn(() => false),
  setLocationSharingEnabled: vi.fn(),
  requestLocationFix: vi.fn<() => Promise<LocationFixResult>>(),
}));
const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock('@/utils/location', () => location);
vi.mock('@/components/Toast', () => ({ toast: toastMock }));
vi.mock('@/components/settings/todoist', () => ({ renderTodoistField: () => '<div data-section="todoist"></div>' }));
vi.mock('@/components/settings/calendar', () => ({
  renderCalendarField: () => '<div data-section="calendar"></div>',
}));
vi.mock('@/components/settings/garmin', () => ({ renderGarminField: () => '<div data-section="garmin"></div>' }));
vi.mock('@/components/settings/rouvy', () => ({ renderRouvyField: () => '<div data-section="rouvy"></div>' }));

import { handleIntegrationsChange, renderIntegrationsSection } from '@/components/settings/integrations';

function mount(): HTMLInputElement {
  document.body.innerHTML = renderIntegrationsSection();
  const box = document.getElementById('location-sharing-enabled');
  if (!(box instanceof HTMLInputElement)) throw new Error('location toggle not rendered');
  return box;
}

beforeEach(() => {
  vi.clearAllMocks();
  location.isLocationSharingEnabled.mockReturnValue(false);
});

describe('integrations section', () => {
  it('renders every integration, divided, then location', () => {
    mount();
    const sections = Array.from(document.querySelectorAll<HTMLElement>('[data-section]')).map(
      (el) => el.dataset.section
    );
    expect(sections).toEqual(['todoist', 'calendar', 'garmin', 'rouvy', 'location']);
    expect(document.querySelectorAll('.settings-divider')).toHaveLength(4);
  });

  it('reflects the stored location preference', () => {
    location.isLocationSharingEnabled.mockReturnValue(true);
    expect(mount().checked).toBe(true);
  });
});

describe('location toggle', () => {
  it('disabling stores it without asking for a fix', () => {
    location.isLocationSharingEnabled.mockReturnValue(true);
    const box = mount();
    box.checked = false;
    handleIntegrationsChange(box);
    expect(location.setLocationSharingEnabled).toHaveBeenCalledWith(false);
    expect(location.requestLocationFix).not.toHaveBeenCalled();
    expect(toastMock.success).toHaveBeenCalledWith('Location sharing disabled');
  });

  it('enabling asks for a fix and confirms it', async () => {
    location.requestLocationFix.mockResolvedValue({
      ok: true,
      fix: { lat: 50, lon: 14, accuracy_m: 10, timestamp_ms: 0 },
    });
    const box = mount();
    box.checked = true;
    handleIntegrationsChange(box);
    expect(location.setLocationSharingEnabled).toHaveBeenCalledWith(true);
    await vi.waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Location sharing enabled'));
    expect(box.checked).toBe(true);
  });

  it.each([
    ['denied', 'Location permission denied'],
    ['unsupported', 'does not support location'],
    ['unavailable', "couldn't determine a location"],
    ['timeout', 'Timed out'],
  ] as const)('turns itself back off when the fix fails (%s)', async (reason, text) => {
    location.requestLocationFix.mockResolvedValue({ ok: false, reason });
    const box = mount();
    box.checked = true;
    handleIntegrationsChange(box);
    await vi.waitFor(() => expect(toastMock.error).toHaveBeenCalledWith(expect.stringContaining(text)));
    expect(location.setLocationSharingEnabled).toHaveBeenLastCalledWith(false);
    expect(box.checked).toBe(false);
  });

  it('ignores changes from other controls', () => {
    mount();
    const other = document.createElement('input');
    other.id = 'something-else';
    handleIntegrationsChange(other);
    expect(location.setLocationSharingEnabled).not.toHaveBeenCalled();
  });
});
