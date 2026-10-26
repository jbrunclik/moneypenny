/**
 * Events module.
 * Handles event listeners and message handlers.
 */

import { createLogger } from '../utils/logger';
import { costs } from '../api/costs';
import { toast } from '../components/Toast';
import { openCostHistory } from '../components/CostHistoryPopup';
import { logout } from '../auth/google';
import { toggleSidebar } from '../components/Sidebar';
import { getElementById } from '../utils/dom';
import { resetSwipeStates } from '../gestures/swipe';
import { showActionSheet } from '../components/ActionSheet';
import { useStore } from '../state/store';
import { ARCHIVE_ICON, DELETE_ICON, EDIT_ICON, PIN_ICON, UNARCHIVE_ICON, UNPIN_ICON } from '../utils/icons';

import { createConversation, selectConversation } from './conversation';
import { deleteConversation, renameConversation, togglePinConversation } from './conversation-actions';
import { archiveConversation, unarchiveConversation, navigateToArchive, leaveArchiveView } from './archive';
import { restoreConversation, deleteConversationForever, emptyTrash, navigateToTrash, leaveTrashView } from './trash';
import { enterSelectionMode } from '../components/SidebarSelection';
import { navigateToPlanner } from './planner';
import { navigateToAgents } from './agents';
import { navigateToSports } from './sports';
import { navigateToLanguage } from './language';
import { navigateToStorage } from './kv-store';
import { openFileInNewTab, downloadFile, copyMessageContent, copyInlineContent } from './file-actions';
import { handleQuizOptionClick, handleQuizContinue, handleQuizInputChange } from '../components/QuizBlock';

const log = createLogger('events');

/**
 * Bottom sheet with all conversation actions - replaces the crammed
 * multi-button swipe row on touch devices.
 */
function openConversationActionSheet(convId: string, archived: boolean): void {
  const store = useStore.getState();
  const conv = archived
    ? store.archivedConversations.find((c) => c.id === convId)
    : store.conversations.find((c) => c.id === convId);
  const title = conv?.title || 'Conversation';

  const actions = archived
    ? [
        { label: 'Rename', icon: EDIT_ICON, onSelect: () => renameConversation(convId) },
        { label: 'Unarchive', icon: UNARCHIVE_ICON, onSelect: () => unarchiveConversation(convId) },
        {
          label: 'Delete',
          icon: DELETE_ICON,
          danger: true,
          onSelect: () => deleteConversation(convId),
        },
      ]
    : [
        {
          label: conv?.pinned ? 'Unpin' : 'Pin',
          icon: conv?.pinned ? UNPIN_ICON : PIN_ICON,
          onSelect: () => void togglePinConversation(convId),
        },
        { label: 'Rename', icon: EDIT_ICON, onSelect: () => renameConversation(convId) },
        { label: 'Archive', icon: ARCHIVE_ICON, onSelect: () => archiveConversation(convId) },
        {
          label: 'Delete',
          icon: DELETE_ICON,
          danger: true,
          onSelect: () => deleteConversation(convId),
        },
      ];

  showActionSheet(title, actions);
}

/** Close the user footer menu. */
function closeUserMenu(): void {
  const menu = document.querySelector('.user-menu');
  menu?.classList.add('hidden');
  getElementById('user-menu-btn')?.setAttribute('aria-expanded', 'false');
}

async function openCostHistoryFromMenu(): Promise<void> {
  try {
    const history = await costs.getCostHistory(12);
    openCostHistory(history);
  } catch (error) {
    log.error('Failed to load cost history', { error });
    toast.error('Failed to load cost history.');
  }
}

async function openAdminFromMenu(): Promise<void> {
  try {
    const { openAdminPage } = await import('../components/AdminPage');
    await openAdminPage();
  } catch (error) {
    // A chunk deleted by a deploy is handled by the stale-chunk reload;
    // anything else surfaces here instead of failing silently
    log.error('Failed to open the admin page', { error });
    toast.error('Failed to open the admin page.');
  }
}

/** User menu items: each closes the menu, then runs its action. */
const USER_MENU_ACTIONS: ReadonlyArray<readonly [selector: string, run: () => void | Promise<void>]> = [
  ['#logout-btn', () => logout()],
  ['#cost-history-btn', openCostHistoryFromMenu],
  [
    '#memories-btn',
    () => void navigateToStorage().catch((error: unknown) => log.error('Failed to open storage', { error })),
  ],
  ['#admin-btn', openAdminFromMenu],
  ['.user-menu-archive', () => navigateToArchive()],
  ['.user-menu-trash', () => navigateToTrash()],
  ['#select-chats-btn', () => enterSelectionMode()],
  ['#settings-btn', () => void import('../components/SettingsPopup').then((m) => m.openSettingsPopup())],
];

