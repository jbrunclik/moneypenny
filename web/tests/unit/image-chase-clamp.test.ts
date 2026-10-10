/**
 * The image-load chase (keep a freshly opened chat pinned while images load)
 * switches off when the USER scrolls up. It read any non-programmatic
 * scrollTop decrease as the user: the iOS keyboard closing, or the reserved
 * turn space being released, clamps the position down with no input - the
 * chase went off and later images left a gap above the composer.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/api/files', () => ({ files: { fetchThumbnail: vi.fn() } }));

function list(): { el: HTMLElement; set: (top: number, height: number) => void } {
  document.body.innerHTML = '<div id="messages"></div>';
  const el = document.getElementById('messages')!;
  let top = 1000;
  let height = 2000;
  Object.defineProperty(el, 'clientHeight', { value: 500, configurable: true });
  Object.defineProperty(el, 'scrollHeight', { get: () => height, configurable: true });
  Object.defineProperty(el, 'scrollTop', { get: () => top, set: (v: number) => { top = v; }, configurable: true });
  return {
    el,
    set: (t, h) => {
      top = t;
      height = h;
      el.dispatchEvent(new Event('scroll'));
    },
  };
}

describe('image-load chase vs a clamp', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  async function armed(): Promise<{ el: HTMLElement; set: (top: number, height: number) => void; thumbs: typeof import('@/utils/thumbnails'); dom: typeof import('@/utils/dom') }> {
    const l = list();
    const thumbs = await import('@/utils/thumbnails');
    const dom = await import('@/utils/dom');
    thumbs.enableScrollOnImageLoad();
    // Past the grace period after enabling
    (window as Window & { __scrollModeEnabledTime?: number }).__scrollModeEnabledTime = Date.now() - 60_000;
    l.set(1500, 2000); // at the bottom
    return { ...l, thumbs, dom };
  }

  it('stays on when the list clamps down with no user input (keyboard closing)', async () => {
    const { set, thumbs } = await armed();
    set(1200, 1700); // the content/band changed: max scroll is lower now
    expect(thumbs.isScrollOnImageLoadEnabled()).toBe(true);
  });

  it('switches off when the user scrolls up', async () => {
    const { set, thumbs, dom } = await armed();
    dom.noteUserScrollIntent();
    set(900, 2000);
    expect(thumbs.isScrollOnImageLoadEnabled()).toBe(false);
  });
});
