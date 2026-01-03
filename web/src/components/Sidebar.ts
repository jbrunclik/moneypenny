import { escapeHtml, getElementById, clearElement } from '../utils/dom';
import { renderUserAvatarHtml } from '../utils/avatar';
import { BRAIN_ICON, DELETE_ICON, EDIT_ICON, LOGOUT_ICON, SETTINGS_ICON } from '../utils/icons';
import { useStore } from '../state/store';
import { DEFAULT_CONVERSATION_TITLE } from '../types/api';
import type { Conversation } from '../types/api';
import { costs, conversations as conversationsApi } from '../api/client';
import { createLogger } from '../utils/logger';
import {
  LOAD_MORE_THRESHOLD_PX,
  INFINITE_SCROLL_DEBOUNCE_MS,
  CONVERSATION_ITEM_HEIGHT_PX,
  CONVERSATIONS_MIN_PAGE_SIZE,
  VIEWPORT_BUFFER_MULTIPLIER,
} from '../config';

const log = createLogger('sidebar');

// Track if infinite scroll listener is set up
let scrollListenerCleanup: (() => void) | null = null;

/**
 * Calculate optimal page size based on container height
 */
function calculatePageSize(containerHeight: number): number {
  const itemsNeeded = Math.ceil(containerHeight / CONVERSATION_ITEM_HEIGHT_PX);
  const withBuffer = Math.ceil(itemsNeeded * VIEWPORT_BUFFER_MULTIPLIER);
  return Math.max(CONVERSATIONS_MIN_PAGE_SIZE, withBuffer);
}

/**
 * Render the conversations list in the sidebar
 */
export function renderConversationsList(): void {
  const container = getElementById<HTMLDivElement>('conversations-list');
  if (!container) return;

  const { conversations, currentConversation, isLoading, conversationsPagination } = useStore.getState();

  if (isLoading && conversations.length === 0) {
    container.innerHTML = `
      <div class="conversations-loading">
        <div class="loading-spinner"></div>
      </div>
    `;
    return;
  }

  if (conversations.length === 0) {
    container.innerHTML = `
      <div class="conversations-empty">
        <p>No conversations yet</p>
        <p class="text-muted">Start a new chat to begin</p>
      </div>
    `;
    return;
  }

  // Render conversations
  const conversationsHtml = conversations
    .map((conv) => renderConversationItem(conv, conv.id === currentConversation?.id))
    .join('');

  // Render loading indicator for "load more" if there are more pages
  const loadMoreHtml = conversationsPagination.hasMore
    ? `<div class="conversations-load-more ${conversationsPagination.isLoadingMore ? 'loading' : ''}">
        <div class="loading-dots">
          <span></span>
          <span></span>
          <span></span>
        </div>
      </div>`
    : '';

  container.innerHTML = conversationsHtml + loadMoreHtml;

  // Set up infinite scroll if not already set up
  setupInfiniteScroll(container);
}

/**
 * Render a single conversation item
 */
function renderConversationItem(conv: Conversation, isActive: boolean): string {
  const title = escapeHtml(conv.title || DEFAULT_CONVERSATION_TITLE);

  // Render unread badge if there are unread messages
  const unreadBadge = conv.unreadCount && conv.unreadCount > 0
    ? `<span class="unread-badge">${conv.unreadCount > 99 ? '99+' : conv.unreadCount}</span>`
    : '';

  return `
    <div class="conversation-item-wrapper ${isActive ? 'active' : ''}" data-conv-id="${conv.id}">
      <div class="conversation-item">
        <div class="conversation-title">${title}</div>
        ${unreadBadge}
        <div class="conversation-actions">
          <button class="conversation-rename" data-rename-id="${conv.id}" aria-label="Rename">
            ${EDIT_ICON}
          </button>
          <button class="conversation-delete" data-delete-id="${conv.id}" aria-label="Delete">
            ${DELETE_ICON}
          </button>
        </div>
      </div>
      <div class="conversation-actions-swipe">
        <button class="conversation-rename-swipe" data-rename-id="${conv.id}" aria-label="Rename">
          ${EDIT_ICON}
        </button>
        <button class="conversation-delete-swipe" data-delete-id="${conv.id}" aria-label="Delete">
          ${DELETE_ICON}
        </button>
      </div>
    </div>
  `;
}

/**
 * Render user info in sidebar footer
 */
export function renderUserInfo(): void {
  const container = getElementById<HTMLDivElement>('user-info');
  if (!container) return;

  const { user } = useStore.getState();

  if (!user) {
    clearElement(container);
    return;
  }

  const name = user.name || user.email;
  const avatarHtml = renderUserAvatarHtml(user.picture || undefined, name);

  container.innerHTML = `
    <div class="user-profile">
      ${avatarHtml}
      <span class="user-name">${escapeHtml(name)}</span>
    </div>
    <div class="user-actions">
      <button id="monthly-cost" class="btn-monthly-cost" title="Click to view cost history">
        <span class="cost-label">This month:</span>
        <span class="cost-value">—</span>
      </button>
      <div class="user-actions-buttons">
        <button id="settings-btn" class="btn-icon-action" title="Settings">
          ${SETTINGS_ICON}
        </button>
        <button id="memories-btn" class="btn-icon-action" title="View memories">
          ${BRAIN_ICON}
        </button>
        <button id="logout-btn" class="btn-icon-action" title="Logout">
          ${LOGOUT_ICON}
        </button>
      </div>
    </div>
  `;

  // Fetch monthly cost after rendering
  const now = new Date();
  costs.getMonthlyCost(now.getFullYear(), now.getMonth() + 1)
    .then(monthlyCost => {
      const costValueEl = container.querySelector('.cost-value');
      if (costValueEl) {
        costValueEl.textContent = monthlyCost.formatted;
      }
      const costBtn = container.querySelector('#monthly-cost');
      if (costBtn) {
        costBtn.setAttribute('title', `Click to view cost history`);
      }
    })
    .catch((error) => {
      // Ignore errors - cost display is optional, but log for debugging
      log.warn('Failed to fetch monthly cost', { error });
    });
}

