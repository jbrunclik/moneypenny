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

import { createConversation, selectConversation, deleteConversation, renameConversation, archiveConversation, unarchiveConversation, navigateToArchive, leaveArchiveView } from './conversation';
import { navigateToPlanner } from './planner';
import { navigateToAgents } from './agents';
import { navigateToSports } from './sports';
import { navigateToLanguage } from './language';
import { navigateToStorage } from './kv-store';
import { openFileInNewTab, downloadFile, copyMessageContent, copyInlineContent } from './file-actions';
import { handleQuizOptionClick, handleQuizContinue, handleQuizInputChange } from '../components/QuizBlock';

const log = createLogger('events');

/**
 * Setup event listeners.
 */
export function setupEventListeners(): void {
  // New chat button
  getElementById('new-chat-btn')?.addEventListener('click', createConversation);

  // Mobile menu button
  getElementById('menu-btn')?.addEventListener('click', toggleSidebar);

  // User footer: menu toggle + menu item actions
  const closeUserMenu = (): void => {
    const menu = document.querySelector('.user-menu');
    menu?.classList.add('hidden');
    getElementById('user-menu-btn')?.setAttribute('aria-expanded', 'false');
  };

  getElementById('user-info')?.addEventListener('click', async (e) => {
    const target = e.target as HTMLElement;

    if (target.closest('#user-menu-btn')) {
      const menu = document.querySelector('.user-menu');
      if (menu) {
        const open = !menu.classList.toggle('hidden');
        getElementById('user-menu-btn')?.setAttribute('aria-expanded', String(open));
      }
      return;
    }

    if (target.closest('#logout-btn')) {
      closeUserMenu();
      logout();
      return;
    }
    if (target.closest('#cost-history-btn')) {
      closeUserMenu();
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
    if (target.closest('#memories-btn')) {
      closeUserMenu();
      navigateToStorage();
      return;
    }
    if (target.closest('.user-menu-archive')) {
      closeUserMenu();
      navigateToArchive();
      return;
    }
    if (target.closest('#settings-btn')) {
      closeUserMenu();
      openSettingsPopup();
    }
  });

  // Close the user menu on outside clicks
  document.addEventListener('click', (e) => {
    const menu = document.querySelector('.user-menu');
    if (!menu || menu.classList.contains('hidden')) return;
    if (!(e.target as HTMLElement).closest('#user-info')) {
      closeUserMenu();
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

    // Handle archive button clicks
    const archiveBtn = (e.target as HTMLElement).closest('[data-archive-id]');
    if (archiveBtn) {
      e.stopPropagation();
      const id = (archiveBtn as HTMLElement).dataset.archiveId;
      if (id) {
        resetSwipeStates();
        archiveConversation(id);
      }
      return;
    }

    // Handle unarchive button clicks
    const unarchiveBtn = (e.target as HTMLElement).closest('[data-unarchive-id]');
    if (unarchiveBtn) {
      e.stopPropagation();
      const id = (unarchiveBtn as HTMLElement).dataset.unarchiveId;
      if (id) {
        resetSwipeStates();
        unarchiveConversation(id);
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

    // Handle archive back button click (leave archive view)
    const archiveBack = (e.target as HTMLElement).closest('[data-archive-back]');
    if (archiveBack) {
      e.stopPropagation();
      leaveArchiveView();
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

    // Handle sports entry click
    const sportsEntry = (e.target as HTMLElement).closest('.sports-entry');
    if (sportsEntry) {
      resetSwipeStates();
      navigateToSports();
      return;
    }

    // Handle language entry click
    const languageEntry = (e.target as HTMLElement).closest('.language-entry');
    if (languageEntry) {
      resetSwipeStates();
      navigateToLanguage();
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

    // Message actions overflow toggle (touch devices)
    const overflowBtn = (e.target as HTMLElement).closest<HTMLElement>('.message-actions-overflow');
    if (overflowBtn) {
      const actionsEl = overflowBtn.closest('.message-actions');
      if (actionsEl) {
        const expanded = actionsEl.classList.toggle('expanded');
        overflowBtn.setAttribute('aria-expanded', String(expanded));
      }
      return;
    }

    // Suggested-prompt chip fills the composer
    const promptChip = (e.target as HTMLElement).closest<HTMLElement>('.welcome-prompt-chip');
    if (promptChip) {
      const input = document.getElementById('message-input') as HTMLTextAreaElement | null;
      if (input) {
        input.value = promptChip.dataset.prompt ?? '';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
      }
      return;
    }

    // Inline copy button (code blocks, tables)
    const inlineCopyBtn = (e.target as HTMLElement).closest('.inline-copy-btn');
    if (inlineCopyBtn) {
      copyInlineContent(inlineCopyBtn as HTMLButtonElement);
      return;
    }

    // Quiz option click (multiple-choice)
    const quizOption = (e.target as HTMLElement).closest('.quiz-option');
    if (quizOption) {
      handleQuizOptionClick(quizOption as HTMLButtonElement);
      return;
    }

    // Quiz continue / send answers click
    const quizContinue = (e.target as HTMLElement).closest('.quiz-continue');
    if (quizContinue) {
      handleQuizContinue(quizContinue as HTMLButtonElement);
    }
  });

  // Quiz text inputs gate the Send button on having an answer
  getElementById('messages')?.addEventListener('input', (e) => {
    const quizInput = (e.target as HTMLElement).closest('.quiz-text-input');
    if (quizInput) {
      handleQuizInputChange(quizInput as HTMLInputElement);
    }
  });
}
