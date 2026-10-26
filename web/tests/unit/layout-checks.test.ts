/**
 * Layout checks (core/layout-checks.ts): each invariant reports a violation
 * found at a settled moment and still there on the re-check - never one seen
 * mid-animation - once per page load, rate-limited, touch devices only, and
 * with numbers only.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  LAYOUT_CHECK_CONFIRM_MS,
  LAYOUT_CHECK_SETTLE_MS,
  LAYOUT_REPORT_MIN_INTERVAL_MS,
  LAYOUT_REPORTS_PER_PAGE_MAX,
} from '@/config';

const ctl = { ios: true, touch: false, anchored: false, drift: null as number | null, userScrolled: false, gliding: false };

vi.mock('@/core/error-reporting', () => ({ reportLayoutCheck: vi.fn(() => true) }));
vi.mock('@/components/MessageInput', () => ({ isIOS: () => ctl.ios }));
vi.mock('@/components/messages/turn-anchor', () => ({
  isTurnAnchored: () => ctl.anchored,
  turnAnchorDrift: () => ctl.drift,
}));
vi.mock('@/core/keyboard/touch-guard', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/core/keyboard/touch-guard')>()),
  isTouchActive: () => ctl.touch,
}));
vi.mock('@/utils/dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/dom')>()),
  userScrolledSince: () => ctl.userScrolled,
  isSmoothScrolling: () => ctl.gliding,
}));

import { reportLayoutCheck } from '@/core/error-reporting';
import { initLayoutChecks, stopLayoutChecks } from '@/core/layout-checks';
import { scrollDebug } from '@/utils/dom';

const report = vi.mocked(reportLayoutCheck);
const SETTLED_MS = LAYOUT_CHECK_SETTLE_MS + LAYOUT_CHECK_CONFIRM_MS;

class MockVisualViewport extends EventTarget {
  height = 800;
  offsetTop = 0;
  scale = 1;
}

let viewport: MockVisualViewport;
let composerBottom = 800;

function setInset(px: number): void {
  document.documentElement.style.setProperty('--keyboard-inset', `${px}px`);
}

function setScrollY(px: number): void {
  Object.defineProperty(window, 'scrollY', { value: px, configurable: true });
}

/** The keyboard (350px) is up and the inset applied, as keyboard-viewport does. */
function openKeyboard(): void {
  document.getElementById('message-input')?.focus();
  viewport.height = 450;
  setInset(350);
  composerBottom = 450;
  viewport.dispatchEvent(new Event('resize'));
}

function sent(): { invariant: string; shape: string; measurements: Record<string, number> }[] {
  return report.mock.calls.map(([layout]) => layout);
}

beforeEach(() => {
  vi.useFakeTimers();
  Object.assign(ctl, { ios: true, touch: false, anchored: false, drift: null, userScrolled: false, gliding: false });
  report.mockClear().mockReturnValue(true);
  document.body.innerHTML =
    '<div id="messages"></div><div class="input-area"></div><textarea id="message-input"></textarea>';
  const composer = document.querySelector('.input-area');
  if (!(composer instanceof HTMLElement)) throw new Error('no composer');
  composerBottom = 800;
  vi.spyOn(composer, 'getBoundingClientRect').mockImplementation(
    () => ({ top: composerBottom - 72, bottom: composerBottom, height: 72 }) as DOMRect
  );
  viewport = new MockVisualViewport();
  Object.defineProperty(window, 'visualViewport', { value: viewport, configurable: true });
  Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
  setScrollY(0);
  setInset(0);
  initLayoutChecks();
});

afterEach(() => {
  stopLayoutChecks();
  vi.restoreAllMocks();
  vi.useRealTimers();
  document.documentElement.style.removeProperty('--keyboard-inset');
  setScrollY(0);
});

describe('composer and keyboard', () => {
  it('stays quiet while the composer sits on the keyboard', async () => {
    openKeyboard();
    await vi.advanceTimersByTimeAsync(SETTLED_MS * 2);
    expect(report).not.toHaveBeenCalled();
  });

  it('reports a composer covered by the keyboard, with the numbers', async () => {
    openKeyboard();
    composerBottom = 520;
    await vi.advanceTimersByTimeAsync(SETTLED_MS);
    expect(sent()).toEqual([
      expect.objectContaining({ invariant: 'composer_gap', shape: 'overlap', build_marker: expect.stringMatching(/^kb\d+$/) }),
    ]);
    expect(sent()[0]?.measurements).toMatchObject({ vv_height: 450, keyboard_inset: 350, composer_bottom: 520, deviation: -70 });
  });

  it('reports a dead band between the composer and the keyboard', async () => {
    openKeyboard();
    composerBottom = 380;
    await vi.advanceTimersByTimeAsync(SETTLED_MS);
    expect(sent()).toEqual([expect.objectContaining({ invariant: 'composer_gap', shape: 'gap' })]);
  });
});

