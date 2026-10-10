/**
 * The iOS keyboard opening while a turn is anchored holds the view on the
 * anchor, re-asserting it 150/350/600ms later. Those delayed holds also ran
 * while a send glide was in flight (sent within 600ms of focusing): each
 * jumped the glide to its end and the glide's next frame pulled it back.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const anchor = { held: vi.fn(), anchored: true, atAnchor: true };
vi.mock('@/components/messages/turn-anchor', () => ({
  holdTurnAnchor: () => anchor.held(),
  isAtTurnAnchor: () => anchor.atAnchor,
  isTurnAnchored: () => anchor.anchored,
}));
const scrolling = { gliding: false };
vi.mock('@/utils/dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/dom')>()),
  isSmoothScrolling: () => scrolling.gliding,
}));

import { cleanupKeyboardViewportPinning, initKeyboardViewportPinning } from '@/core/keyboard-viewport';

Element.prototype.scrollTo = vi.fn();

class MockVisualViewport extends EventTarget {
  height = 800;
  offsetTop = 0;
  scale = 1;
}

describe('keyboard opening in an anchored turn', () => {
  let viewport: MockVisualViewport;

  beforeEach(() => {
    vi.useFakeTimers();
    anchor.held.mockClear();
    scrolling.gliding = false;
    document.body.innerHTML = '<div id="messages"></div><textarea id="message-input"></textarea>';
    viewport = new MockVisualViewport();
    Object.defineProperty(window, 'visualViewport', { value: viewport, configurable: true });
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
    initKeyboardViewportPinning();
  });

  afterEach(() => {
    cleanupKeyboardViewportPinning();
    vi.useRealTimers();
  });

  function openKeyboard(): void {
    (document.getElementById('message-input') as HTMLTextAreaElement).focus();
    viewport.height = 500;
    viewport.dispatchEvent(new Event('resize'));
  }

  it('re-asserts the anchor while the keyboard settles', () => {
    openKeyboard();
    vi.advanceTimersByTime(700);
    expect(anchor.held.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it('leaves a send glide in flight alone', () => {
    openKeyboard();
    vi.advanceTimersByTime(20); // the immediate (rAF) hold
    const immediate = anchor.held.mock.calls.length;
    scrolling.gliding = true; // the user sent: the glide runs
    vi.advanceTimersByTime(700);
    expect(anchor.held.mock.calls.length).toBe(immediate);
  });
});
