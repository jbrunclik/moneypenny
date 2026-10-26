/**
 * Trash view: the sidebar full-view listing deleted conversations (like the
 * archive view), plus the user-menu entry badge.
 *
 * Rows carry data-trash-id rather than data-conv-id, so the sidebar's row
 * click handler never opens a trashed conversation - restore it first.
 */

import { createElement } from '../utils/dom';
import { CHEVRON_RIGHT_ICON, DELETE_ICON, RESTORE_ICON, createIconButton, createIconElement } from '../utils/icons';
import { useStore } from '../state/store';
import { DEFAULT_CONVERSATION_TITLE } from '../types/api';
import type { Conversation } from '../types/api';
import { conversations as conversationsApi } from '../api/conversations';
import { createLogger } from '../utils/logger';
import { MS_PER_DAY } from '../constants';
import { INFINITE_SCROLL_DEBOUNCE_MS, LOAD_MORE_THRESHOLD_PX, TRASH_RETENTION_DAYS } from '../config';

const log = createLogger('sidebar');

let trashScrollListenerCleanup: (() => void) | null = null;

/**
 * "N days left" until the server purges a trashed conversation.
 */
export function daysLeftLabel(purgeAt: string | null | undefined, now: Date = new Date()): string {
  if (!purgeAt) return '';
  const days = Math.ceil((new Date(purgeAt).getTime() - now.getTime()) / MS_PER_DAY);
  if (days <= 0) return 'Deleting soon';
  return days === 1 ? '1 day left' : `${days} days left`;
}

/**
 * Show the user-menu Trash entry with its count; hidden when the trash is empty.
 */
export function renderTrashEntry(): void {
  const trashItem = document.querySelector<HTMLButtonElement>('.user-menu-trash');
  if (!trashItem) return;

  const { trashedConversations, trashPagination } = useStore.getState();
  const total = trashPagination.totalCount || trashedConversations.length;
  trashItem.classList.toggle('hidden', total === 0);
  const badge = trashItem.querySelector('.trash-count');
  if (badge) badge.textContent = String(total);
}

function trashedConversationItem(conv: Conversation): HTMLElement {
  const id = conv.id;
  return createElement('div', { class: 'conversation-item-wrapper', 'data-trash-id': id }, [
    createElement('div', { class: 'conversation-item trash-item', tabindex: '-1' }, [
      createElement('div', { class: 'conversation-text' }, [
        createElement('div', { class: 'conversation-title' }, [conv.title || DEFAULT_CONVERSATION_TITLE]),
      ]),
      createElement('span', { class: 'conversation-time trash-days-left' }, [daysLeftLabel(conv.purge_at)]),
      createElement('div', { class: 'conversation-actions' }, [
        createIconButton({ class: 'conversation-unarchive', 'data-restore-id': id, 'aria-label': 'Restore' }, RESTORE_ICON),
        createIconButton(
          { class: 'conversation-delete', 'data-delete-forever-id': id, 'aria-label': 'Delete forever' },
          DELETE_ICON
        ),
      ]),
    ]),
    createElement('div', { class: 'conversation-actions-swipe' }, [
      createIconButton(
        { class: 'conversation-delete-swipe', 'data-delete-forever-id': id, 'aria-label': 'Delete forever' },
        DELETE_ICON
      ),
      createIconButton({ class: 'conversation-unarchive-swipe', 'data-restore-id': id, 'aria-label': 'Restore' }, RESTORE_ICON),
    ]),
  ]);
}

function trashHeader(totalCount: number, hasItems: boolean): HTMLElement {
  const emptying = useStore.getState().isEmptyingTrash;
  const emptyBtn =
    hasItems &&
    createElement('button', { class: 'trash-empty-btn', 'data-empty-trash': '' }, [emptying ? 'Emptying…' : 'Empty']);
  if (emptyBtn) emptyBtn.disabled = emptying;
  return createElement('div', { class: 'archive-view-header trash-view-header' }, [
    createElement('button', { class: 'archive-back-btn', 'data-trash-back': '', 'aria-label': 'Back to conversations' }, [
      createIconElement('archive-back-icon', CHEVRON_RIGHT_ICON),
    ]),
    createElement('span', { class: 'archive-view-title' }, ['Trash']),
    createElement('span', { class: 'archive-count' }, [String(totalCount)]),
    emptyBtn,
  ]);
}

