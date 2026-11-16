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
import { OUTBOX_RESEND_BACKOFF_MS, OUTBOX_RESEND_DELAY_MS, OUTBOX_RESEND_MAX_AGE_MS } from '../config';
import { compareTimestamps } from '../utils/timestamps';
import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { failedEntries, getOutboxEntry, type OutboxEntry } from './outbox';
import { resendOutboxEntry } from './rerun';

const log = createLogger('outbox');

export type ResendTrigger = 'online' | 'visible' | 'open';

// UI-local (F2): a resend pass is running (one at a time per page)
let running = false;
// This page's automatic attempts per message (backoff; a reload starts over)
const attempts = new Map<string, { count: number; lastAt: number }>();

/** Test hook: a fresh page's attempt counts. */
export function _resetResendBackoff(): void {
  attempts.clear();
}

/** Whether a message's backoff allows another automatic try now. */
function backoffAllows(id: string, now: number): boolean {
  const seen = attempts.get(id);
  if (!seen) return true;
  const wait = OUTBOX_RESEND_BACKOFF_MS[seen.count - 1];
  return wait !== undefined && now - seen.lastAt >= wait;
}

/** A newer message in the chat: resending now would land out of order. */
function hasNewerMessage(convId: string, entry: OutboxEntry): boolean {
  return useStore
    .getState()
    .getMessages(convId)
    .some(
      (m) =>
        m.id !== entry.id &&
        m.status !== 'failed' &&
        compareTimestamps(m.created_at, entry.createdAt) > 0
    );
}

/**
 * The entries that may go now: younger than a day (an old request waits for
 * the user's Retry), within their backoff, and with nothing newer after them
 * in the chat (they would land out of order).
 */
function resendable(convId: string): OutboxEntry[] {
  const now = Date.now();
  return failedEntries(convId).filter(
    (e) =>
      Date.parse(e.createdAt) >= now - OUTBOX_RESEND_MAX_AGE_MS &&
      backoffAllows(e.id, now) &&
      !hasNewerMessage(convId, e)
  );
}

/** One automatic attempt; whether it went through (a failed send stays failed). */
async function resendOne(convId: string, entry: OutboxEntry): Promise<boolean> {
  const seen = attempts.get(entry.id);
  attempts.set(entry.id, { count: (seen?.count ?? 0) + 1, lastAt: Date.now() });
  await resendOutboxEntry(convId, entry.id);
  return getOutboxEntry(convId, entry.id)?.status !== 'failed';
}

/** Resend the open conversation's failed sends; how many went through. */
export async function resendFailedSends(trigger: ResendTrigger): Promise<number> {
  if (running || !navigator.onLine) return 0;
  const convId = useStore.getState().currentConversation?.id;
  if (!convId || useStore.getState().getActiveRequest(convId)) return 0;
  const entries = resendable(convId);
  if (entries.length === 0) return 0;

  running = true;
  let count = 0;
  try {
    for (const entry of entries) {
      // The user moved on, or a reply started: the rest wait for the next trigger
      if (useStore.getState().currentConversation?.id !== convId) break;
      if (useStore.getState().getActiveRequest(convId)) break;
      if (await resendOne(convId, entry)) count += 1;
    }
  } finally {
    running = false;
  }
  log.info('Outbox resend', { conversationId: convId, trigger, count, tried: entries.length });
  if (count > 0) toast.info(count === 1 ? 'Resent 1 message.' : `Resent ${count} messages.`);
  return count;
}

// A trigger blocked by a running request (a reply, a recovery poll) checks
// again this many times, OUTBOX_RESEND_DELAY_MS apart, before it lapses
const BLOCKED_RECHECKS = 30;

/**
 * Resend after OUTBOX_RESEND_DELAY_MS; while the open chat has a request
 * running, check again (a stream error's recovery can hold it for seconds,
 * and the trigger would otherwise be lost until the next one).
 */
function scheduleResend(trigger: ResendTrigger, rechecks = BLOCKED_RECHECKS): void {
  setTimeout(() => {
    const convId = useStore.getState().currentConversation?.id;
    if (convId && useStore.getState().getActiveRequest(convId) && rechecks > 0) {
      scheduleResend(trigger, rechecks - 1);
      return;
    }
    void resendFailedSends(trigger);
  }, OUTBOX_RESEND_DELAY_MS);
}

/** Wire the triggers (once, from startup); `conversation:opened` comes from switchToConversation. */
export function initOutboxResend(): void {
  document.addEventListener('conversation:opened', () => scheduleResend('open'));
  window.addEventListener('online', () => scheduleResend('online'));
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') scheduleResend('visible');
  });
}
