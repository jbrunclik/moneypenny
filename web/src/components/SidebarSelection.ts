/**
 * Sidebar selection mode for bulk delete: the selection bar and footer,
 * row checkboxes, and select all. Selection state lives in the store
 * (state/slices/selection.ts); Sidebar.ts only asks for each row's checkbox.
 */
import { useStore } from '../state/store';
import { isConversationSelected, selectedCount } from '../state/slices/selection';
import type { Conversation } from '../types/api';
import { CHECK_ICON, DELETE_ICON, setIcon } from '../utils/icons';
import { renderConversationsList } from './Sidebar';
import { clearSearch } from './SearchInput';
import { isSearchResultsVisible } from './SearchResults';

/** The core actions selection mode triggers, passed in at startup (F1). */
export interface SelectionActions {
  bulkDelete: () => Promise<void>;
  leaveTrashView: () => void;
  leaveArchiveView: () => void;
}
let actions: SelectionActions | null = null;

export function enterSelectionMode(): void {
  const store = useStore.getState();
  if (isSearchResultsVisible()) clearSearch();
  // Leave like the back button does: restores the hash and drops the
  // view's infinite-scroll listener
  if (store.isTrashView) actions?.leaveTrashView();
  if (store.isArchiveView) actions?.leaveArchiveView();
  store.startSelection();
  renderSelectionChrome();
  renderConversationsList();
}

export function exitSelectionMode(): void {
  useStore.getState().endSelection();
  renderSelectionChrome();
  renderConversationsList();
}

/** Bar text, footer button, and the #sidebar.selecting class. */
export function renderSelectionChrome(): void {
  const state = useStore.getState();
  document.getElementById('sidebar')?.classList.toggle('selecting', state.isSelecting);
  document.getElementById('selection-bar')?.classList.toggle('hidden', !state.isSelecting);
  document.getElementById('selection-footer')?.classList.toggle('hidden', !state.isSelecting);
  if (!state.isSelecting) return;

  const count = selectedCount(state);
  const countEl = document.querySelector('#selection-bar .selection-count');
  if (countEl) countEl.textContent = `${count} selected`;
  const allBtn = document.getElementById('selection-all');
  if (allBtn) allBtn.textContent = state.selectionMode === 'all' ? 'Deselect all' : 'Select all';
  const trashBtn = document.getElementById('selection-trash') as HTMLButtonElement | null;
  if (trashBtn) {
    trashBtn.disabled = count === 0 || state.isBulkDeleting;
    setIcon(trashBtn, DELETE_ICON);
    trashBtn.append(` ${state.isBulkDeleting ? 'Moving…' : `Move ${count} to trash`}`);
  }
}

/** The row's checkbox in selection mode; '' otherwise. */
export function renderSelectionCheckbox(conv: Conversation): string {
  const state = useStore.getState();
  if (!state.isSelecting) return '';
  const checked = isConversationSelected(state, conv);
  return `<span class="conversation-select" role="checkbox" aria-checked="${checked}" aria-label="Select">${checked ? CHECK_ICON : ''}</span>`;
}

function refresh(): void {
  renderSelectionChrome();
  renderConversationsList();
}

/** Sidebar clicks while selecting; returns true when it handled the click. */
export function handleSelectionListClick(e: MouseEvent): boolean {
  const state = useStore.getState();
  if (!state.isSelecting) return false;
  const target = e.target as HTMLElement;

  if (target.closest('#selection-cancel')) {
    exitSelectionMode();
    return true;
  }
  if (target.closest('#selection-all')) {
    if (state.selectionMode === 'all') state.deselectAll();
    else state.selectAll(new Date().toISOString());
    refresh();
    return true;
  }
  if (target.closest('#selection-trash')) {
    void actions?.bulkDelete();
    return true;
  }
  const wrapper = target.closest<HTMLElement>('#conversations-list [data-conv-id]');
  const conv = wrapper && state.conversations.find((c) => c.id === wrapper.dataset.convId);
  if (conv) {
    state.toggleSelected(conv);
    refresh();
    return true;
  }
  return target.closest('#conversations-list') !== null;
}

let initialized = false;

/** Wire the sidebar click and Escape listeners (once). */
export function initSidebarSelection(selectionActions: SelectionActions): void {
  actions = selectionActions;
  if (initialized) return;
  initialized = true;
  // Capture phase: runs before the list's own row-open / action handlers
  document.getElementById('sidebar')?.addEventListener(
    'click',
    (e) => {
      if (handleSelectionListClick(e)) {
        e.preventDefault();
        e.stopPropagation();
      }
    },
    true
  );
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && useStore.getState().isSelecting) exitSelectionMode();
  });
}
