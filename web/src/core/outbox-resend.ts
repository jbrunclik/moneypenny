/**
 * Failed sends go again on their own: when the connection returns, when the
 * app comes back into view (phones drop the connection in the background),
 * and when their conversation opens - the offline toast promised it, and
 * only a manual Retry did it (Nov 16 2026).
 *
 * Only the open conversation's entries (the send pipeline renders into it),
 * younger than a day, oldest first, one at a time, never while a reply runs
 * there. No duplicates:
 * the server answers a repeated client_message_id with 409, read as landed.
 */
import { toast } from '../components/Toast';
import { OUTBOX_RESEND_DELAY_MS, OUTBOX_RESEND_MAX_AGE_MS } from '../config';
import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { failedEntries } from './outbox';
import { resendOutboxEntry } from './rerun';

const log = createLogger('outbox');

export type ResendTrigger = 'online' | 'visible' | 'open';

// UI-local (F2): a resend pass is running (one at a time per page)
let running = false;

/** Resend the open conversation's failed sends; how many went. */
export async function resendFailedSends(trigger: ResendTrigger): Promise<number> {
  if (running || !navigator.onLine) return 0;
  const convId = useStore.getState().currentConversation?.id;
  if (!convId || useStore.getState().getActiveRequest(convId)) return 0;
  // Younger than a day: an old request waits for the user's own Retry
  const oldest = Date.now() - OUTBOX_RESEND_MAX_AGE_MS;
  const entries = failedEntries(convId).filter((e) => Date.parse(e.createdAt) >= oldest);
  if (entries.length === 0) return 0;

  running = true;
  let count = 0;
  try {
    for (const entry of entries) {
      // The user moved on, or a reply started: the rest wait for the next trigger
      if (useStore.getState().currentConversation?.id !== convId) break;
      if (useStore.getState().getActiveRequest(convId)) break;
      await resendOutboxEntry(convId, entry.id);
      count += 1;
    }
  } finally {
    running = false;
  }
  log.info('Outbox resend', { conversationId: convId, trigger, count });
  if (count > 0) toast.info(count === 1 ? 'Resent 1 message.' : `Resent ${count} messages.`);
  return count;
}

/** Resend after OUTBOX_RESEND_DELAY_MS (the checks run again then). */
function scheduleResend(trigger: ResendTrigger): void {
  setTimeout(() => void resendFailedSends(trigger), OUTBOX_RESEND_DELAY_MS);
}

/** Wire the triggers (once, from startup); `conversation:opened` comes from switchToConversation. */
export function initOutboxResend(): void {
  document.addEventListener('conversation:opened', () => scheduleResend('open'));
  window.addEventListener('online', () => scheduleResend('online'));
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') scheduleResend('visible');
  });
}
