/**
 * stopMomentumScroll toggles overflow to end an iOS coast - under a finger
 * still moving on the list that ended their drag.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('stopMomentumScroll', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('coarse') }));
  });
  afterEach(() => vi.unstubAllGlobals());

  function spyOverflow(el: HTMLElement): string[] {
    const writes: string[] = [];
    const style = el.style;
    Object.defineProperty(style, 'overflowY', {
      get: () => '',
      set: (v: string) => writes.push(v),
      configurable: true,
    });
    return writes;
  }

  it('stops a coast (no finger on the list)', async () => {
    const { stopMomentumScroll } = await import('@/utils/dom');
    const el = document.createElement('div');
    const writes = spyOverflow(el);
    stopMomentumScroll(el);
    expect(writes).toEqual(['hidden', '']);
  });

  it('never toggles under a finger moving on the list', async () => {
    const { noteUserScrollIntent, stopMomentumScroll } = await import('@/utils/dom');
    const el = document.createElement('div');
    const writes = spyOverflow(el);
    noteUserScrollIntent(); // a touchmove just now
    stopMomentumScroll(el);
    expect(writes).toEqual([]);
  });
});
