/**
 * Touch tracking and the pan guard (core/keyboard/touch-guard.ts): whether
 * a finger is down, and which touchmoves the guard blocks while the
 * keyboard inset is active.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { installTouchTracking, isEditableElement, isTouchActive, setPanGuard } from '@/core/keyboard/touch-guard';

function touchmove(target: Element): boolean {
  const event = new Event('touchmove', { bubbles: true, cancelable: true });
  target.dispatchEvent(event);
  return event.defaultPrevented;
}

describe('keyboard touch guard', () => {
  afterEach(() => {
    setPanGuard(false);
    document.body.replaceChildren();
  });

  it('tracks whether a finger is down', () => {
    installTouchTracking();
    document.dispatchEvent(new Event('touchstart'));
    expect(isTouchActive()).toBe(true);
    document.dispatchEvent(new Event('touchend'));
    expect(isTouchActive()).toBe(false);
  });

  it('knows editable elements', () => {
    expect(isEditableElement(document.createElement('textarea'))).toBe(true);
    expect(isEditableElement(document.createElement('input'))).toBe(true);
    // jsdom has no isContentEditable (undefined); browsers say false
    expect(isEditableElement(document.createElement('div'))).toBeFalsy();
    expect(isEditableElement(null)).toBe(false);
  });

  it('blocks pans nothing can consume while active, and only then', () => {
    const plain = document.createElement('div');
    document.body.appendChild(plain);
    expect(touchmove(plain)).toBe(false);

    setPanGuard(true);
    expect(touchmove(plain)).toBe(true);

    setPanGuard(false);
    expect(touchmove(plain)).toBe(false);
  });

  it('never blocks drags in form controls or scrollable content', () => {
    const textarea = document.createElement('textarea');
    const list = document.createElement('div');
    list.style.overflowY = 'auto';
    Object.defineProperty(list, 'scrollHeight', { value: 500 });
    Object.defineProperty(list, 'clientHeight', { value: 100 });
    const row = document.createElement('div');
    list.appendChild(row);
    document.body.append(textarea, list);
    setPanGuard(true);

    expect(touchmove(textarea)).toBe(false);
    expect(touchmove(row)).toBe(false);
  });
});
