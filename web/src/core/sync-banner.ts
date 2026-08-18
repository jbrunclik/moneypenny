/**
 * Sync banner module.
 * Handles the "new messages available" banner for real-time sync.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { conversations } from '../api/client';
import { toast } from '../components/Toast';
import { getElementById } from '../utils/dom';
import type { Conversation } from '../types/api';

import { isTempConversation, switchToConversation, markAgentViewedAndRefresh } from './conversation';

const log = createLogger('sync-banner');

/**
 * Re-fetch the currently open conversation and re-render it.
 * Used by the "new messages available" banner and by notification taps
 * that target the already-open conversation.
 */
export async function reloadCurrentConversation(conversationId: string): Promise<void> {
  if (isTempConversation(conversationId)) return;

  try {
    const store = useStore.getState();
    const response = await conversations.get(conversationId);

    // Check if user switched away during API call
    const currentConv = useStore.getState().currentConversation;
    if (currentConv?.id !== conversationId) {
      log.debug('Reload cancelled - user switched away', {
        requestedId: conversationId,
        currentId: currentConv?.id,
      });
      return;
    }

    // Store messages and pagination in the per-conversation Maps
    store.setMessages(conversationId, response.messages, response.message_pagination);

    // Keep agent context - dropping is_agent/agent_id here used to strip
    // the agent header and leave new messages permanently "unread"
    const conv: Conversation = {
      id: response.id,
      title: response.title,
      model: response.model,
      created_at: response.created_at,
      updated_at: response.updated_at,
      messages: response.messages,
      is_agent: response.is_agent,
      agent_id: response.agent_id,
      has_pending_approval: response.has_pending_approval,
    };
    // Pass total message count from pagination for correct sync behavior
    const totalCount = response.message_pagination.total_count;
    switchToConversation(conv, totalCount);

    // The newly arrived messages are now on screen - mark them viewed so
    // the unread badge clears (daily briefing reuses one conversation)
    if (response.is_agent && response.agent_id) {
      markAgentViewedAndRefresh(response.agent_id);
    }
  } catch (error) {
    log.error('Failed to reload conversation', { error, conversationId });
    toast.error('Failed to reload conversation.');
  }
}

/**
 * Show banner when new messages are available from another device.
 * Note: We don't use the messageCount parameter from the callback because
 * we get the accurate total_count from the API when reloading the conversation.
 */
export function showNewMessagesAvailableBanner(_messageCount: number): void {
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (!messagesContainer) return;

  // Don't show if banner already exists
  if (messagesContainer.querySelector('.new-messages-banner')) return;

  const store = useStore.getState();
  const currentConvId = store.currentConversation?.id;
  if (!currentConvId) return;

  const banner = document.createElement('div');
  banner.className = 'new-messages-banner';
  banner.innerHTML = `
    <span>New messages available</span>
    <button class="btn btn-small">Reload</button>
  `;

  banner.querySelector('button')?.addEventListener('click', async () => {
    banner.remove();
    await reloadCurrentConversation(currentConvId);
  });

  // Insert at the top of messages container
  messagesContainer.insertBefore(banner, messagesContainer.firstChild);
}

/**
 * Hide the new messages banner.
 */
export function hideNewMessagesAvailableBanner(): void {
  const banner = document.querySelector('.new-messages-banner');
  banner?.remove();
}
