/**
 * Events module.
 * Handles event listeners and message handlers.
 */

import { createLogger } from '../utils/logger';
import { costs } from '../api/client';
import { toast } from '../components/Toast';
import { logout } from '../auth/google';
import { toggleSidebar } from '../components/Sidebar';
import { openSettingsPopup } from '../components/SettingsPopup';
import { getElementById } from '../utils/dom';
import { resetSwipeStates } from '../gestures/swipe';

import { createConversation, selectConversation, deleteConversation, renameConversation } from './conversation';
import { navigateToPlanner } from './planner';
import { navigateToAgents } from './agents';
import { navigateToStorage } from './kv-store';
import { openFileInNewTab, downloadFile, copyMessageContent, copyInlineContent } from './file-actions';

const log = createLogger('events');

/**
 * Setup event listeners.
 */
export function setupEventListeners(): void {
  // New chat button
  getElementById('new-chat-btn')?.addEventListener('click', createConversation);

  // Mobile menu button
  getElementById('menu-btn')?.addEventListener('click', toggleSidebar);

  // User info area clicks (logout and monthly cost buttons)
  getElementById('user-info')?.addEventListener('click', async (e) => {
    if ((e.target as HTMLElement).closest('#logout-btn')) {
      logout();
      return;
    }
    if ((e.target as HTMLElement).closest('#monthly-cost')) {
      try {
        const history = await costs.getCostHistory(12);
        const { openCostHistory } = await import('../components/CostHistoryPopup');
        openCostHistory(history);
      } catch (error) {
        log.error('Failed to load cost history', { error });
        toast.error('Failed to load cost history.');
      }
      return;
    }
    if ((e.target as HTMLElement).closest('#memories-btn')) {
      navigateToStorage();
      return;
    }
    if ((e.target as HTMLElement).closest('#settings-btn')) {
      openSettingsPopup();
    }
  });

  // Conversation list clicks
  getElementById('conversations-list')?.addEventListener('click', (e) => {
    // Handle rename button clicks
    const renameBtn = (e.target as HTMLElement).closest('[data-rename-id]');
    if (renameBtn) {
      e.stopPropagation();
      const id = (renameBtn as HTMLElement).dataset.renameId;
      if (id) {
        resetSwipeStates();
        renameConversation(id);
      }
      return;
    }

    // Handle delete button clicks
    const deleteBtn = (e.target as HTMLElement).closest('[data-delete-id]');
    if (deleteBtn) {
      e.stopPropagation();
      const id = (deleteBtn as HTMLElement).dataset.deleteId;
      if (id) {
        resetSwipeStates();
        deleteConversation(id);
      }
      return;
    }

    // Handle planner entry click
    const plannerEntry = (e.target as HTMLElement).closest('.planner-entry');
    if (plannerEntry) {
      resetSwipeStates();
      navigateToPlanner();
      return;
    }

    // Handle agents entry click
    const agentsEntry = (e.target as HTMLElement).closest('.agents-entry');
    if (agentsEntry) {
      resetSwipeStates();
      navigateToAgents();
      return;
    }

    // Handle conversation selection
    const convItem = (e.target as HTMLElement).closest('.conversation-item');
    if (convItem) {
      const wrapper = convItem.closest('[data-conv-id]');
      if (wrapper) {
        resetSwipeStates();
        const id = (wrapper as HTMLElement).dataset.convId;
        if (id) selectConversation(id);
      }
    }
  });

  // Document preview (open in new tab), download buttons, and message copy buttons
  getElementById('messages')?.addEventListener('click', (e) => {
    // Document preview (click on filename to open in new tab)
    const previewLink = (e.target as HTMLElement).closest('.document-preview');
    if (previewLink) {
      e.preventDefault();
      const messageId = (previewLink as HTMLElement).dataset.messageId;
      const fileIndex = (previewLink as HTMLElement).dataset.fileIndex;
      const fileName = (previewLink as HTMLElement).dataset.fileName;
      const fileType = (previewLink as HTMLElement).dataset.fileType;
      if (messageId && fileIndex) {
        openFileInNewTab(messageId, parseInt(fileIndex, 10), fileName || 'file', fileType || '');
      }
      return;
    }

    // Document download button
    const downloadBtn = (e.target as HTMLElement).closest('.document-download');
    if (downloadBtn) {
      const messageId = (downloadBtn as HTMLElement).dataset.messageId;
      const fileIndex = (downloadBtn as HTMLElement).dataset.fileIndex;
      const fileName = (downloadBtn as HTMLElement).dataset.fileName;
      if (messageId && fileIndex) {
        downloadFile(messageId, parseInt(fileIndex, 10), fileName || `file-${fileIndex}`);
      }
      return;
    }

    const copyBtn = (e.target as HTMLElement).closest('.message-copy-btn');
    if (copyBtn) {
      copyMessageContent(copyBtn as HTMLButtonElement);
      return;
    }

    // Inline copy button (code blocks, tables)
    const inlineCopyBtn = (e.target as HTMLElement).closest('.inline-copy-btn');
    if (inlineCopyBtn) {
      copyInlineContent(inlineCopyBtn as HTMLButtonElement);
    }
  });
}
