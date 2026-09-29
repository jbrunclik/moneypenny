/**
 * Mid-run steering: guidance typed while a turn is streaming goes into that
 * turn instead of queueing a new one.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { conversations } from '../api/conversations';
import { toast } from '../components/Toast';
import { addMessageToUI } from '../components/messages';
import { clearMessageInput } from '../components/MessageInput';
import { getElementById } from '../utils/dom';
import { programmaticScrollToBottom } from '../utils/thumbnails';
import type { Message } from '../types/api';
import { getSyncManager } from '../sync/SyncManager';

const log = createLogger('messaging');

/**
 * Mid-run steering: send guidance into a turn that is currently streaming.
 * The server injects it between the agent's tool rounds and also persists
 * it as a regular user message, so it shows up in history either way.
 */
export async function interjectIntoActiveTurn(convId: string, messageText: string): Promise<void> {
  try {
    await conversations.interject(convId, messageText);
  } catch (error) {
    log.error('Failed to send interjection', { error, conversationId: convId });
    toast.error('Failed to steer the response. Please wait for it to finish.');
    return;
  }

  // Render the steering text as a normal user bubble right away
  const userMessage: Message = {
    id: crypto.randomUUID(),
    role: 'user',
    content: messageText,
    created_at: new Date().toISOString(),
  };
  useStore.getState().appendMessage(convId, userMessage);
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (messagesContainer) {
    addMessageToUI(userMessage, messagesContainer, undefined, { animate: true });
    programmaticScrollToBottom(messagesContainer);
  }

  // The route persisted one user message - keep sync counts in step so no
  // false unread badge appears for this conversation
  getSyncManager()?.incrementLocalMessageCount(convId, 1);

  clearMessageInput();
  useStore.getState().setConversationDraft(convId, '');
  toast.info('Steering the current response…');
  log.info('Interjection sent', { conversationId: convId, length: messageText.length });
}