describe('settling', () => {
  it('never checks mid-animation', async () => {
    openKeyboard();
    composerBottom = 600; // wrong for the whole animation...
    for (let frame = 0; frame < 20; frame++) {
      viewport.height = 450 + frame;
      setInset(350 - frame);
      viewport.dispatchEvent(new Event('resize'));
      await vi.advanceTimersByTimeAsync(100);
    }
    expect(report).not.toHaveBeenCalled();
    composerBottom = 469; // ...and right once it ends
    await vi.advanceTimersByTimeAsync(SETTLED_MS * 2);
    expect(report).not.toHaveBeenCalled();
  });

  it('waits for a viewport that moves without an event', async () => {
    openKeyboard();
    composerBottom = 600;
    await vi.advanceTimersByTimeAsync(LAYOUT_CHECK_SETTLE_MS - 100);
    viewport.height = 460; // iOS resized silently: not settled yet
    setInset(340);
    await vi.advanceTimersByTimeAsync(SETTLED_MS - 100);
    expect(report).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(SETTLED_MS);
    expect(sent()).toEqual([expect.objectContaining({ invariant: 'composer_gap' })]);
  });

  it('drops a failure that is fixed before the re-check', async () => {
    openKeyboard();
    composerBottom = 600;
    await vi.advanceTimersByTimeAsync(LAYOUT_CHECK_SETTLE_MS + 10);
    composerBottom = 450; // the settle poller caught up
    await vi.advanceTimersByTimeAsync(LAYOUT_CHECK_CONFIRM_MS);
    expect(report).not.toHaveBeenCalled();
  });

  it('drops a failure when the viewport moves again before the re-check', async () => {
    openKeyboard();
    composerBottom = 600;
    await vi.advanceTimersByTimeAsync(LAYOUT_CHECK_SETTLE_MS + 10);
    viewport.dispatchEvent(new Event('resize'));
    composerBottom = 450;
    await vi.advanceTimersByTimeAsync(SETTLED_MS);
    expect(report).not.toHaveBeenCalled();
  });
});

describe('stranded window pan', () => {
  it('reports a window left scrolled with no finger down', async () => {
    setScrollY(291);
    window.dispatchEvent(new Event('scroll'));
    await vi.advanceTimersByTimeAsync(SETTLED_MS);
    expect(sent()).toEqual([expect.objectContaining({ invariant: 'stranded_pan', shape: 'keyboard-closed' })]);
    expect(sent()[0]?.measurements.scroll_y).toBe(291);
  });

  it('leaves a pan under a finger alone', async () => {
    ctl.touch = true;
    setScrollY(291);
    window.dispatchEvent(new Event('scroll'));
    await vi.advanceTimersByTimeAsync(SETTLED_MS);
    expect(report).not.toHaveBeenCalled();
  });
});

describe('keyboard inset', () => {
  it('reports an inset left behind after the keyboard closed', async () => {
    setInset(391);
    viewport.dispatchEvent(new Event('resize'));
    await vi.advanceTimersByTimeAsync(SETTLED_MS);
    expect(sent()).toEqual([expect.objectContaining({ invariant: 'inset_mismatch', shape: 'stuck' })]);
    expect(sent()[0]?.measurements).toMatchObject({ keyboard_inset: 391, expected_inset: 0 });
  });

  it('reports a keyboard the inset missed', async () => {
    document.getElementById('message-input')?.focus();
    viewport.height = 450;
    viewport.dispatchEvent(new Event('resize'));
    await vi.advanceTimersByTimeAsync(SETTLED_MS);
    expect(sent()).toEqual([expect.objectContaining({ invariant: 'inset_mismatch', shape: 'missing' })]);
  });

  it('ignores pinch zoom', async () => {
    setInset(391);
    viewport.scale = 2;
    viewport.dispatchEvent(new Event('resize'));
    await vi.advanceTimersByTimeAsync(SETTLED_MS);
    expect(report).not.toHaveBeenCalled();
  });
});

describe('anchored turn', () => {
  async function restOnAnchorThenOpenKeyboard(driftAfter: number): Promise<void> {
    Object.assign(ctl, { anchored: true, drift: 0 });
    scrollDebug('glide-done'); // the send glide put the view on the anchor
    openKeyboard();
    ctl.drift = driftAfter;
    await vi.advanceTimersByTimeAsync(SETTLED_MS);
  }

  it('stays quiet when the keyboard leaves the turn on its anchor', async () => {
    await restOnAnchorThenOpenKeyboard(2);
    expect(report).not.toHaveBeenCalled();
  });

  it('reports a turn the keyboard moved off its anchor', async () => {
    await restOnAnchorThenOpenKeyboard(-40);
    expect(sent()).toEqual([expect.objectContaining({ invariant: 'anchor_drift', shape: 'keyboard-open' })]);
    expect(sent()[0]?.measurements.deviation).toBe(-40);
  });

  it('leaves a turn the user scrolled alone', async () => {
    ctl.userScrolled = true;
    await restOnAnchorThenOpenKeyboard(-40);
    expect(report).not.toHaveBeenCalled();
  });
});

