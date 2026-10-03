/**
 * Wait for the reply to a user message the server already has, whose turn
 * this page is no longer reading (a send's 409, a batch turn after reload).
 */

import { useStore } from '../state/store';
import { SEND_CONFLICT_REPLY_POLL_DELAYS_MS } from '../config';
import { createLogger } from '../utils/logger';
import { conversations } from '../api/conversations';
import { renderMessages, showLoadingIndicator } from '../components/messages';
import { reconcileOutboxWithServer } from './outbox';

const log = createLogger('messaging');

/**
 * Refetch until the server has a reply to `messageId`, or the poll schedule
 * runs out (the next sync then picks the reply up). Returns whether it came.
 */
export async function waitForReplyTo(convId: string, messageId: string): Promise<boolean> {
  if (await refreshConversationMessages(convId, messageId)) return true;
  for (const delayMs of SEND_CONFLICT_REPLY_POLL_DELAYS_MS) {
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    if (await refreshConversationMessages(convId, messageId)) return true;
  }
  log.warn('No reply while waiting for a delivered message', { conversationId: convId, messageId });
  return false;
}

/**
 * Refetch a conversation's messages from the server and re-render if it is
 * still the current conversation. Returns whether an assistant reply follows
 * `messageId`; while none does, the re-render keeps the spinner up.
 */
async function refreshConversationMessages(convId: string, messageId: string): Promise<boolean> {
  try {
    const response = await conversations.get(convId);
    const merged = reconcileOutboxWithServer(convId, response.messages);
    useStore.getState().setMessages(convId, merged, response.message_pagination);
    const sentAt = merged.findIndex((m) => m.id === messageId);
    const replied = sentAt >= 0 && merged.slice(sentAt + 1).some((m) => m.role === 'assistant');
    if (useStore.getState().currentConversation?.id === convId) {
      renderMessages(merged, { hasPendingApproval: response.has_pending_approval });
      // renderMessages clears #messages, the spinner included
      if (!replied) showLoadingIndicator();
    }
    return replied;
  } catch (refreshError) {
    log.warn('Failed to refresh conversation while waiting for a reply', { refreshError, conversationId: convId });
    return false;
  }
}
