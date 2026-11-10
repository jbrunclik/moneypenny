import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { _resetScrollWriteStats, scrollWriteStats, writeScrollTop } from '@/utils/scroll-writes';

/** A scroll container whose writes land, or are dropped like iOS mid-coast. */
function fakeList(options: { drops?: boolean; scrollTop?: number; scrollHeight?: number; clientHeight?: number } = {}) {
  let top = options.scrollTop ?? 500;
  const el = {
    get scrollTop() {
      return top;
    },
    set scrollTop(value: number) {
      if (!options.drops) top = value;
    },
    scrollHeight: options.scrollHeight ?? 5000,
    clientHeight: options.clientHeight ?? 800,
    /** The list keeps coasting between frames */
    coast(px: number) {
      top += px;
    },
  };
  return el;
}

let frames: FrameRequestCallback[] = [];
function nextFrame(): void {
  const run = frames;
  frames = [];
  run.forEach((cb) => cb(0));
}

beforeEach(() => {
  frames = [];
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => frames.push(cb));
  _resetScrollWriteStats();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('writeScrollTop', () => {
  it('writes the position and counts a write that landed', () => {
    const list = fakeList();
    writeScrollTop(list as unknown as HTMLElement, 900, 'pagination-prepend');
    expect(list.scrollTop).toBe(900);
    nextFrame();

    const stats = scrollWriteStats()['pagination-prepend'];
    expect(stats.writes).toBe(1);
    expect(stats.dropped).toBe(0);
  });

  it('counts a write iOS dropped, with how far it missed', () => {
    const list = fakeList({ drops: true });
    writeScrollTop(list as unknown as HTMLElement, 900, 'pagination-prepend');
    nextFrame();

    const stats = scrollWriteStats()['pagination-prepend'];
    expect(stats.dropped).toBe(1);
    expect(stats.maxMissPx).toBe(400);
    expect(stats.last).toEqual({ fromPx: 500, targetPx: 900, actualPx: 500, landed: false });
  });

  it('a write that landed while the list kept coasting still counts as landed', () => {
    const list = fakeList();
    writeScrollTop(list as unknown as HTMLElement, 900, 'artifact-resize');
    list.coast(-40);
    nextFrame();

    expect(scrollWriteStats()['artifact-resize'].dropped).toBe(0);
  });

  it('a dropped write during a coast is still caught', () => {
    const list = fakeList({ drops: true });
    writeScrollTop(list as unknown as HTMLElement, 900, 'artifact-resize');
    list.coast(-40);
    nextFrame();

    expect(scrollWriteStats()['artifact-resize'].dropped).toBe(1);
  });

  it('judges against the position the browser could reach (clamped to the end)', () => {
    const list = fakeList({ scrollTop: 4100, scrollHeight: 5000, clientHeight: 800 });
    writeScrollTop(list as unknown as HTMLElement, 4300, 'thinking-collapse');
    nextFrame();

    expect(scrollWriteStats()['thinking-collapse'].dropped).toBe(0);
  });

  it('ignores writes too small to tell apart from a coast', () => {
    const list = fakeList({ drops: true });
    writeScrollTop(list as unknown as HTMLElement, 501, 'image-growth');
    nextFrame();

    expect(scrollWriteStats()['image-growth']).toMatchObject({ writes: 1, verified: 0, dropped: 0 });
  });

  it('returns a copy: later writes do not change an earlier snapshot', () => {
    const before = scrollWriteStats();
    writeScrollTop(fakeList() as unknown as HTMLElement, 900, 'pagination-prepend');
    nextFrame();

    expect(before['pagination-prepend'].writes).toBe(0);
  });
});
