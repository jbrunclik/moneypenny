/**
 * Reusable swipe gesture handler: tells a horizontal swipe from a vertical
 * scroll and from a tap, and completes or snaps back at the threshold.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { createSwipeHandler, isTouchDevice, resetSwipeStates, type SwipeConfig } from '@/gestures/swipe';

const NOW = new Date('2026-10-26T10:00:00Z').getTime();

function touch(x: number, y: number): TouchEvent {
  const point = { clientX: x, clientY: y };
  return { touches: [point], changedTouches: [point] } as unknown as TouchEvent;
}

function setup(overrides: Partial<SwipeConfig> = {}) {
  const target = document.createElement('div');
  const onComplete = vi.fn();
  const onSnapBack = vi.fn();
  const onSwipeMove = vi.fn();
  const handlers = createSwipeHandler({
    shouldStart: () => true,
    getTarget: () => target,
    getTransform: (deltaX) => `translateX(${-deltaX}px)`,
    getInitialState: () => false,
    onComplete,
    onSnapBack,
    onSwipeMove,
    ...overrides,
  });
  return { target, handlers, onComplete, onSnapBack, onSwipeMove };
}

/** Start at (200, 100), move to `to`, end there; returns the end result. */
function gesture(handlers: ReturnType<typeof setup>['handlers'], to: [number, number]): boolean {
  handlers.handleTouchStart(touch(200, 100));
  handlers.handleTouchMove(touch(...to));
  return handlers.handleTouchEnd(touch(...to));
}

describe('createSwipeHandler', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('a long left swipe completes the action and clears the transform', () => {
    const { target, handlers, onComplete } = setup();
    expect(gesture(handlers, [120, 105])).toBe(true);
    expect(onComplete).toHaveBeenCalledWith(target, 80);
    expect(target.style.transform).toBe('');
    expect(target.style.transition).toBe('');
  });

  it('a short swipe snaps back', () => {
    const { handlers, onComplete, onSnapBack } = setup();
    expect(gesture(handlers, [170, 100])).toBe(true);
    expect(onComplete).not.toHaveBeenCalled();
    expect(onSnapBack).toHaveBeenCalled();
  });

  it('moves the target and reports progress while swiping', () => {
    const { target, handlers, onSwipeMove } = setup();
    handlers.handleTouchStart(touch(200, 100));
    handlers.handleTouchMove(touch(160, 100));
    expect(target.style.transform).toBe('translateX(-40px)');
    expect(target.style.transition).toBe('none');
    expect(onSwipeMove).toHaveBeenCalledWith(target, 40, 0.5);
  });

  it('caps the reported progress at 1', () => {
    const { handlers, onSwipeMove } = setup();
    handlers.handleTouchStart(touch(200, 100));
    handlers.handleTouchMove(touch(0, 100));
    expect(onSwipeMove).toHaveBeenLastCalledWith(expect.anything(), 200, 1);
  });

  it('a mostly vertical move is a scroll, not a swipe', () => {
    const { target, handlers, onComplete, onSwipeMove } = setup();
    expect(gesture(handlers, [140, 300])).toBe(true);
    expect(onSwipeMove).not.toHaveBeenCalled();
    expect(onComplete).not.toHaveBeenCalled();
    expect(target.style.transform).toBe('');
  });

  it('a quick touch without movement is a tap and bubbles up', () => {
    const { handlers, onComplete } = setup();
    handlers.handleTouchStart(touch(200, 100));
    vi.advanceTimersByTime(100);
    expect(handlers.handleTouchEnd(touch(202, 101))).toBe(false);
    expect(onComplete).not.toHaveBeenCalled();
  });

  it('a long press without movement is not a tap', () => {
    const { handlers } = setup();
    handlers.handleTouchStart(touch(200, 100));
    vi.advanceTimersByTime(500);
    expect(handlers.handleTouchEnd(touch(200, 100))).toBe(true);
  });

  it('ignores touches when shouldStart says no', () => {
    const { handlers, onComplete } = setup({ shouldStart: () => false });
    expect(gesture(handlers, [100, 100])).toBe(false);
    expect(onComplete).not.toHaveBeenCalled();
  });

  it('a null transform leaves the target in place', () => {
    const { target, handlers, onSwipeMove } = setup({ getTransform: () => null });
    handlers.handleTouchStart(touch(200, 100));
    handlers.handleTouchMove(touch(100, 100));
    expect(target.style.transform).toBe('');
    expect(onSwipeMove).not.toHaveBeenCalled();
  });

  it('touch cancel resets the target and ends the gesture', () => {
    const { target, handlers } = setup();
    handlers.handleTouchStart(touch(200, 100));
    handlers.handleTouchMove(touch(150, 100));
    handlers.handleTouchCancel();
    expect(target.style.transform).toBe('');
    expect(target.style.transition).toBe('');
    expect(handlers.handleTouchEnd(touch(150, 100))).toBe(false);
  });
});

describe('resetSwipeStates', () => {
  function item(): HTMLElement {
    const wrapper = document.createElement('div');
    wrapper.className = 'conversation-item-wrapper swiped';
    const conv = document.createElement('div');
    conv.className = 'conversation-item';
    conv.style.transform = 'translateX(-80px)';
    wrapper.appendChild(conv);
    document.body.appendChild(wrapper);
    return wrapper;
  }

  it('closes every swiped item except the given one', () => {
    document.body.replaceChildren();
    const a = item();
    const b = item();
    resetSwipeStates(b);
    expect(a.classList.contains('swiped')).toBe(false);
    expect(a.querySelector<HTMLElement>('.conversation-item')?.style.transform).toBe('');
    expect(b.classList.contains('swiped')).toBe(true);
    expect(b.querySelector<HTMLElement>('.conversation-item')?.style.transform).toBe('translateX(-80px)');
  });
});

describe('isTouchDevice', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each([true, false])('follows the (hover: none) media query (%s)', (matches) => {
    const matchMedia = vi.fn(() => ({ matches }));
    vi.stubGlobal('matchMedia', matchMedia);
    expect(isTouchDevice()).toBe(matches);
    expect(matchMedia).toHaveBeenCalledWith('(hover: none)');
  });
});