/** Three bouncing dots under the list while more rows can load. */
function loadMoreDots(loading: boolean): HTMLElement {
  return createElement('div', { class: `archive-load-more ${loading ? 'loading' : ''}` }, [
    createElement('div', { class: 'loading-dots' }, [createElement('span'), createElement('span'), createElement('span')]),
  ]);
}

/**
 * Render the full trash view (replaces the conversation list content).
 * `renderList` re-renders the sidebar list (Sidebar passes its own).
 */
export function renderTrashView(container: HTMLDivElement, renderList: () => void): void {
  renderTrashEntry();
  const { trashedConversations, trashPagination } = useStore.getState();
  const header = trashHeader(trashPagination.totalCount, trashedConversations.length > 0);

  if (trashedConversations.length === 0 && trashPagination.isLoadingMore) {
    container.replaceChildren(
      header,
      createElement('div', { class: 'conversations-loading' }, [createElement('div', { class: 'loading-spinner' })])
    );
    return;
  }

  if (trashedConversations.length === 0) {
    container.replaceChildren(
      header,
      createElement('div', { class: 'conversations-empty' }, [
        createElement('p', {}, ['Trash is empty']),
        createElement('p', { class: 'trash-empty-hint' }, [
          `Deleted conversations stay here for ${TRASH_RETENTION_DAYS} days.`,
        ]),
      ])
    );
    return;
  }

  container.replaceChildren(
    header,
    ...trashedConversations.map(trashedConversationItem),
    ...(trashPagination.hasMore ? [loadMoreDots(trashPagination.isLoadingMore)] : [])
  );
  setupTrashInfiniteScroll(container, renderList);
}

function setupTrashInfiniteScroll(container: HTMLDivElement, renderList: () => void): void {
  if (trashScrollListenerCleanup) return;

  let debounceTimeout: ReturnType<typeof setTimeout> | null = null;

  const handleScroll = () => {
    if (debounceTimeout) clearTimeout(debounceTimeout);
    debounceTimeout = setTimeout(() => {
      const { trashPagination } = useStore.getState();
      if (trashPagination.isLoadingMore || !trashPagination.hasMore) return;
      const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
      if (distanceFromBottom < LOAD_MORE_THRESHOLD_PX) {
        void loadMoreTrashedConversations(renderList);
      }
    }, INFINITE_SCROLL_DEBOUNCE_MS);
  };

  container.addEventListener('scroll', handleScroll);
  trashScrollListenerCleanup = () => {
    container.removeEventListener('scroll', handleScroll);
    if (debounceTimeout) clearTimeout(debounceTimeout);
  };
}

/**
 * Remove the trash view's infinite scroll listener (on leaving the view).
 */
export function cleanupTrashInfiniteScroll(): void {
  if (trashScrollListenerCleanup) {
    trashScrollListenerCleanup();
    trashScrollListenerCleanup = null;
  }
}

async function loadMoreTrashedConversations(renderList: () => void): Promise<void> {
  const store = useStore.getState();
  const { trashPagination } = store;
  if (!trashPagination.hasMore || trashPagination.isLoadingMore) return;

  store.setLoadingMoreTrash(true);
  renderList();
  try {
    const result = await conversationsApi.listTrash(undefined, trashPagination.nextCursor ?? undefined);
    store.appendTrashedConversations(result.conversations, result.pagination);
  } catch (error) {
    log.error('Failed to load more trashed conversations', { error });
  } finally {
    store.setLoadingMoreTrash(false);
    renderList();
  }
}
