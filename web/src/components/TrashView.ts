/**
 * Trash view: the sidebar full-view listing deleted conversations (like the
 * archive view), plus the user-menu entry badge.
 *
 * Rows carry data-trash-id rather than data-conv-id, so the sidebar's row
 * click handler never opens a trashed conversation - restore it first.
 */

import { escapeHtml } from '../utils/dom';
import { CHEVRON_RIGHT_ICON, DELETE_ICON, RESTORE_ICON } from '../utils/icons';
import { useStore } from '../state/store';
import { DEFAULT_CONVERSATION_TITLE } from '../types/api';
import type { Conversation } from '../types/api';
import { conversations as conversationsApi } from '../api/conversations';
import { createLogger } from '../utils/logger';
import { MS_PER_DAY } from '../constants';
import { INFINITE_SCROLL_DEBOUNCE_MS, LOAD_MORE_THRESHOLD_PX, TRASH_RETENTION_DAYS } from '../config';
import { renderConversationsList } from './Sidebar';

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

function renderTrashedConversationItem(conv: Conversation): string {
  const title = escapeHtml(conv.title || DEFAULT_CONVERSATION_TITLE);
  const daysLeft = escapeHtml(daysLeftLabel(conv.purge_at));
  const id = escapeHtml(conv.id);

  return `
    <div class="conversation-item-wrapper" data-trash-id="${id}">
      <div class="conversation-item trash-item" tabindex="-1">
        <div class="conversation-text">
          <div class="conversation-title">${title}</div>
        </div>
        <span class="conversation-time trash-days-left">${daysLeft}</span>
        <div class="conversation-actions">
          <button class="conversation-unarchive" data-restore-id="${id}" aria-label="Restore">
            ${RESTORE_ICON}
          </button>
          <button class="conversation-delete" data-delete-forever-id="${id}" aria-label="Delete forever">
            ${DELETE_ICON}
          </button>
        </div>
      </div>
      <div class="conversation-actions-swipe">
        <button class="conversation-delete-swipe" data-delete-forever-id="${id}" aria-label="Delete forever">
          ${DELETE_ICON}
        </button>
        <button class="conversation-unarchive-swipe" data-restore-id="${id}" aria-label="Restore">
          ${RESTORE_ICON}
        </button>
      </div>
    </div>
  `;
}

function renderTrashHeader(totalCount: number, hasItems: boolean): string {
  const emptyBtn = hasItems
    ? '<button class="trash-empty-btn" data-empty-trash>Empty</button>'
    : '';
  return `
    <div class="archive-view-header trash-view-header">
      <button class="archive-back-btn" data-trash-back aria-label="Back to conversations">
        <span class="archive-back-icon">${CHEVRON_RIGHT_ICON}</span>
      </button>
      <span class="archive-view-title">Trash</span>
      <span class="archive-count">${totalCount}</span>
      ${emptyBtn}
    </div>
  `;
}

/**
 * Render the full trash view (replaces the conversation list content).
 */
export function renderTrashView(container: HTMLDivElement): void {
  renderTrashEntry();
  const { trashedConversations, trashPagination } = useStore.getState();
  const headerHtml = renderTrashHeader(trashPagination.totalCount, trashedConversations.length > 0);

  if (trashedConversations.length === 0 && trashPagination.isLoadingMore) {
    container.innerHTML = headerHtml + `
      <div class="conversations-loading">
        <div class="loading-spinner"></div>
      </div>
    `;
    return;
  }

  if (trashedConversations.length === 0) {
    container.innerHTML = headerHtml + `
      <div class="conversations-empty">
        <p>Trash is empty</p>
        <p class="trash-empty-hint">Deleted conversations stay here for ${TRASH_RETENTION_DAYS} days.</p>
      </div>
    `;
    return;
  }

  const itemsHtml = trashedConversations.map(renderTrashedConversationItem).join('');
  const loadMoreHtml = trashPagination.hasMore
    ? `<div class="archive-load-more ${trashPagination.isLoadingMore ? 'loading' : ''}">
        <div class="loading-dots">
          <span></span>
          <span></span>
          <span></span>
        </div>
      </div>`
    : '';

  container.innerHTML = headerHtml + itemsHtml + loadMoreHtml;
  setupTrashInfiniteScroll(container);
}

function setupTrashInfiniteScroll(container: HTMLDivElement): void {
  if (trashScrollListenerCleanup) return;

  let debounceTimeout: ReturnType<typeof setTimeout> | null = null;

  const handleScroll = () => {
    if (debounceTimeout) clearTimeout(debounceTimeout);
    debounceTimeout = setTimeout(() => {
      const { trashPagination } = useStore.getState();
      if (trashPagination.isLoadingMore || !trashPagination.hasMore) return;
      const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
      if (distanceFromBottom < LOAD_MORE_THRESHOLD_PX) {
        void loadMoreTrashedConversations();
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

async function loadMoreTrashedConversations(): Promise<void> {
  const store = useStore.getState();
  const { trashPagination } = store;
  if (!trashPagination.hasMore || trashPagination.isLoadingMore) return;

  store.setLoadingMoreTrash(true);
  renderConversationsList();
  try {
    const result = await conversationsApi.listTrash(undefined, trashPagination.nextCursor ?? undefined);
    store.appendTrashedConversations(result.conversations, result.pagination);
  } catch (error) {
    log.error('Failed to load more trashed conversations', { error });
  } finally {
    store.setLoadingMoreTrash(false);
    renderConversationsList();
  }
}
