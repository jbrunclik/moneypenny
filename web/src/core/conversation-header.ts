/**
 * Chat header for regular (non-agent) conversations: inline rename plus
 * the pin / archive / delete actions.
 */

import { useStore } from '../state/store';
import type { Conversation } from '../types/api';
import { renderChatHeader } from '../components/ChatHeader';
import { ARCHIVE_ICON, DELETE_ICON, PIN_ICON, UNPIN_ICON } from '../utils/icons';
import { isTempConversation } from './conversation';
import { deleteConversation, renameConversationTo, togglePinConversation } from './conversation-actions';
import { archiveConversation } from './archive';

/**
 * Build the icon action buttons for the regular conversation header.
 */
function buildChatHeaderActions(convId: string): HTMLElement[] {
  const conv = useStore.getState().conversations.find((c) => c.id === convId);
  const pinBtn = document.createElement('button');
  pinBtn.className = 'btn-icon chat-header-action';
  pinBtn.setAttribute('aria-label', conv?.pinned ? 'Unpin conversation' : 'Pin conversation');
  pinBtn.title = conv?.pinned ? 'Unpin conversation' : 'Pin conversation';
  pinBtn.innerHTML = conv?.pinned ? UNPIN_ICON : PIN_ICON;
  pinBtn.addEventListener('click', () => {
    void togglePinConversation(convId).then(() => {
      // Refresh the header so the icon/tooltip reflect the new state
      const updated = useStore.getState().conversations.find((c) => c.id === convId);
      if (updated && useStore.getState().currentConversation?.id === convId) {
        renderChatHeaderForConversation({ ...updated });
      }
    });
  });

  const archiveBtn = document.createElement('button');
  archiveBtn.className = 'btn-icon chat-header-action';
  archiveBtn.setAttribute('aria-label', 'Archive conversation');
  archiveBtn.title = 'Archive conversation';
  archiveBtn.innerHTML = ARCHIVE_ICON;
  archiveBtn.addEventListener('click', () => void archiveConversation(convId));

  const deleteBtn = document.createElement('button');
  deleteBtn.className = 'btn-icon chat-header-action chat-header-action-danger';
  deleteBtn.setAttribute('aria-label', 'Delete conversation');
  deleteBtn.title = 'Delete conversation';
  deleteBtn.innerHTML = DELETE_ICON;
  deleteBtn.addEventListener('click', () => void deleteConversation(convId));

  return [pinBtn, archiveBtn, deleteBtn];
}

/**
 * Render the chat header for a regular (non-agent) conversation.
 * Temp conversations get a plain header (no rename/actions until persisted).
 */
export function renderChatHeaderForConversation(conv: Conversation): void {
  if (isTempConversation(conv.id)) {
    renderChatHeader({ title: conv.title });
    return;
  }
  renderChatHeader({
    title: conv.title,
    onRenameCommit: (newTitle) => void renameConversationTo(conv.id, newTitle),
    actions: buildChatHeaderActions(conv.id),
  });
}
