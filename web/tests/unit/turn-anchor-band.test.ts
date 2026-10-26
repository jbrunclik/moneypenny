/**
 * Send-to-top anchoring when the band between header and composer is short
 * (the iOS keyboard open). Device check, Oct 26 2026 (standalone PWA, kb19):
 * the keyboard opening moved a one-line anchored turn 55px up, under the
 * header, while the reply streamed below. The "keep the reply's start in
 * view" offset is meant only for a message taller than the band; it applied
 * whenever message + TURN_REPLY_MIN_VISIBLE_PX didn't fit.
 *
 * jsdom has no layout: the list's geometry is faked with the numbers measured
 * in WebKit for the device-check fixture (list 874px -> 490px with the
 * keyboard, scroll-padding-top 130, composer 103 + 12 gap).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/utils/programmatic-scroll', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/programmatic-scroll')>()),
  // The send glide lands at once (its frames are not under test here)
  programmaticScrollToPosition: (el: HTMLElement, top: number, _smooth: boolean, _o: unknown, onDone?: () => void) => {
    el.scrollTop = top;
    onDone?.();
  },
}));

import {
  anchorTurn,
  holdTurnAnchor,
  initTurnAnchorResizeHold,
  resetTurnAnchor,
  turnAnchorDrift,
  turnAnchorEventCounts,
  turnAnchorExtra,
} from '@/components/messages/turn-anchor';
import { TURN_REPLY_MIN_VISIBLE_PX } from '@/config';

const SCROLL_PADDING_TOP_PX = 130;
const COMPOSER_PX = 103;
const LIST_GAP_PX = 12;
const TURN_TOP_PX = 7781;

let resizeCallbacks: Array<() => void> = [];
class FakeResizeObserver {
  constructor(private readonly cb: () => void) {}
  observe(): void {
    resizeCallbacks.push(this.cb);
  }
  disconnect(): void {}
}

function layout(el: HTMLElement, parent: HTMLElement, props: Record<string, number>): void {
  Object.defineProperty(el, 'offsetParent', { value: parent, configurable: true });
  for (const [key, value] of Object.entries(props)) {
    Object.defineProperty(el, key, { value, configurable: true, writable: true });
  }
}

function setup(messageSpanPx: number): { container: HTMLElement; turn: HTMLElement; reply: HTMLElement } {
  document.body.innerHTML = '<div id="messages"><div class="message user"></div><div class="message assistant"></div></div>';
  const container = document.getElementById('messages') as HTMLElement;
  const [turn, reply] = [...container.children] as HTMLElement[];
  Object.defineProperty(container, 'clientHeight', { value: 874, configurable: true, writable: true });
  Object.defineProperty(container, 'scrollTop', { value: 0, configurable: true, writable: true });
  layout(turn!, container, { offsetTop: TURN_TOP_PX });
  layout(reply!, container, { offsetTop: TURN_TOP_PX + messageSpanPx });
  const real = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation((el, pseudo) => {
    if (el !== container) return real(el, pseudo);
    if (pseudo === '::after') return { height: `${COMPOSER_PX}px` } as CSSStyleDeclaration;
    return {
      scrollPaddingTop: `${SCROLL_PADDING_TOP_PX}px`,
      rowGap: `${LIST_GAP_PX}px`,
      paddingBottom: '0px',
    } as CSSStyleDeclaration;
  });
  return { container, turn: turn!, reply: reply! };
}

/** Send: the turn glides onto the anchor (the glide's scroll event lands). */
function send(container: HTMLElement, turn: HTMLElement, reply: HTMLElement): void {
  initTurnAnchorResizeHold(container);
  anchorTurn(container, turn, reply);
  container.dispatchEvent(new Event('scroll'));
}

/** The keyboard opens: the list shrinks to 490px and its observer runs. */
function openKeyboard(container: HTMLElement): void {
  (container as { clientHeight: number }).clientHeight = 490;
  resizeCallbacks.forEach((cb) => cb());
}

/** Where the turn's top sits relative to the anchor line (+ = below it). */
function turnOffsetFromAnchorLine(container: HTMLElement): number {
  return TURN_TOP_PX - container.scrollTop - SCROLL_PADDING_TOP_PX;
}

describe('send-to-top with a short band (keyboard open)', () => {
  beforeEach(() => {
    resizeCallbacks = [];
    vi.stubGlobal('ResizeObserver', FakeResizeObserver);
  });

  afterEach(() => {
    const container = document.getElementById('messages');
    if (container) resetTurnAnchor(container);
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('keeps a short message on the anchor line when the keyboard opens', () => {
    // The fixture's one-line message: 90px + the list gap
    const { container, turn, reply } = setup(102);
    send(container, turn, reply);
    expect(turnOffsetFromAnchorLine(container)).toBe(0);

    const before = turnAnchorEventCounts();
    openKeyboard(container);
    // The list's resize observer held it (the device check reports this)
    expect(turnAnchorEventCounts().resize).toBe(before.resize + 1);
    expect(turnAnchorExtra()).toBe(0);

    // Band 490 - 130 - 115 = 245: the message (102) fits, so it stays at
    // the top - not 17px under the header to show more of the reply
    expect(turnOffsetFromAnchorLine(container)).toBe(0);
    expect(turnAnchorDrift(container)).toBe(0);
  });

  it('keeps it there through the keyboard holds while the reply streams', () => {
    const { container, turn, reply } = setup(102);
    send(container, turn, reply);
    openKeyboard(container);
    // The reply grows mid-stream; the delayed keyboard holds re-fit it
    holdTurnAnchor(container, 'keyboard-delayed');
    expect(turnOffsetFromAnchorLine(container)).toBe(0);
  });

  it('a message taller than the band still keeps the start of the reply in view', () => {
    const span = 400;
    const { container, turn, reply } = setup(span);
    send(container, turn, reply);
    openKeyboard(container);

    const band = 490 - SCROLL_PADDING_TOP_PX - COMPOSER_PX - LIST_GAP_PX;
    expect(turnOffsetFromAnchorLine(container)).toBe(-(span + TURN_REPLY_MIN_VISIBLE_PX - band));
    expect(turnAnchorExtra()).toBe(span + TURN_REPLY_MIN_VISIBLE_PX - band);
  });
});
