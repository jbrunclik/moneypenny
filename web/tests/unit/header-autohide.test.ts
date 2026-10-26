/**
 * The mobile header hides on a user scroll down and comes back on a
 * deliberate scroll up or near the top - never on our own scrolls.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const scroll = vi.hoisted(() => ({
  subscriber: null as (() => void) | null,
  programmatic: false,
  following: false,
}));

vi.mock('@/utils/scroll-manager', () => ({
  onMessagesScroll: (_key: string, fn: () => void) => {
    scroll.subscriber = fn;
  },
}));
vi.mock('@/utils/programmatic-scroll', () => ({
  isProgrammaticScrollActive: () => scroll.programmatic,
  isStreamFollowScroll: () => scroll.following,
}));

import { initHeaderAutoHide, revealHeader } from '@/core/header-autohide';

const VIEWPORT_PX = 600;
const CONTENT_PX = 5000;
let container: HTMLDivElement;

function scrollTo(top: number): void {
  container.scrollTop = top;
  scroll.subscriber?.();
}

const hidden = (): boolean => document.documentElement.classList.contains('header-hidden');

beforeEach(() => {
  container = document.createElement('div');
  container.id = 'messages';
  Object.defineProperty(container, 'scrollHeight', { value: CONTENT_PX });
  Object.defineProperty(container, 'clientHeight', { value: VIEWPORT_PX });
  let top = 0;
  Object.defineProperty(container, 'scrollTop', {
    get: () => top,
    set: (v: number) => {
      top = v;
    },
  });
  document.body.appendChild(container);
  scroll.programmatic = false;
  scroll.following = false;
  initHeaderAutoHide();
  revealHeader();
});

afterEach(() => {
  container.remove();
  document.documentElement.classList.remove('header-hidden');
});

describe('header auto-hide', () => {
  it('hides on a scroll down past the top zone', () => {
    scrollTo(500);
    expect(hidden()).toBe(true);
  });

  it('comes back on a deliberate scroll up', () => {
    scrollTo(1500);
    scrollTo(1200);
    expect(hidden()).toBe(false);
  });

  it('always shows near the top', () => {
    scrollTo(1500);
    scrollTo(1550);
    expect(hidden()).toBe(true);
    scrollTo(40);
    expect(hidden()).toBe(false);
  });

  it('ignores jitter below the direction threshold', () => {
    scrollTo(1500);
    scrollTo(1495);
    expect(hidden()).toBe(true);
  });

  it('stays hidden in the bottom bounce zone', () => {
    const bottom = CONTENT_PX - VIEWPORT_PX;
    scrollTo(bottom);
    expect(hidden()).toBe(true);
    // The rubber band bounces back a few px: reads as up, but stays hidden
    scrollTo(bottom - 20);
    expect(hidden()).toBe(true);
  });

  it('never moves on our own scrolls, and measures the next user scroll from there', () => {
    scroll.programmatic = true;
    scrollTo(3000);
    expect(hidden()).toBe(false);
    scroll.programmatic = false;
    // A small user scroll after the jump is measured from 3000, not from 0
    scrollTo(2995);
    expect(hidden()).toBe(false);
    scrollTo(3100);
    expect(hidden()).toBe(true);
  });

  it('does not hide while following a stream', () => {
    scroll.following = true;
    scrollTo(800);
    scrollTo(1600);
    expect(hidden()).toBe(false);
  });

  it('revealHeader shows it and re-syncs to the current position', () => {
    scrollTo(1500);
    expect(hidden()).toBe(true);
    container.scrollTop = 4000; // a conversation switch moved the view
    revealHeader();
    expect(hidden()).toBe(false);
    scrollTo(3995); // jitter from the new position, not a 2500px scroll up
    expect(hidden()).toBe(false);
    scrollTo(4100);
    expect(hidden()).toBe(true);
  });
});
