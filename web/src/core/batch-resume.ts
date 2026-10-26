/**
 * Batch turns that outlive their page.
 *
 * The batch endpoint saves the user message before the agent runs and keeps
 * running the turn after the client is gone. When the page dies mid-turn
 * (iPhone PWA suspended or reloaded), the reloaded conversation shows the
 * message with no reply - so wait for it, spinner up, instead of leaving the
 * user to send it again.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { hideLoadingIndicator, showLoadingIndicator } from '../components/messages';
import type { Message } from '../types/api';
import { getSyncManager } from '../sync/SyncManager';
import { clearInflightBatch, readInflightBatch } from './inflight-batches';
import { waitForReplyTo } from './reply-wait';
import { settleTurnFor } from './response-scroll';

const log = createLogger('messaging');

/** Conversations whose reply this page is already waiting for. */
const waiting = new Set<string>();

/**
 * After the conversation renders: if this page died during a batch turn here
 * and the reply isn't in yet, show the spinner and poll until it lands.
 */
export async function resumeInflightBatchIfAny(convId: string, messages: Message[]): Promise<void> {
  // Still live in this tab (conversation switch, not a reload)
  if (useStore.getState().getActiveRequest(convId) || waiting.has(convId)) return;
  const entry = readInflightBatch(convId);
  if (!entry) return;

  const sentAt = messages.findIndex((m) => m.id === entry.messageId);
  const replied = messages.slice(sentAt + 1).some((m) => m.role === 'assistant');
  if (sentAt < 0 || replied) {
    // Never landed (the outbox shows it as failed) or already answered
    clearInflightBatch(convId);
    return;
  }

  log.info('Waiting for a batch reply after reload', { conversationId: convId, messageId: entry.messageId });
  waiting.add(convId);
  showLoadingIndicator();
  try {
    if (await waitForReplyTo(convId, entry.messageId)) {
      // The reload counted the user message; only the reply is new
      getSyncManager()?.incrementLocalMessageCount(convId, 1);
    }
  } finally {
    waiting.delete(convId);
    // A message sent meanwhile has its own entry - leave that one alone
    clearInflightBatch(convId, entry.messageId);
    if (useStore.getState().currentConversation?.id === convId) {
      hideLoadingIndicator();
      settleTurnFor(convId);
    }
  }
}
