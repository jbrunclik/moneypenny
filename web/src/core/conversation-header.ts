/**
 * Chat header for regular (non-agent) conversations: inline rename plus
 * the pin / export / archive / delete actions.
 */

import { useStore } from '../state/store';
import type { Conversation } from '../types/api';
import { renderChatHeader } from '../components/ChatHeader';
import { ARCHIVE_ICON, DELETE_ICON, DOWNLOAD_ICON, FOLDER_ICON, PIN_ICON, UNPIN_ICON, setIcon } from '../utils/icons';
import { isTempConversation } from '../utils/conversation-id';
import { deleteConversation, renameConversationTo, togglePinConversation } from './conversation-actions';
import { archiveConversation } from './archive';
import { exportConversation } from './file-actions';

/** The project actions the header offers, injected by startup (F1: core/projects sits above this module). */
interface HeaderProjectActions {
  moveChat: (conversationId: string) => void;
}
// UI-local (F2): injected by startup (F1)
let headerProjectActions: HeaderProjectActions | null = null;

export function setHeaderProjectActions(actions: HeaderProjectActions): void {
  headerProjectActions = actions;
}

/**
 * Build the icon action buttons for the regular conversation header.
 */
function buildChatHeaderActions(convId: string): HTMLElement[] {
  const conv = useStore.getState().conversations.find((c) => c.id === convId);
  const pinBtn = document.createElement('button');
  pinBtn.className = 'btn-icon chat-header-action';
  pinBtn.setAttribute('aria-label', conv?.pinned ? 'Unpin conversation' : 'Pin conversation');
  pinBtn.title = conv?.pinned ? 'Unpin conversation' : 'Pin conversation';
  setIcon(pinBtn, conv?.pinned ? UNPIN_ICON : PIN_ICON);
  pinBtn.addEventListener('click', () => {
    void togglePinConversation(convId).then(() => {
      // Refresh the header so the icon/tooltip reflect the new state
      const updated = useStore.getState().conversations.find((c) => c.id === convId);
      if (updated && useStore.getState().currentConversation?.id === convId) {
        renderChatHeaderForConversation({ ...updated });
      }
    });
  });

  const exportBtn = document.createElement('button');
  exportBtn.className = 'btn-icon chat-header-action';
  exportBtn.setAttribute('aria-label', 'Export as Markdown');
  exportBtn.title = 'Export as Markdown';
  setIcon(exportBtn, DOWNLOAD_ICON);
  exportBtn.addEventListener('click', () => void exportConversation(convId));

  const archiveBtn = document.createElement('button');
  archiveBtn.className = 'btn-icon chat-header-action';
  archiveBtn.setAttribute('aria-label', 'Archive conversation');
  archiveBtn.title = 'Archive conversation';
  setIcon(archiveBtn, ARCHIVE_ICON);
  archiveBtn.addEventListener('click', () => void archiveConversation(convId));

  const moveBtn = document.createElement('button');
  moveBtn.className = 'btn-icon chat-header-action';
  moveBtn.setAttribute('aria-label', 'Move to project');
  moveBtn.title = 'Move to project';
  setIcon(moveBtn, FOLDER_ICON);
  moveBtn.addEventListener('click', () => headerProjectActions?.moveChat(convId));

  const deleteBtn = document.createElement('button');
  deleteBtn.className = 'btn-icon chat-header-action chat-header-action-danger';
  deleteBtn.setAttribute('aria-label', 'Delete conversation');
  deleteBtn.title = 'Delete conversation';
  setIcon(deleteBtn, DELETE_ICON);
  deleteBtn.addEventListener('click', () => void deleteConversation(convId));

  return [pinBtn, moveBtn, exportBtn, archiveBtn, deleteBtn];
}

/**
 * Render the chat header for a regular (non-agent) conversation.
 * Temp conversations get a plain header (no rename/actions until persisted).
 */
export function renderChatHeaderForConversation(conv: Conversation): void {
  const project = projectLink(conv);
  if (isTempConversation(conv.id)) {
    renderChatHeader({ title: conv.title, project });
    return;
  }
  renderChatHeader({
    title: conv.title,
    onRenameCommit: (newTitle) => void renameConversationTo(conv.id, newTitle),
    actions: buildChatHeaderActions(conv.id),
    project,
  });
}

/** A link to the chat's project page (the hash route opens it). */
function projectLink(conv: Conversation): { name: string; href: string } | undefined {
  const projectId =
    conv.project_id ?? useStore.getState().conversations.find((c) => c.id === conv.id)?.project_id;
  const project = projectId ? useStore.getState().projects.find((p) => p.id === projectId) : undefined;
  return project ? { name: project.name, href: `#/projects/${project.id}` } : undefined;
}
