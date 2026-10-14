/**
 * Stale-chunk recovery after a deploy.
 *
 * Each build empties static/assets, so a page loaded before a deploy still
 * references the previous build's hashed chunks: its first lazy import (PDF
 * viewer, settings, agent editor) 404s. Vite reports that as a
 * `vite:preloadError` event; reload once so the page picks up the current
 * build. The composer draft is persisted, so nothing unsent is lost.
 */

import { STALE_CHUNK_RELOAD_GUARD_MS } from '../config';
import { createLogger } from '../utils/logger';

const log = createLogger('stale-chunks');

const RELOADED_AT_KEY = 'stale-chunk-reloaded-at';

function readReloadedAt(): number {
  try {
    return Number(sessionStorage.getItem(RELOADED_AT_KEY)) || 0;
  } catch {
    return 0;
  }
}

function writeReloadedAt(now: number): boolean {
  try {
    sessionStorage.setItem(RELOADED_AT_KEY, String(now));
    return true;
  } catch {
    // Without the marker a reload could loop - let the error surface instead
    return false;
  }
}

export function initStaleChunkReload(): void {
  window.addEventListener('vite:preloadError', (event) => {
    const now = Date.now();
    if (now - readReloadedAt() < STALE_CHUNK_RELOAD_GUARD_MS) {
      log.warn('Lazy chunk failed again right after a reload', { event });
      return;
    }
    if (!writeReloadedAt(now)) return;
    log.info('Lazy chunk missing (page older than the deploy), reloading');
    event.preventDefault();
    window.location.reload();
  });
}