async function handleUserInfoClick(e: MouseEvent): Promise<void> {
  const target = e.target as HTMLElement;

  if (target.closest('#user-menu-btn')) {
    const menu = document.querySelector('.user-menu');
    if (menu) {
      const open = !menu.classList.toggle('hidden');
      getElementById('user-menu-btn')?.setAttribute('aria-expanded', String(open));
    }
    return;
  }

  const action = USER_MENU_ACTIONS.find(([selector]) => target.closest(selector));
  if (action) {
    closeUserMenu();
    await action[1]();
  }
}

/**
 * The row a roving-tabindex key moves to in a list of `count` rows, or null
 * to stay (no wrap past either end). `current` is -1 when focus is not on a row.
 */
export function nextRovingIndex(key: string, current: number, count: number): number | null {
  if (key === 'Home') return 0;
  if (key === 'End') return count - 1;
  if (current === -1) return key === 'ArrowDown' ? 0 : count - 1;
  const next = current + (key === 'ArrowDown' ? 1 : -1);
  return next < 0 || next >= count ? null : next;
}

const ROVING_KEYS: ReadonlySet<string> = new Set(['ArrowDown', 'ArrowUp', 'Home', 'End']);

/**
 * Conversation list keyboard navigation: Enter/Space activate the focused
 * row or nav entry; arrows move a roving tabindex through rows.
 */
function handleConversationListKeydown(e: KeyboardEvent): void {
  const target = e.target as HTMLElement;

  if (e.key === 'Enter' || e.key === ' ') {
    const actionable = target.closest<HTMLElement>(
      '.conversation-item, .planner-entry, .agents-entry, .sports-entry, .language-entry'
    );
    if (actionable) {
      e.preventDefault();
      actionable.click();
    }
    return;
  }

  if (!ROVING_KEYS.has(e.key)) return;

  const items = Array.from(
    document.querySelectorAll<HTMLElement>('#conversations-list .conversation-item')
  );
  if (items.length === 0) return;

  const current = items.indexOf(target.closest('.conversation-item') as HTMLElement);
  const next = nextRovingIndex(e.key, current, items.length);
  const nextItem = next === null ? undefined : items[next];
  if (!nextItem) return;
  e.preventDefault();
  items.forEach((item) => item.setAttribute('tabindex', '-1'));
  nextItem.setAttribute('tabindex', '0');
  nextItem.focus();
}

/** A delegated click target: the first action whose selector matches runs. */
interface ClickAction {
  selector: string;
  /** Keep the click from reaching the row underneath (row buttons) */
  stop?: boolean;
  run: (el: HTMLElement, e: MouseEvent) => void;
}

/** Run the first matching action for a delegated click; true when one ran. */
function runClickAction(actions: readonly ClickAction[], e: MouseEvent): boolean {
  const target = e.target as HTMLElement;
  for (const action of actions) {
    const el = target.closest<HTMLElement>(action.selector);
    if (!el) continue;
    if (action.stop) e.stopPropagation();
    action.run(el, e);
    return true;
  }
  return false;
}

/** A row button acting on the conversation id in `data-*`: closes open swipes first. */
function onRowId(key: string, act: (id: string) => unknown): ClickAction['run'] {
  return (el) => {
    const id = el.dataset[key];
    if (id) {
      resetSwipeStates();
      void act(id);
    }
  };
}

/** A sidebar entry (planner, agents, programs): closes open swipes first. */
function onEntry(open: () => unknown): ClickAction['run'] {
  return () => {
    resetSwipeStates();
    void open();
  };
}

const CONVERSATION_LIST_ACTIONS: readonly ClickAction[] = [
  { selector: '[data-rename-id]', stop: true, run: onRowId('renameId', renameConversation) },
  {
    // The "more" button: all actions in a sheet
    selector: '[data-more-id], [data-more-archived-id]',
    stop: true,
    run: (el) => {
      if (el.dataset.moreId) {
        openConversationActionSheet(el.dataset.moreId, false);
      } else if (el.dataset.moreArchivedId) {
        openConversationActionSheet(el.dataset.moreArchivedId, true);
      }
    },
  },
  {
    selector: '[data-pin-id]',
    stop: true,
    run: (el) => {
      const id = el.dataset.pinId;
      if (id) void togglePinConversation(id);
    },
  },
  { selector: '[data-archive-id]', stop: true, run: onRowId('archiveId', archiveConversation) },
  { selector: '[data-unarchive-id]', stop: true, run: onRowId('unarchiveId', unarchiveConversation) },
  // Trash view: restore, delete forever, empty, back
  { selector: '[data-restore-id]', stop: true, run: onRowId('restoreId', restoreConversation) },
  { selector: '[data-delete-forever-id]', stop: true, run: onRowId('deleteForeverId', deleteConversationForever) },
  { selector: '[data-empty-trash]', stop: true, run: () => void emptyTrash() },
  { selector: '[data-trash-back]', stop: true, run: () => leaveTrashView() },
  { selector: '[data-delete-id]', stop: true, run: onRowId('deleteId', deleteConversation) },
  { selector: '[data-archive-back]', stop: true, run: () => leaveArchiveView() },
  { selector: '.planner-entry', run: onEntry(navigateToPlanner) },
  {
    selector: '.agents-entry',
    run: onEntry(() => navigateToAgents().catch((error: unknown) => log.error('Failed to open agents', { error }))),
  },
  { selector: '.sports-entry', run: onEntry(navigateToSports) },
  { selector: '.language-entry', run: onEntry(navigateToLanguage) },
  {
    // Conversation selection
    selector: '.conversation-item',
    run: (el) => {
      const wrapper = el.closest<HTMLElement>('[data-conv-id]');
      if (wrapper) {
        resetSwipeStates();
        const id = wrapper.dataset.convId;
        if (id) void selectConversation(id);
      }
    },
  },
];

