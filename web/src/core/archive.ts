/**
 * Conversation archive: archive/unarchive and the archive view.
 */

import { getSyncManager } from '../sync/SyncManager';
import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { conversations } from '../api/conversations';
import { toast } from '../components/Toast';
import {
  renderConversationsList,
  loadArchivedConversations,
  cleanupArchiveInfiniteScroll,
} from '../components/Sidebar';
import { renderMessages, updateChatTitle } from '../components/messages';
import { setArchiveHash, setConversationHash, clearConversationHash } from '../router/deeplink';
import { APP_NAME } from '../config';
import { renderChatHeader } from '../components/ChatHeader';
import { isTempConversation } from './conversation';

const log = createLogger('conversation');

/**
 * Archive a conversation (no confirmation needed - it's reversible).
 */
export async function archiveConversation(convId: string): Promise<void> {
  if (isTempConversation(convId)) return;

  const store = useStore.getState();
  const conv = store.conversations.find((c) => c.id === convId);
  if (!conv) return;

  try {
    getSyncManager()?.noteLocalChange(convId);
    await conversations.archive(convId);
    // Again once it's committed: a poll started during the request may
    // already see (or not yet see) the write - skip it either way
    getSyncManager()?.noteLocalChange(convId);

    // Move from active to archived list
    store.removeConversation(convId);
    store.addArchivedConversation({ ...conv, archived: true });

    // If this was the current conversation, clear it
    if (store.currentConversation?.id === convId) {
      store.setCurrentConversation(null);
      renderMessages([]);
      updateChatTitle(APP_NAME);
      renderChatHeader(null);
      clearConversationHash();
    }

    renderConversationsList();
    toast.success('Conversation archived.', {
      action: {
        label: 'Undo',
        onClick: () => unarchiveConversation(convId),
      },
    });
  } catch (error) {
    log.error('Failed to archive conversation', { error, conversationId: convId });
    toast.error('Failed to archive conversation.');
  }
}

/**
 * Unarchive a conversation (restore to main list).
 */
export async function unarchiveConversation(convId: string): Promise<void> {
  const store = useStore.getState();
  const conv = store.archivedConversations.find((c) => c.id === convId);
  if (!conv) return;

  try {
    getSyncManager()?.noteLocalChange(convId);
    await conversations.unarchive(convId);
    // Again once it's committed: a poll started during the request may
    // already see (or not yet see) the write - skip it either way
    getSyncManager()?.noteLocalChange(convId);

    // Move from archived to active list
    store.removeArchivedConversation(convId);
    store.addConversation({ ...conv, archived: false });
    renderConversationsList();
    toast.success('Conversation restored.');
  } catch (error) {
    log.error('Failed to unarchive conversation', { error, conversationId: convId });
    toast.error('Failed to unarchive conversation.');
  }
}

/**
 * Navigate to the archive view (full-view, like search).
 * Lazy-loads archived conversations on first open.
 */
export function navigateToArchive(): void {
  const store = useStore.getState();
  store.setIsTrashView(false);
  store.setIsArchiveView(true);
  setArchiveHash();

  // Lazy-load archived conversations on first open
  if (store.archivedConversations.length === 0) {
    loadArchivedConversations();
    return; // loadArchivedConversations will re-render
  }

  renderConversationsList();
}

/**
 * Leave the archive view and return to conversations list.
 */
export function leaveArchiveView(): void {
  const store = useStore.getState();
  store.setIsArchiveView(false);
  cleanupArchiveInfiniteScroll();
  renderConversationsList();
  // Restore the URL: back to the open conversation or home
  const currentId = store.currentConversation?.id;
  if (currentId && !isTempConversation(currentId)) {
    setConversationHash(currentId, { replace: true });
  } else {
    clearConversationHash();
  }
}