describe('scroll to the bottom', () => {
  function setList(gap: number): void {
    const list = document.getElementById('messages');
    if (!list) throw new Error('no list');
    Object.defineProperty(list, 'scrollHeight', { value: 2000, configurable: true });
    Object.defineProperty(list, 'clientHeight', { value: 500, configurable: true });
    Object.defineProperty(list, 'scrollTop', { value: 1500 - gap, configurable: true });
  }

  it('reports a scroll that finished short of the bottom', async () => {
    setList(300);
    scrollDebug('bottom-done', { top: 1200, gap: 300 });
    await vi.advanceTimersByTimeAsync(LAYOUT_CHECK_CONFIRM_MS);
    expect(sent()).toEqual([expect.objectContaining({ invariant: 'scroll_bottom_miss', shape: 'short' })]);
    expect(sent()[0]?.measurements.deviation).toBe(300);
  });

  it('stays quiet when it landed, or the user took over', async () => {
    setList(0);
    scrollDebug('bottom-done', { top: 1500, gap: 0 });
    setList(300);
    ctl.userScrolled = true;
    scrollDebug('bottom-done', { top: 1200, gap: 300 });
    await vi.advanceTimersByTimeAsync(LAYOUT_CHECK_CONFIRM_MS);
    expect(report).not.toHaveBeenCalled();
  });
});

describe('reporting', () => {
  async function strandPan(): Promise<void> {
    setScrollY(100);
    window.dispatchEvent(new Event('scroll'));
    await vi.advanceTimersByTimeAsync(SETTLED_MS);
    setScrollY(0);
    window.dispatchEvent(new Event('scroll'));
    await vi.advanceTimersByTimeAsync(SETTLED_MS);
  }

  it('sends one failure once per page load', async () => {
    await strandPan();
    await vi.advanceTimersByTimeAsync(LAYOUT_REPORT_MIN_INTERVAL_MS);
    await strandPan();
    expect(report).toHaveBeenCalledTimes(1);
  });

  it('spaces reports out, sending a skipped one when it recurs later', async () => {
    await strandPan();
    setInset(391); // a second failure right after the first
    viewport.dispatchEvent(new Event('resize'));
    await vi.advanceTimersByTimeAsync(SETTLED_MS);
    expect(report).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(LAYOUT_REPORT_MIN_INTERVAL_MS);
    viewport.dispatchEvent(new Event('resize'));
    await vi.advanceTimersByTimeAsync(SETTLED_MS);
    expect(sent().map((s) => s.invariant)).toEqual(['stranded_pan', 'inset_mismatch']);
  });

  it('stops at the page cap', async () => {
    document.getElementById('message-input')?.focus();
    // [window scroll, applied inset, visual viewport height, composer bottom]:
    // seven distinct failures, one round apart
    const rounds: [number, number, number, number][] = [
      [100, 0, 800, 800], // stranded pan, keyboard closed
      [0, 391, 800, 800], // inset stuck
      [0, 0, 450, 800], // inset missing
      [0, 200, 450, 800], // composer overlap (and inset off)
      [0, 200, 450, 800], // inset off
      [0, 350, 450, 380], // composer gap
      [100, 350, 450, 450], // stranded pan, keyboard open
    ];
    for (const [scrollY, inset, height, bottom] of rounds) {
      Object.assign(viewport, { height });
      setScrollY(scrollY);
      setInset(inset);
      composerBottom = bottom;
      viewport.dispatchEvent(new Event('resize'));
      await vi.advanceTimersByTimeAsync(SETTLED_MS + LAYOUT_REPORT_MIN_INTERVAL_MS);
    }
    expect(report).toHaveBeenCalledTimes(LAYOUT_REPORTS_PER_PAGE_MAX);
    expect(new Set(sent().map((s) => `${s.invariant}|${s.shape}`)).size).toBe(LAYOUT_REPORTS_PER_PAGE_MAX);
  });

  it('carries names and numbers only', async () => {
    const input = document.getElementById('message-input');
    if (input instanceof HTMLTextAreaElement) input.value = 'secret draft';
    openKeyboard();
    composerBottom = 520;
    await vi.advanceTimersByTimeAsync(SETTLED_MS);
    const layout = sent()[0];
    expect(JSON.stringify(layout)).not.toContain('secret');
    expect(Object.values(layout?.measurements ?? {}).every((v) => typeof v === 'number')).toBe(true);
  });

  it('does not run on a desktop', async () => {
    stopLayoutChecks();
    ctl.ios = false;
    initLayoutChecks();
    setInset(391);
    viewport.dispatchEvent(new Event('resize'));
    await vi.advanceTimersByTimeAsync(SETTLED_MS);
    expect(report).not.toHaveBeenCalled();
  });
});
