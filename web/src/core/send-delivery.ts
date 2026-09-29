/**
 * Delivery state of a user message: confirmed by the server, or failed.
 * Shared by the streaming and batch send paths and the dispatch level.
 */

import { useStore } from '../state/store';
import { setMessageSendState } from '../components/messages/send-state';
import { confirmOutboxEntry, getOutboxEntry, markOutboxFailed } from './outbox';

// Sends that already used their single automatic retry (session-only)
const autoRetriedSends = new Set<string>();

/**
 * Claim the single automatic retry for a send. Returns false when it was
 * already used.
 */
export function claimAutoRetry(messageId: string): boolean {
  if (autoRetriedSends.has(messageId)) return false;
  autoRetriedSends.add(messageId);
  return true;
}

/** A manual retry earns a fresh automatic retry on transient failure. */
export function resetAutoRetry(messageId: string): void {
  autoRetriedSends.delete(messageId);
}

/**
 * The server confirmed receipt of the user message (first stream event or
 * batch response): drop the outbox entry and clear the pending state.
 */
export function confirmDelivery(convId: string, messageId: string): void {
  autoRetriedSends.delete(messageId);
  confirmOutboxEntry(convId, messageId);
  useStore.getState().updateMessage(convId, messageId, { status: undefined });
  setMessageSendState(messageId, 'sent');
}

/**
 * Mark an unconfirmed send as failed (outbox + store + DOM). No-op when the
 * message was already confirmed - a mid-stream failure after delivery must
 * not flag the user message as unsent.
 */
export function markSendFailed(convId: string, messageId: string): void {
  if (!getOutboxEntry(convId, messageId)) return;
  markOutboxFailed(convId, messageId);
  useStore.getState().updateMessage(convId, messageId, { status: 'failed' });
  setMessageSendState(messageId, 'failed');
}
