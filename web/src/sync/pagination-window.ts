/**
 * Where a synced conversation stands relative to the paginated list: inside
 * the part already loaded, or older than the page load (pagination brings it
 * when the user scrolls, so it is neither added nor counted unread).
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';

const log = createLogger('sync');

/**
 * Slack between a conversation's last update and the initial page load:
 * both are server times, so a small buffer covers the timing difference.
 */
const PAGE_LOAD_BUFFER_MS = 5 * 1000;

/** Whether `updatedAt` falls inside the part of the list already loaded. */
export function inLoadedWindow(updatedAt: string): boolean {
  const store = useStore.getState();
  if (!store.conversationsPagination.hasMore) return true;
  const unpinned = store.conversations.filter((c) => !c.pinned);
  const oldest = unpinned[unpinned.length - 1];
  if (!oldest) return true;
  return new Date(updatedAt).getTime() >= new Date(oldest.updated_at).getTime();
}

/**
 * Determine if a conversation was discovered via pagination (not actually new).
 *
 * Compares updated_at (server time) to initialLoadTime (server time from first sync).
 * If older than initialLoadTime minus a buffer, it's pagination discovery.
 *
 * Without initialLoadTime yet (first sync) the two can't be told apart:
 * treated as pagination-discovered to be safe (no false unread badges).
 * Invalid timestamps default the same way.
 *
 * @param initialLoadTime server time of the first full sync, if any
 * @param updatedAt ISO timestamp of when conversation was last updated (server time)
 * @returns true if conversation is pagination-discovered, false if actually new
 */
export function isPaginationDiscovered(initialLoadTime: string | null, updatedAt: string): boolean {
  if (!initialLoadTime) return true;

  // Both timestamps are server time, so no clock skew issues
  try {
    const updatedDate = new Date(updatedAt);
    const initialDate = new Date(initialLoadTime);

    // Check for invalid dates (new Date() doesn't throw, returns Invalid Date)
    if (isNaN(updatedDate.getTime()) || isNaN(initialDate.getTime())) {
      log.warn('Invalid timestamp for pagination detection', { updatedAt, initialLoadTime });
      return true;
    }

    return updatedDate.getTime() < initialDate.getTime() - PAGE_LOAD_BUFFER_MS;
  } catch (error) {
    log.warn('Failed to parse timestamp for pagination detection', { updatedAt, initialLoadTime, error });
    return true;
  }
}
