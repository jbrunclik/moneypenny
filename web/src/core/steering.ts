/**
 * Mid-run steering: guidance typed while a turn is streaming goes into that
 * turn instead of queueing a new one.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { conversations } from '../api/conversations';
import { toast } from '../components/Toast';
import { addMessageToUI, getStreamingMessageElement } from '../components/messages';
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
  // One id for the bubble and the saved message (sync echoes, later deletes)
  const steeringId = crypto.randomUUID();
  try {
    await conversations.interject(convId, messageText, steeringId);
  } catch (error) {
    log.error('Failed to send interjection', { error, conversationId: convId });
    toast.error('Failed to steer the response. Please wait for it to finish.');
    return;
  }

  // Render the steering text as a normal user bubble right away
  const userMessage: Message = {
    id: steeringId,
    role: 'user',
    content: messageText,
    created_at: new Date().toISOString(),
  };
  useStore.getState().appendMessage(convId, userMessage);
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (messagesContainer) {
    addMessageToUI(userMessage, messagesContainer, undefined, { animate: true });
    // Above the reply still streaming: it takes the steering into account
    // and the server orders it that way too. Appended below, the turn
    // ended on a user message and lost regenerate/continue.
    const bubble = messagesContainer.lastElementChild;
    const reply = getStreamingMessageElement(convId);
    if (reply && bubble instanceof HTMLElement && bubble !== reply) {
      reply.before(bubble);
      bubble.scrollIntoView({ block: 'nearest' });
    } else {
      programmaticScrollToBottom(messagesContainer);
    }
  }

  // The route persisted one user message - keep sync counts in step so no
  // false unread badge appears for this conversation
  getSyncManager()?.incrementLocalMessageCount(convId, 1);

  clearMessageInput();
  useStore.getState().setConversationDraft(convId, '');
  toast.info('Steering the current response…');
  log.info('Interjection sent', { conversationId: convId, length: messageText.length });
}

/**
 * Steering the turn never read (sent while its answer was writing - it is
 * read only between tool rounds): the server moved it after the reply.
 * Mirror that and start a reply to it - a regenerate answers the last user
 * message. Only in the conversation on screen (the reply renders there);
 * elsewhere the steering stays last for the user's next turn.
 */
export function answerUnreadSteering(convId: string, steeringId: string): void {
  if (useStore.getState().currentConversation?.id !== convId) return;
  const store = useStore.getState();
  const steering = store.getMessages(convId).find((m) => m.id === steeringId);
  if (steering) {
    store.removeMessage(convId, steeringId);
    store.appendMessage(convId, steering);
  }
  const bubble = document.querySelector(`#messages .message[data-message-id="${steeringId}"]`);
  if (bubble) bubble.parentElement?.appendChild(bubble);
  log.info('Answering unread steering', { conversationId: convId, messageId: steeringId });
  document.dispatchEvent(new CustomEvent('message:answer-steering', { detail: { convId } }));
}
