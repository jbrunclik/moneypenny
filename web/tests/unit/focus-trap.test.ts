/**
 * Unit tests for the focus-trap utility.
 *
 * jsdom note: offsetParent is always null in jsdom, so visibility is
 * mocked per-element via Object.defineProperty where needed.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { getFocusableElements, trapTabKey } from '../../src/utils/focus-trap';

function makeVisible(el: HTMLElement): void {
  Object.defineProperty(el, 'offsetParent', {
    get: () => document.body,
    configurable: true,
  });
}

function tabEvent(shiftKey = false): KeyboardEvent {
  return new KeyboardEvent('keydown', { key: 'Tab', shiftKey, cancelable: true });
}

describe('focus-trap', () => {
  let container: HTMLElement;

  beforeEach(() => {
    document.body.innerHTML = '';
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  describe('getFocusableElements', () => {
    it('returns focusable elements in DOM order', () => {
      container.innerHTML = `
        <button id="a">A</button>
        <a href="#" id="b">B</a>
        <input id="c">
      `;
      container.querySelectorAll<HTMLElement>('*').forEach(makeVisible);

      const ids = getFocusableElements(container).map((el) => el.id);
      expect(ids).toEqual(['a', 'b', 'c']);
    });

    it('skips disabled and hidden elements', () => {
      container.innerHTML = `
        <button id="a">A</button>
        <button id="b" disabled>B</button>
        <button id="c">C</button>
      `;
      makeVisible(container.querySelector('#a') as HTMLElement);
      // #c stays "invisible" (offsetParent null, as with display:none)

      const ids = getFocusableElements(container).map((el) => el.id);
      expect(ids).toEqual(['a']);
    });

    it('skips elements with tabindex=-1', () => {
      container.innerHTML = `
        <button id="a" tabindex="-1">A</button>
        <button id="b">B</button>
      `;
      container.querySelectorAll<HTMLElement>('*').forEach(makeVisible);

      const ids = getFocusableElements(container).map((el) => el.id);
      expect(ids).toEqual(['b']);
    });
  });

  describe('trapTabKey', () => {
    beforeEach(() => {
      container.innerHTML = `
        <button id="first">First</button>
        <input id="middle">
        <button id="last">Last</button>
      `;
      container.querySelectorAll<HTMLElement>('*').forEach(makeVisible);
    });

    it('ignores non-Tab keys', () => {
      const e = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true });
      trapTabKey(container, e);
      expect(e.defaultPrevented).toBe(false);
    });

    it('wraps forward from last to first', () => {
      (container.querySelector('#last') as HTMLElement).focus();
      const e = tabEvent();
      trapTabKey(container, e);
      expect(e.defaultPrevented).toBe(true);
      expect(document.activeElement?.id).toBe('first');
    });

    it('wraps backward from first to last', () => {
      (container.querySelector('#first') as HTMLElement).focus();
      const e = tabEvent(true);
      trapTabKey(container, e);
      expect(e.defaultPrevented).toBe(true);
      expect(document.activeElement?.id).toBe('last');
    });

    it('does not intercept tabbing between middle elements', () => {
      (container.querySelector('#middle') as HTMLElement).focus();
      const e = tabEvent();
      trapTabKey(container, e);
      expect(e.defaultPrevented).toBe(false);
    });

    it('pulls focus back when focus is outside the container', () => {
      const outside = document.createElement('button');
      makeVisible(outside);
      document.body.appendChild(outside);
      outside.focus();

      const e = tabEvent();
      trapTabKey(container, e);
      expect(e.defaultPrevented).toBe(true);
      expect(document.activeElement?.id).toBe('first');
    });

    it('prevents default when container has no focusable elements', () => {
      container.innerHTML = '<p>Nothing focusable</p>';
      const e = tabEvent();
      trapTabKey(container, e);
      expect(e.defaultPrevented).toBe(true);
    });
  });
});