/**
 * Update the monthly cost display in the sidebar
 */
export async function updateMonthlyCost(): Promise<void> {
  const costValueEl = document.querySelector('#user-info .cost-value');
  if (!costValueEl) return;

  try {
    const now = new Date();
    const monthlyCost = await costs.getMonthlyCost(now.getFullYear(), now.getMonth() + 1);
    costValueEl.textContent = monthlyCost.formatted;
  } catch {
    // Ignore errors - cost display is optional
  }
}

/**
 * Update conversation title in sidebar
 */
export function updateConversationTitle(convId: string, title: string): void {
  const wrapper = document.querySelector<HTMLDivElement>(
    `.conversation-item-wrapper[data-conv-id="${convId}"]`
  );
  if (wrapper) {
    const titleEl = wrapper.querySelector<HTMLDivElement>('.conversation-title');
    if (titleEl) {
      titleEl.textContent = title;
    }
  }
}

/**
 * Set active conversation in sidebar
 */
export function setActiveConversation(convId: string | null): void {
  // Remove active from all
  document
    .querySelectorAll<HTMLDivElement>('.conversation-item-wrapper.active')
    .forEach((el) => el.classList.remove('active'));

  // Add active to current
  if (convId) {
    const wrapper = document.querySelector<HTMLDivElement>(
      `.conversation-item-wrapper[data-conv-id="${convId}"]`
    );
    wrapper?.classList.add('active');
  }
}

/**
 * Toggle sidebar visibility (mobile)
 */
export function toggleSidebar(): void {
  useStore.getState().toggleSidebar();
  updateSidebarVisibility();
}

/**
 * Close sidebar (mobile)
 */
export function closeSidebar(): void {
  useStore.getState().closeSidebar();
  updateSidebarVisibility();
}

/**
 * Update sidebar visibility based on state
 */
function updateSidebarVisibility(): void {
  const sidebar = getElementById<HTMLElement>('sidebar');
  const app = getElementById<HTMLDivElement>('app');
  if (!sidebar || !app) return;

  const { isSidebarOpen } = useStore.getState();

  if (isSidebarOpen) {
    sidebar.classList.add('open');
    // Create overlay for mobile
    let overlay = app.querySelector<HTMLDivElement>('.sidebar-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.className = 'sidebar-overlay';
      overlay.addEventListener('click', closeSidebar);
      app.appendChild(overlay);
    }
    overlay.classList.add('visible');
  } else {
    sidebar.classList.remove('open');
    const overlay = app.querySelector<HTMLDivElement>('.sidebar-overlay');
    overlay?.classList.remove('visible');
  }
}

/**
 * Set up infinite scroll for the conversations list.
 * When user scrolls near the bottom and there are more pages, load more conversations.
 */
function setupInfiniteScroll(container: HTMLDivElement): void {
  // If listener already set up, don't add another
  if (scrollListenerCleanup) return;

  let debounceTimeout: ReturnType<typeof setTimeout> | null = null;

  const handleScroll = () => {
    // Debounce the scroll handler
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }

    debounceTimeout = setTimeout(() => {
      const { conversationsPagination } = useStore.getState();

      // Don't load more if already loading or no more pages
      if (conversationsPagination.isLoadingMore || !conversationsPagination.hasMore) {
        return;
      }

      // Check if user is near the bottom
      const scrollTop = container.scrollTop;
      const scrollHeight = container.scrollHeight;
      const clientHeight = container.clientHeight;
      const distanceFromBottom = scrollHeight - scrollTop - clientHeight;

      if (distanceFromBottom < LOAD_MORE_THRESHOLD_PX) {
        loadMoreConversations(container);
      }
    }, INFINITE_SCROLL_DEBOUNCE_MS);
  };

  container.addEventListener('scroll', handleScroll);

  // Store cleanup function
  scrollListenerCleanup = () => {
    container.removeEventListener('scroll', handleScroll);
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }
  };

  log.debug('Infinite scroll set up');
}

/**
 * Clean up infinite scroll listener.
 * Should be called when navigating away or when store is reset.
 */
export function cleanupInfiniteScroll(): void {
  if (scrollListenerCleanup) {
    scrollListenerCleanup();
    scrollListenerCleanup = null;
    log.debug('Infinite scroll cleaned up');
  }
}

/**
 * Load more conversations from the API.
 */
async function loadMoreConversations(container: HTMLDivElement): Promise<void> {
  const store = useStore.getState();
  const { conversationsPagination } = store;

  if (!conversationsPagination.hasMore || conversationsPagination.isLoadingMore) {
    return;
  }

  log.debug('Loading more conversations', { cursor: conversationsPagination.nextCursor });

  // Set loading state
  store.setLoadingMoreConversations(true);
  // Re-render to show loading indicator
  renderConversationsList();

  try {
    // Calculate page size based on container height
    const pageSize = calculatePageSize(container.clientHeight);

    const result = await conversationsApi.list(pageSize, conversationsPagination.nextCursor);

    // Append conversations to the store
    store.appendConversations(result.conversations, result.pagination);

    log.info('Loaded more conversations', {
      count: result.conversations.length,
      hasMore: result.pagination.has_more,
    });
  } catch (error) {
    log.error('Failed to load more conversations', { error });
  } finally {
    // Reset loading state and re-render
    store.setLoadingMoreConversations(false);
    renderConversationsList();
  }
}