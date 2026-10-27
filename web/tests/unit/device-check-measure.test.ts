/**
 * Device check measuring and waiting: layout that still moves is never
 * measured, a Stop ends any wait, and the reads match what the keyboard
 * handling writes.
 */
import { afterEach, describe, expect, it } from 'vitest';
import {
  DeviceCheckAbortedError,
  listSnapshot,
  round,
  snapshotMeasurements,
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
  document.documentElement.style.removeProperty('--composer-height');
  document.documentElement.classList.remove('header-hidden');
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
  it('measures an element top in view', () => {
    const list = document.body.appendChild(document.createElement('div'));
    box(list, { scrollHeight: 6000, clientHeight: 800 });
    Object.defineProperty(list, 'scrollTop', { configurable: true, writable: true, value: 5150 });

    const item = list.appendChild(document.createElement('div'));
    box(item, { offsetParent: list, offsetTop: 5222 });
    expect(topInView(list, item)).toBe(72);
    expect(round(12.345)).toBe(12.3);
  });
});

describe('list snapshot (the keyboard-open diagnostics)', () => {
  it('reads the list, the reservation, the header and the composer', () => {
    const list = document.body.appendChild(document.createElement('div'));
    box(list, { clientHeight: 490 });
    Object.defineProperty(list, 'scrollTop', { configurable: true, writable: true, value: 7668.04 });
    list.style.scrollPaddingTop = '130px';
    const reply = list.appendChild(document.createElement('div'));
    reply.setAttribute('data-turn-space', '');
    box(reply, { offsetHeight: 160 });
    document.documentElement.style.setProperty('--composer-height', '103px');
    document.documentElement.classList.add('header-hidden');

    const snapshot = listSnapshot(list);
    expect(snapshot).toEqual({
      scrollTop: 7668,
      clientHeight: 490,
      turnSpacePx: 160,
      scrollPaddingTopPx: 130,
      headerHidden: true,
      composerHeightPx: 103,
    });
    expect(snapshotMeasurements(snapshot, 'after')).toEqual({
      scroll_top_after: 7668,
      client_height_after: 490,
      turn_space_px_after: 160,
      scroll_padding_top_after: 130,
      header_hidden_after: true,
      composer_height_after: 103,
    });
  });

  it('reads no reservation and no composer as 0', () => {
    const list = document.body.appendChild(document.createElement('div'));
    expect(listSnapshot(list)).toMatchObject({ turnSpacePx: 0, composerHeightPx: 0, headerHidden: false });
  });
});