/** Document preview: PDFs open in the inline viewer, other documents in a new tab. */
function openDocumentPreview(el: HTMLElement, e: MouseEvent): void {
  e.preventDefault();
  const { messageId, fileIndex, fileName, fileType } = el.dataset;
  if (!messageId || !fileIndex) return;
  // PDFs open in the inline viewer (window.open is pop-up-blocked and
  // broken in the installed PWA); other documents keep the new tab
  if (fileType === 'application/pdf') {
    void import('../components/PdfViewer').then(({ openPdfViewer }) =>
      openPdfViewer(messageId, parseInt(fileIndex, 10), fileName || 'file.pdf')
    );
  } else {
    void openFileInNewTab(messageId, parseInt(fileIndex, 10), fileName || 'file', fileType || '');
  }
}

function downloadDocument(el: HTMLElement): void {
  const { messageId, fileIndex, fileName } = el.dataset;
  if (messageId && fileIndex) {
    void downloadFile(messageId, parseInt(fileIndex, 10), fileName || `file-${fileIndex}`);
  }
}

/** Message actions overflow toggle (touch devices). */
function toggleMessageActionsOverflow(overflowBtn: HTMLElement): void {
  const actionsEl = overflowBtn.closest('.message-actions');
  if (actionsEl) {
    const expanded = actionsEl.classList.toggle('expanded');
    overflowBtn.setAttribute('aria-expanded', String(expanded));
  }
}

/** Clicks in the messages list: documents, copy buttons, actions overflow, quizzes. */
const MESSAGE_ACTIONS: readonly ClickAction[] = [
  { selector: '.document-preview', run: openDocumentPreview },
  { selector: '.document-download', run: downloadDocument },
  { selector: '.message-copy-btn', run: (el) => void copyMessageContent(el as HTMLButtonElement) },
  { selector: '.message-actions-overflow', run: toggleMessageActionsOverflow },
  // Inline copy button (code blocks, tables)
  { selector: '.inline-copy-btn', run: (el) => void copyInlineContent(el as HTMLButtonElement) },
  // Quiz option click (multiple-choice)
  { selector: '.quiz-option', run: (el) => handleQuizOptionClick(el as HTMLButtonElement) },
  // Quiz continue / send answers click
  { selector: '.quiz-continue', run: (el) => handleQuizContinue(el as HTMLButtonElement) },
];

export function setupEventListeners(): void {
  // New chat button
  getElementById('new-chat-btn')?.addEventListener('click', createConversation);

  // Mobile menu button
  getElementById('menu-btn')?.addEventListener('click', toggleSidebar);

  // User footer: menu toggle + menu item actions
  getElementById('user-info')?.addEventListener('click', (e) => {
    void handleUserInfoClick(e).catch((error: unknown) => log.error('User menu action failed', { error }));
  });

  // Close the user menu on outside clicks
  document.addEventListener('click', (e) => {
    const menu = document.querySelector('.user-menu');
    if (!menu || menu.classList.contains('hidden')) return;
    if (!(e.target as HTMLElement).closest('#user-info')) {
      closeUserMenu();
    }
  });

  getElementById('conversations-list')?.addEventListener('keydown', handleConversationListKeydown);

  // Conversation list clicks
  getElementById('conversations-list')?.addEventListener('click', (e) => {
    runClickAction(CONVERSATION_LIST_ACTIONS, e);
  });

  // Document preview (open in new tab), download buttons, and message copy buttons
  getElementById('messages')?.addEventListener('click', (e) => {
    runClickAction(MESSAGE_ACTIONS, e);
  });

  // Quiz text inputs gate the Send button on having an answer
  getElementById('messages')?.addEventListener('input', (e) => {
    const quizInput = (e.target as HTMLElement).closest('.quiz-text-input');
    if (quizInput) {
      handleQuizInputChange(quizInput as HTMLInputElement);
    }
  });
}
