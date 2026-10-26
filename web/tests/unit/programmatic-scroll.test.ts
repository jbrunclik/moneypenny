/**
 * Programmatic-scroll tokens, the stream-follow marker and the scroll
 * wrappers that hold a token while they scroll.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  beginProgrammaticScroll,
  endProgrammaticScroll,
  isProgrammaticScrollActive,
  isStreamFollowScroll,
  markStreamFollowScroll,
  programmaticScrollToBottom,
} from '@/utils/programmatic-scroll';

describe('programmatic scroll markers', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('a token holds the flag until shortly after it ends', () => {
    const token = beginProgrammaticScroll();
    expect(isProgrammaticScrollActive()).toBe(true);
    endProgrammaticScroll(token);
    // Its scroll events dispatch a frame later and still count as ours
    expect(isProgrammaticScrollActive()).toBe(true);
    vi.advanceTimersByTime(200);
    expect(isProgrammaticScrollActive()).toBe(false);
  });

  it('overlapping scrolls do not end each other early', () => {
    // The reserved-space release ending while the send glide still ran used
    // to clear the single flag and expose the glide's last frames
    const glide = beginProgrammaticScroll();
    const release = beginProgrammaticScroll();
    endProgrammaticScroll(release);
    vi.advanceTimersByTime(500);
    expect(isProgrammaticScrollActive()).toBe(true);
    endProgrammaticScroll(glide);
    vi.advanceTimersByTime(200);
    expect(isProgrammaticScrollActive()).toBe(false);
  });

  it('a token that is never ended expires instead of muting user scrolls forever', () => {
    beginProgrammaticScroll();
    vi.advanceTimersByTime(3100);
    expect(isProgrammaticScrollActive()).toBe(false);
  });
});

describe('programmaticScrollToBottom', () => {
  function scroller(scrollTop: number, scrollHeight: number, clientHeight: number): HTMLElement {
    const el = document.createElement('div');
    Object.defineProperty(el, 'scrollHeight', { value: scrollHeight, configurable: true });
    Object.defineProperty(el, 'clientHeight', { value: clientHeight, configurable: true });
    Object.defineProperty(el, 'scrollTop', { value: scrollTop, writable: true, configurable: true });
    el.scrollTo = vi.fn();
    return el;
  }

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.advanceTimersByTime(1000); // drain any pending marker reset
    vi.useRealTimers();
  });

  it('marks a programmatic scroll while scrolling a list that is not at the bottom', () => {
    const el = scroller(0, 1000, 500);
    programmaticScrollToBottom(el);
    expect(el.scrollTo).toHaveBeenCalled();
    expect(isProgrammaticScrollActive()).toBe(true);
    vi.advanceTimersByTime(200);
    expect(isProgrammaticScrollActive()).toBe(false);
  });

  it('does not open a programmatic window when the list is already pinned to the bottom', () => {
    // A no-op scrollTo fires no scroll event; a lingering flag would only
    // swallow the next genuine user scroll (Storage page header auto-hide flake)
    const el = scroller(500, 1000, 500);
    programmaticScrollToBottom(el);
    expect(el.scrollTo).not.toHaveBeenCalled();
    expect(isProgrammaticScrollActive()).toBe(false);
  });

  it('treats an empty container (nothing to scroll) as already pinned', () => {
    const el = scroller(0, 300, 300);
    programmaticScrollToBottom(el);
    expect(isProgrammaticScrollActive()).toBe(false);
  });
});

describe('stream-follow marker', () => {
  function list(scrollTop: number, scrollHeight = 2000): HTMLElement {
    const el = document.createElement('div');
    Object.defineProperty(el, 'scrollHeight', { value: scrollHeight, configurable: true });
    Object.defineProperty(el, 'clientHeight', { value: 500, configurable: true });
    Object.defineProperty(el, 'scrollTop', { value: scrollTop, writable: true, configurable: true });
    return el;
  }

  it('matches the scroll event of the position a follow scroll wrote', () => {
    markStreamFollowScroll(1500);
    expect(isStreamFollowScroll(list(1500))).toBe(true);
  });

  it('counts a clamp below that position to the new bottom', () => {
    markStreamFollowScroll(1500);
    expect(isStreamFollowScroll(list(1200, 1700))).toBe(true);
  });

  it('is spent on the first event that is not one', () => {
    markStreamFollowScroll(1500);
    expect(isStreamFollowScroll(list(900))).toBe(false);
    expect(isStreamFollowScroll(list(1500))).toBe(false);
  });
});
