/**
 * Reporting this device's read state to the server - the read count behind
 * every device's unread badge.
 */

import { conversations as conversationsApi } from '../api/conversations';
import { createLogger } from '../utils/logger';
import type { SyncState } from './sync-state';

const log = createLogger('sync');

/**
 * Record on the server that this device has shown `count` messages.
 * Deduplicated against the last report (and the server's own read count,
 * see the summary merge); a failed report is retried with the next one.
 */
export function reportRead(state: SyncState, convId: string, count: number): void {
  if (convId.startsWith('temp-') || count < 0) return;
  if (state.reportedReadCounts.get(convId) === count) return;
  state.reportedReadCounts.set(convId, count);
  conversationsApi.markRead(convId, count).catch((error: unknown) => {
    state.reportedReadCounts.delete(convId);
    log.debug('Reporting read state failed', { conversationId: convId, error });
  });
}
