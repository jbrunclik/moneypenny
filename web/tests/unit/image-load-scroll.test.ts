/**
 * Unit tests for the scroll-on-image-load mode
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  enableScrollOnImageLoad,
  disableScrollOnImageLoad,
  isScrollOnImageLoadEnabled,
} from '@/components/messages/image-load-scroll';
import { beginProgrammaticScroll } from '@/utils/programmatic-scroll';
import { noteUserScrollIntent } from '@/utils/dom';
import { SCROLL_MODE_GRACE_PERIOD_MS } from '@/config';

// Mock the files API
vi.mock('@/api/files', () => ({
  files: {
    fetchThumbnail: vi.fn(),
  },
}));

// Mock dom utilities
vi.mock('@/utils/dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/dom')>();
  return {
    ...actual,
    getElementById: vi.fn((id: string) => {
      if (id === 'messages') {
        return document.getElementById('messages');
      }
      return null;
    }),
    isScrolledToBottom: vi.fn(),
  };
});

describe('enableScrollOnImageLoad', () => {
  beforeEach(() => {
    // Reset state before each test
    disableScrollOnImageLoad();
  });

  it('enables scroll-on-image-load mode', () => {
    expect(isScrollOnImageLoadEnabled()).toBe(false);
    enableScrollOnImageLoad();
    expect(isScrollOnImageLoadEnabled()).toBe(true);
  });

  it('resets pending image loads counter', () => {
    // Enable scroll mode
    enableScrollOnImageLoad();
    expect(isScrollOnImageLoadEnabled()).toBe(true);

    // Disable and re-enable should work correctly
    disableScrollOnImageLoad();
    enableScrollOnImageLoad();
    expect(isScrollOnImageLoadEnabled()).toBe(true);
  });
});

describe('disableScrollOnImageLoad', () => {
  beforeEach(() => {
    enableScrollOnImageLoad();
  });

  it('disables scroll-on-image-load mode', () => {
    expect(isScrollOnImageLoadEnabled()).toBe(true);
    disableScrollOnImageLoad();
    expect(isScrollOnImageLoadEnabled()).toBe(false);
  });

  it('can be called multiple times safely', () => {
    disableScrollOnImageLoad();
    disableScrollOnImageLoad();
    expect(isScrollOnImageLoadEnabled()).toBe(false);
  });
});

describe('isScrollOnImageLoadEnabled', () => {
  beforeEach(() => {
    disableScrollOnImageLoad();
  });

  it('returns false by default', () => {
    expect(isScrollOnImageLoadEnabled()).toBe(false);
  });

  it('returns true after enable', () => {
    enableScrollOnImageLoad();
    expect(isScrollOnImageLoadEnabled()).toBe(true);
  });

  it('returns false after disable', () => {
    enableScrollOnImageLoad();
    disableScrollOnImageLoad();
    expect(isScrollOnImageLoadEnabled()).toBe(false);
  });
});

describe('scroll-on-image-load integration', () => {
  beforeEach(() => {
    disableScrollOnImageLoad();
  });

  afterEach(() => {
    disableScrollOnImageLoad();
  });

  it('scroll mode persists across multiple checks', () => {
    enableScrollOnImageLoad();
    expect(isScrollOnImageLoadEnabled()).toBe(true);
    expect(isScrollOnImageLoadEnabled()).toBe(true);
    expect(isScrollOnImageLoadEnabled()).toBe(true);
  });

  it('can toggle between enabled and disabled states', () => {
    expect(isScrollOnImageLoadEnabled()).toBe(false);
    enableScrollOnImageLoad();
    expect(isScrollOnImageLoadEnabled()).toBe(true);
    disableScrollOnImageLoad();
    expect(isScrollOnImageLoadEnabled()).toBe(false);
    enableScrollOnImageLoad();
    expect(isScrollOnImageLoadEnabled()).toBe(true);
  });
});

// Note: The race condition fix is primarily tested via E2E tests in conversation.spec.ts
// because it requires real browser timing, IntersectionObserver, and image loading behavior.
// The fix ensures that when an image finishes loading, we check scroll position immediately
// rather than relying solely on the shouldScrollOnImageLoad flag which may not have updated
// yet due to the scroll listener's debounce delay.

describe('image-load scroll guard', () => {
  let container: HTMLDivElement;

  /** The list moves to `top` and fires its scroll event. */
  const scrollListTo = (top: number): void => {
    container.scrollTop = top;
    container.dispatchEvent(new Event('scroll'));
  };

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date', 'performance'] });
    document.body.innerHTML = '<div id="messages"></div>';
    container = document.getElementById('messages') as HTMLDivElement;
    Object.defineProperty(container, 'scrollHeight', { configurable: true, value: 3000 });
    Object.defineProperty(container, 'clientHeight', { configurable: true, value: 1000 });
    container.scrollTop = 2000; // pinned to the bottom
    enableScrollOnImageLoad();
    vi.advanceTimersByTime(SCROLL_MODE_GRACE_PERIOD_MS + 100);
  });

  afterEach(() => {
    disableScrollOnImageLoad();
    vi.runOnlyPendingTimers(); // expire programmatic-scroll tokens
    vi.useRealTimers();
  });

  it('a user scroll-up while one of our scrolls is in flight stops the chase', () => {
    // The previous reply's settle still holds its programmatic window when the
    // user wheels up - the chase stayed on and the next image load pulled the
    // view back down (CI scroll log, Oct 24)
    beginProgrammaticScroll();
    noteUserScrollIntent();
    scrollListTo(0);
    expect(isScrollOnImageLoadEnabled()).toBe(false);
  });

  it('a move up inside our programmatic window without user input keeps the chase', () => {
    vi.advanceTimersByTime(5000); // no recent input
    beginProgrammaticScroll();
    scrollListTo(1500);
    expect(isScrollOnImageLoadEnabled()).toBe(true);
  });
});
