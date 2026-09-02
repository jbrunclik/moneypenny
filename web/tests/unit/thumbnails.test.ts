/**
 * Unit tests for thumbnail lazy loading and scroll-on-image-load behavior
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  enableScrollOnImageLoad,
  disableScrollOnImageLoad,
  isScrollOnImageLoadEnabled,
  markProgrammaticScrollStart,
  markProgrammaticScrollEnd,
  isProgrammaticScrollActive,
  programmaticScrollToBottom,
  getThumbnailObserver,
} from '@/utils/thumbnails';
import { files } from '@/api/client';
import { isScrolledToBottom } from '@/utils/dom';

// Mock the files API
vi.mock('@/api/client', () => ({
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

describe('programmatic scroll markers', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('markProgrammaticScrollStart and markProgrammaticScrollEnd are exported', () => {
    // These functions should be callable without errors
    expect(() => markProgrammaticScrollStart()).not.toThrow();
    expect(() => markProgrammaticScrollEnd()).not.toThrow();
  });

  it('markProgrammaticScrollEnd uses delayed reset', () => {
    // Start a programmatic scroll
    markProgrammaticScrollStart();

    // End it - should schedule a delayed reset
    markProgrammaticScrollEnd();

    // The internal state uses a 150ms delay for reset
    // We can't directly test the internal state, but we can verify no errors occur
    vi.advanceTimersByTime(200);
  });

  it('multiple start calls are safe', () => {
    markProgrammaticScrollStart();
    markProgrammaticScrollStart();
    markProgrammaticScrollStart();
    // Should not throw
  });

  it('multiple end calls are safe', () => {
    markProgrammaticScrollEnd();
    markProgrammaticScrollEnd();
    markProgrammaticScrollEnd();
    vi.advanceTimersByTime(500);
    // Should not throw
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

// Note: The race condition fix is primarily tested via E2E tests in conversation.spec.ts
// because it requires real browser timing, IntersectionObserver, and image loading behavior.
// The fix ensures that when an image finishes loading, we check scroll position immediately
// rather than relying solely on the shouldScrollOnImageLoad flag which may not have updated
// yet due to the scroll listener's debounce delay.