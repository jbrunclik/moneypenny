/**
 * Shared settings-field helpers: re-rendering one field of the open popup
 * (a no-op when the popup or field is gone) and the transient "Saved"
 * indicator.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { POPUP_ID, renderFieldLabel, rerenderField, showSavedIndicator } from '@/components/settings/shared';

beforeEach(() => {
  document.body.innerHTML = '';
});

afterEach(() => {
  vi.useRealTimers();
});

describe('renderFieldLabel', () => {
  it('renders the icon and the label', () => {
    const host = document.createElement('div');
    host.innerHTML = renderFieldLabel('<svg class="icon"></svg>', 'Garmin');
    expect(host.querySelector('.settings-label-icon svg.icon')).not.toBeNull();
    expect(host.querySelector('label')?.textContent).toContain('Garmin');
  });
});

describe('rerenderField', () => {
  it('replaces only the matching field in the open popup', () => {
    document.body.innerHTML = `
      <div id="${POPUP_ID}">
        <div class="settings-field" data-section="a"><p class="old">old a</p></div>
        <div class="settings-field" data-section="b"><p class="old">old b</p></div>
      </div>`;
    rerenderField('a', '', 'Label A', '<p class="new">new a</p>');

    const a = document.querySelector('[data-section="a"]');
    expect(a?.querySelector('.new')?.textContent).toBe('new a');
    expect(a?.querySelector('.old')).toBeNull();
    expect(a?.querySelector('label')?.textContent).toContain('Label A');
    expect(document.querySelector('[data-section="b"] .old')).not.toBeNull();
  });

  it('does nothing when the popup is closed', () => {
    document.body.innerHTML = '<div class="settings-field" data-section="a">outside</div>';
    rerenderField('a', '', 'A', 'new');
    expect(document.querySelector('[data-section="a"]')?.textContent).toBe('outside');
  });

  it('does nothing when the field is not in the popup', () => {
    document.body.innerHTML = `<div id="${POPUP_ID}"><p>other</p></div>`;
    expect(() => rerenderField('missing', '', 'A', 'new')).not.toThrow();
    expect(document.getElementById(POPUP_ID)?.textContent).toBe('other');
  });
});

describe('showSavedIndicator', () => {
  it('shows the field indicator briefly', () => {
    vi.useFakeTimers();
    document.body.innerHTML = `
      <span class="settings-saved-indicator" data-saved-for="phone"></span>
      <span class="settings-saved-indicator" data-saved-for="other"></span>`;
    showSavedIndicator('phone');
    const phone = document.querySelector('[data-saved-for="phone"]');
    expect(phone?.classList.contains('visible')).toBe(true);
    expect(document.querySelector('[data-saved-for="other"]')?.classList.contains('visible')).toBe(false);

    vi.advanceTimersByTime(1500);
    expect(phone?.classList.contains('visible')).toBe(false);
  });

  it('ignores a field without an indicator', () => {
    expect(() => showSavedIndicator('missing')).not.toThrow();
  });
});
