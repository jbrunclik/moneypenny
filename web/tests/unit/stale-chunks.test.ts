/**
 * Stale-chunk recovery: a lazy chunk 404 after a deploy reloads the page
 * once; a second failure right after that reload must not loop.
 */
import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { STALE_CHUNK_RELOAD_GUARD_MS } from '@/config';
import { initStaleChunkReload } from '@/core/stale-chunks';

const RELOADED_AT_KEY = 'stale-chunk-reloaded-at';
const NOW = new Date('2026-10-26T10:00:00Z').getTime();

function preloadError(): Event {
  const event = new Event('vite:preloadError', { cancelable: true });
  window.dispatchEvent(event);
  return event;
}

describe('stale chunk reload', () => {
  let reload: ReturnType<typeof vi.fn>;

  beforeAll(() => {
    initStaleChunkReload();
  });

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    sessionStorage.removeItem(RELOADED_AT_KEY);
    reload = vi.fn();
    vi.stubGlobal('location', { ...window.location, reload });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    sessionStorage.removeItem(RELOADED_AT_KEY);
  });

  it('reloads on the first missing chunk and records when', () => {
    const event = preloadError();
    expect(reload).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(true);
    expect(sessionStorage.getItem(RELOADED_AT_KEY)).toBe(String(NOW));
  });

  it('does not reload again within the guard window', () => {
    sessionStorage.setItem(RELOADED_AT_KEY, String(NOW - STALE_CHUNK_RELOAD_GUARD_MS + 1));
    const event = preloadError();
    expect(reload).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });

  it('reloads again once the guard window has passed', () => {
    sessionStorage.setItem(RELOADED_AT_KEY, String(NOW - STALE_CHUNK_RELOAD_GUARD_MS - 1));
    preloadError();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('treats a garbage marker as no previous reload', () => {
    sessionStorage.setItem(RELOADED_AT_KEY, 'not-a-number');
    preloadError();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('does not reload when the marker cannot be written (would loop)', () => {
    vi.spyOn(sessionStorage, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    const event = preloadError();
    expect(reload).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });
});
