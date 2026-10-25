/**
 * The single document-level Escape listener for simple popups: Escape closes
 * only the topmost visible registered popup; Tab is trapped inside it.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  destroyPopupEscapeListener,
  initPopupEscapeListener,
  registerPopupEscapeHandler,
} from '@/utils/popupEscapeHandler';

function addPopup(id: string, visible: boolean): HTMLElement {
  const el = document.createElement('div');
  el.id = id;
  if (!visible) el.classList.add('hidden');
  document.body.appendChild(el);
  return el;
}

function press(key: string): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
  document.dispatchEvent(event);
  return event;
}

describe('popup escape handler', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    initPopupEscapeListener();
  });
  afterEach(() => {
    destroyPopupEscapeListener();
  });

  it('Escape closes a visible popup and prevents the default', () => {
    addPopup('p1', true);
    const onEscape = vi.fn();
    registerPopupEscapeHandler('p1', onEscape);
    const event = press('Escape');
    expect(onEscape).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(true);
  });

  it('ignores hidden and missing popups', () => {
    addPopup('hidden-popup', false);
    const onHidden = vi.fn();
    const onMissing = vi.fn();
    registerPopupEscapeHandler('hidden-popup', onHidden);
    registerPopupEscapeHandler('not-in-dom', onMissing);
    const event = press('Escape');
    expect(onHidden).not.toHaveBeenCalled();
    expect(onMissing).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });

  it('closes only the most recently registered visible popup', () => {
    addPopup('below', true);
    addPopup('above', true);
    const onBelow = vi.fn();
    const onAbove = vi.fn();
    registerPopupEscapeHandler('below', onBelow);
    registerPopupEscapeHandler('above', onAbove);
    press('Escape');
    expect(onAbove).toHaveBeenCalledTimes(1);
    expect(onBelow).not.toHaveBeenCalled();
  });

  it('falls through to a lower popup when the top one is hidden', () => {
    addPopup('below', true);
    addPopup('above', false);
    const onBelow = vi.fn();
    registerPopupEscapeHandler('below', onBelow);
    registerPopupEscapeHandler('above', vi.fn());
    press('Escape');
    expect(onBelow).toHaveBeenCalledTimes(1);
  });

  it('the cleanup function unregisters the popup', () => {
    addPopup('p1', true);
    const onEscape = vi.fn();
    const unregister = registerPopupEscapeHandler('p1', onEscape);
    unregister();
    press('Escape');
    expect(onEscape).not.toHaveBeenCalled();
  });

  it('other keys do nothing', () => {
    addPopup('p1', true);
    const onEscape = vi.fn();
    registerPopupEscapeHandler('p1', onEscape);
    const event = press('Enter');
    expect(onEscape).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });

  it('Tab is trapped while a popup is open, and left alone otherwise', () => {
    // An open popup with nothing focusable: Tab must not leave it
    addPopup('p1', true);
    const unregister = registerPopupEscapeHandler('p1', vi.fn());
    expect(press('Tab').defaultPrevented).toBe(true);
    unregister();
    expect(press('Tab').defaultPrevented).toBe(false);
  });

  it('initializing twice does not double-fire handlers', () => {
    initPopupEscapeListener();
    addPopup('p1', true);
    const onEscape = vi.fn();
    registerPopupEscapeHandler('p1', onEscape);
    press('Escape');
    expect(onEscape).toHaveBeenCalledTimes(1);
  });

  it('destroy removes the listener and every registered handler', () => {
    addPopup('p1', true);
    const onEscape = vi.fn();
    registerPopupEscapeHandler('p1', onEscape);
    destroyPopupEscapeListener();
    initPopupEscapeListener();
    press('Escape');
    expect(onEscape).not.toHaveBeenCalled();
  });
});
