/**
 * The orientation restore wrote a scroll percentage: an anchored turn (held
 * by the list's resize observer) landed elsewhere, and a user scrolling since
 * the rotation was overridden.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const anchored = { value: false };
vi.mock('@/components/messages/turn-anchor', () => ({ isTurnAnchored: () => anchored.value }));

describe('orientation restore', () => {
  beforeEach(() => {
    vi.useFakeTimers({
      toFake: ['setTimeout', 'clearTimeout', 'requestAnimationFrame', 'cancelAnimationFrame', 'performance'],
    });
    anchored.value = false;
    document.body.innerHTML = '<div id="messages"></div>';
  });
  afterEach(() => vi.useRealTimers());

  function list(): HTMLElement {
    const el = document.getElementById('messages')!;
    let top = 500;
    Object.defineProperty(el, 'scrollHeight', { value: 2000, configurable: true });
    Object.defineProperty(el, 'clientHeight', { value: 1000, configurable: true });
    Object.defineProperty(el, 'scrollTop', { get: () => top, set: (v: number) => { top = v; }, configurable: true });
    return el;
  }

  async function rotate(el: HTMLElement, between?: () => void): Promise<void> {
    const { initOrientationChangeHandler } = await import('@/components/messages/orientation');
    initOrientationChangeHandler();
    window.dispatchEvent(new Event('orientationchange'));
    Object.defineProperty(el, 'clientHeight', { value: 500, configurable: true }); // landscape
    between?.();
    await vi.advanceTimersByTimeAsync(300);
  }

  it('restores the relative position after a rotation', async () => {
    const el = list();
    await rotate(el);
    expect(el.scrollTop).toBe(750); // 50% of the new max (1500)
  });

  it('leaves an anchored turn to the resize observer', async () => {
    const el = list();
    anchored.value = true;
    await rotate(el);
    expect(el.scrollTop).toBe(500);
  });

  it('keeps where the user scrolled since', async () => {
    const el = list();
    const { noteUserScrollIntent } = await import('@/utils/dom');
    await rotate(el, () => {
      vi.advanceTimersByTime(5);
      noteUserScrollIntent();
      el.scrollTop = 100;
    });
    expect(el.scrollTop).toBe(100);
  });
});
