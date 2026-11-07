/**
 * The scroll-to-bottom button: a tap is the user's newest scroll intent, so
 * the flick before it no longer counts as them scrolling. It used to: inside
 * the 1.5s momentum window the image-load guard took the coast left over from
 * that flick, during the button's own jump, for the user scrolling up and
 * cancelled the jump - the button did nothing (CI flake, Nov 2026).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type Dom = typeof import('@/utils/dom');
type Button = typeof import('@/components/ScrollToBottom');

describe('scroll-to-bottom button', () => {
  let dom: Dom;
  let button: Button;
  let now: number;

  beforeEach(async () => {
    now = 1000;
    vi.spyOn(performance, 'now').mockImplementation(() => now);
    vi.stubGlobal('requestAnimationFrame', () => 1);
    vi.stubGlobal('cancelAnimationFrame', () => {});
    vi.resetModules(); // no scroll intent left from another test
    document.body.innerHTML = '<main><div id="messages"></div></main>';
    dom = await import('@/utils/dom');
    button = await import('@/components/ScrollToBottom');
    button.initScrollToBottom();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  async function tap(): Promise<void> {
    document.querySelector<HTMLButtonElement>('.scroll-to-bottom')!.click();
    for (let i = 0; i < 5; i++) await Promise.resolve();
  }

  it('retires the scroll intent of the flick before the tap', async () => {
    dom.noteUserScrollIntent(); // the flick up
    now += 300;
    expect(dom.userScrolledRecently()).toBe(true);

    await tap();

    expect(dom.userScrolledRecently()).toBe(false);
  });

  it('a scroll after the tap is the user again', async () => {
    dom.noteUserScrollIntent();
    await tap();
    now += 50;

    document.getElementById('messages')!.dispatchEvent(new Event('wheel'));

    expect(dom.userScrolledRecently()).toBe(true);
  });
});
