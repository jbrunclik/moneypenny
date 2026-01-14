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

import { isTempConversation, switchToConversation } from './conversation';

const log = createLogger('sync-banner');

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

    // Reload the conversation
    if (currentConvId && !isTempConversation(currentConvId)) {
      try {
        const store = useStore.getState();
        const response = await conversations.get(currentConvId);

        // Check if user switched away during API call
        const currentConv = useStore.getState().currentConversation;
        if (currentConv?.id !== currentConvId) {
          log.debug('Reload cancelled - user switched away', {
            requestedId: currentConvId,
            currentId: currentConv?.id,
          });
          return;
        }

        // Store messages and pagination in the per-conversation Maps
        store.setMessages(currentConvId, response.messages, response.message_pagination);

        // Convert response to Conversation object for switchToConversation
        // Use the actual total_count from the response, not the passed messageCount
        // The passed messageCount is from the sync callback and may be stale
        const conv: Conversation = {
          id: response.id,
          title: response.title,
          model: response.model,
          created_at: response.created_at,
          updated_at: response.updated_at,
          messages: response.messages,
        };
        // Pass total message count from pagination for correct sync behavior
        const totalCount = response.message_pagination.total_count;
        switchToConversation(conv, totalCount);
      } catch (error) {
        log.error('Failed to reload conversation', { error, conversationId: currentConvId });
        toast.error('Failed to reload conversation.');
      }
    }
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
