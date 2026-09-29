/**
 * Conversation and message actions: delete, rename, auto-title, pin.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { conversations, messages } from '../api/conversations';
import { toast } from '../components/Toast';
import { showConfirm, showPrompt } from '../components/Modal';
import { renderConversationsList } from '../components/Sidebar';
import { renderMessages, updateChatTitle } from '../components/messages';
import { clearConversationHash } from '../router/deeplink';
import { DEFAULT_CONVERSATION_TITLE } from '../types/api';
import { APP_NAME } from '../config';
import { renderChatHeader } from '../components/ChatHeader';
import { updateConversationCost } from './toolbar';
import { isTempConversation } from './conversation';

const log = createLogger('conversation');

/**
 * Remove conversation from UI and clear if it was current.
 */
export function removeConversationFromUI(convId: string): void {
  const store = useStore.getState();
  store.removeConversation(convId);
  renderConversationsList();

  if (store.currentConversation?.id === convId) {
    store.setCurrentConversation(null);
    renderMessages([]);
    updateChatTitle(APP_NAME);
    renderChatHeader(null);
    // The mobile cost chip lives in the persistent mobile header (not the
    // re-rendered chat header) - clear it or the deleted conversation's
    // cost lingers on the welcome screen
    void updateConversationCost(null);
    // Clear the hash since conversation no longer exists
    clearConversationHash();
  }
}

/**
 * Delete a conversation.
 */
export async function deleteConversation(convId: string): Promise<void> {
  const confirmed = await showConfirm({
    title: 'Delete Conversation',
    message: 'Are you sure you want to delete this conversation? This cannot be undone.',
    confirmLabel: 'Delete',
    cancelLabel: 'Cancel',
    danger: true,
  });

  if (!confirmed) return;

  // For temp conversations, just remove locally (no API call needed)
  if (isTempConversation(convId)) {
    removeConversationFromUI(convId);
    return;
  }

  // Check if the conversation is archived
  const store = useStore.getState();
  const isArchived = store.archivedConversations.some(c => c.id === convId);

  try {
    await conversations.delete(convId);

    if (isArchived) {
      store.removeArchivedConversation(convId);
      renderConversationsList();
    } else {
      removeConversationFromUI(convId);
    }
  } catch (error) {
    log.error('Failed to delete conversation', { error, conversationId: convId });
    toast.error('Failed to delete conversation. Please try again.');
  }
}

/**
 * Delete a message.
 */
export async function deleteMessage(messageId: string): Promise<void> {
  const confirmed = await showConfirm({
    title: 'Delete Message',
    message: 'Are you sure you want to delete this message? This cannot be undone.',
    confirmLabel: 'Delete',
    cancelLabel: 'Cancel',
    danger: true,
  });

  if (!confirmed) return;

  try {
    await messages.delete(messageId);
    // Remove the message element from the DOM
    const messageEl = document.querySelector(`.message[data-message-id="${messageId}"]`);
    if (messageEl) {
      messageEl.remove();
    }
    toast.success('Message deleted.');
  } catch (error) {
    log.error('Failed to delete message', { error, messageId });
    toast.error('Failed to delete message. Please try again.');
  }
}

/**
 * Rename a conversation.
 */
export async function renameConversation(convId: string): Promise<void> {
  const store = useStore.getState();
  const conv = store.conversations.find(c => c.id === convId)
    || store.archivedConversations.find(c => c.id === convId);

  if (!conv) {
    log.warn('Conversation not found for rename', { conversationId: convId });
    return;
  }

  const currentTitle = conv.title || DEFAULT_CONVERSATION_TITLE;

  const newTitle = await showPrompt({
    title: 'Rename Conversation',
    message: 'Enter a new name for this conversation:',
    defaultValue: currentTitle,
    placeholder: 'Conversation name',
    confirmLabel: 'Rename',
    cancelLabel: 'Cancel',
  });

  // User cancelled or entered empty string
  if (!newTitle || newTitle.trim() === '') {
    return;
  }

  await renameConversationTo(convId, newTitle);
}

/**
 * Rename a conversation to a specific title (no prompt).
 * Used by the prompt flow above and the chat header inline rename.
 */
export async function renameConversationTo(convId: string, newTitle: string): Promise<void> {
  const store = useStore.getState();
  const conv = store.conversations.find(c => c.id === convId)
    || store.archivedConversations.find(c => c.id === convId);

  if (!conv) {
    log.warn('Conversation not found for rename', { conversationId: convId });
    return;
  }

  const isArchived = store.archivedConversations.some(c => c.id === convId);
  const currentTitle = conv.title || DEFAULT_CONVERSATION_TITLE;
  const trimmedTitle = newTitle.trim();

  // Empty or no change
  if (!trimmedTitle || trimmedTitle === currentTitle) {
    return;
  }

  // Validate length (backend accepts 1-200 chars)
  if (trimmedTitle.length > 200) {
    toast.error('Conversation name is too long (max 200 characters).');
    return;
  }

  // For temp conversations, just update locally (no API call needed)
  if (isTempConversation(convId)) {
    store.updateConversation(convId, { title: trimmedTitle });
    if (store.currentConversation?.id === convId) {
      updateChatTitle(trimmedTitle);
    }
    renderConversationsList();
    toast.success('Conversation renamed.');
    return;
  }

  try {
    await conversations.update(convId, { title: trimmedTitle });

    // Update local state
    if (isArchived) {
      store.updateArchivedConversation(convId, { title: trimmedTitle });
    } else {
      store.updateConversation(convId, { title: trimmedTitle });
    }

    // Update chat title if this is the current conversation
    if (store.currentConversation?.id === convId) {
      updateChatTitle(trimmedTitle);
    }

    // Update sidebar
    renderConversationsList();

    toast.success('Conversation renamed.');
  } catch (error) {
    log.error('Failed to rename conversation', { error, conversationId: convId });
    toast.error('Failed to rename conversation. Please try again.');
  }
}

/**
 * Update conversation title after first message (auto-generated by backend).
 * Title is included in the response from both batch and streaming endpoints.
 */
export function updateConversationTitle(convId: string, title?: string): void {
  if (!title) return;

  const store = useStore.getState();
  if (store.currentConversation?.title === DEFAULT_CONVERSATION_TITLE) {
    store.updateConversation(convId, { title });
    updateChatTitle(title);
    renderConversationsList();
  }
}

/**
 * Pin or unpin a conversation (sidebar ordering).
 */
export async function togglePinConversation(convId: string): Promise<void> {
  if (isTempConversation(convId)) return;

  const store = useStore.getState();
  const conv = store.conversations.find((c) => c.id === convId);
  if (!conv) return;

  const nextPinned = !conv.pinned;
  try {
    if (nextPinned) {
      await conversations.pin(convId);
    } else {
      await conversations.unpin(convId);
    }
  } catch (error) {
    log.error('Failed to toggle pin', { error, conversationId: convId });
    toast.error(nextPinned ? 'Failed to pin conversation.' : 'Failed to unpin conversation.');
    return;
  }

  store.updateConversation(convId, { pinned: nextPinned });
  renderConversationsList();
}
