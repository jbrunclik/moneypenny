/**
 * Device check measuring and waiting: layout that still moves is never
 * measured, a Stop ends any wait, and the reads match what the keyboard
 * handling writes.
 */
import { afterEach, describe, expect, it } from 'vitest';
import {
  DeviceCheckAbortedError,
  distanceFromBottom,
  keyboardInset,
  round,
  topInView,
  waitForStable,
  waitUntil,
} from '@/core/device-checks/measure';

function box(el: HTMLElement, values: Record<string, number | Element>): void {
  for (const [key, value] of Object.entries(values)) {
    Object.defineProperty(el, key, { configurable: true, value });
  }
}

afterEach(() => {
  document.documentElement.style.removeProperty('--keyboard-inset');
  document.body.replaceChildren();
});

describe('waits', () => {
  it('waitUntil resolves true once the condition holds, false on timeout', async () => {
    let ready = false;
    setTimeout(() => {
      ready = true;
    }, 60); // the condition turns true later
    await expect(waitUntil(() => ready, 1000, new AbortController().signal)).resolves.toBe(true);
    await expect(waitUntil(() => false, 80, new AbortController().signal)).resolves.toBe(false);
  });

  it('waitForStable returns the value once it stopped changing', async () => {
    const values = [10, 20, 30, 30, 30, 30, 30, 30, 30, 30];
    let i = 0;
    const read = (): number => values[Math.min(i++, values.length - 1)] ?? 30;
    await expect(waitForStable(read, new AbortController().signal, 150, 2000)).resolves.toBe(30);
  });

  it('gives up at the timeout with the latest value', async () => {
    let n = 0;
    const started = performance.now();
    const value = await waitForStable(() => n++, new AbortController().signal, 500, 200);
    expect(performance.now() - started).toBeLessThan(450);
    expect(value).toBeGreaterThan(0);
  });

  it('a Stop ends a wait', async () => {
    const controller = new AbortController();
    const waiting = waitUntil(() => false, 5000, controller.signal);
    controller.abort();
    await expect(waiting).rejects.toBeInstanceOf(DeviceCheckAbortedError);
  });
});

describe('reads', () => {
  it('reads the inset keyboard-viewport.ts writes on <html>', () => {
    expect(keyboardInset()).toBe(0);
    document.documentElement.style.setProperty('--keyboard-inset', '391px');
    expect(keyboardInset()).toBe(391);
  });

  it('measures the distance to the bottom and an element top in view', () => {
    const list = document.body.appendChild(document.createElement('div'));
    box(list, { scrollHeight: 6000, clientHeight: 800 });
    Object.defineProperty(list, 'scrollTop', { configurable: true, writable: true, value: 5150 });
    expect(distanceFromBottom(list)).toBe(50);

    const item = list.appendChild(document.createElement('div'));
    box(item, { offsetParent: list, offsetTop: 5222 });
    expect(topInView(list, item)).toBe(72);
    expect(round(12.345)).toBe(12.3);
  });
});
