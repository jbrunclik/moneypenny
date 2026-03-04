import { escapeHtml, getElementById, clearElement } from '../utils/dom';
import { renderUserAvatarHtml } from '../utils/avatar';
import { ARCHIVE_ICON, CHEVRON_RIGHT_ICON, DATABASE_ICON, DELETE_ICON, EDIT_ICON, LOGOUT_ICON, PLANNER_ICON, ROBOT_ICON, SETTINGS_ICON, UNARCHIVE_ICON } from '../utils/icons';
import { useStore } from '../state/store';
import { DEFAULT_CONVERSATION_TITLE } from '../types/api';
import type { Conversation, User } from '../types/api';
import { costs, conversations as conversationsApi } from '../api/client';
import { createLogger } from '../utils/logger';
import { getSyncManager } from '../sync/SyncManager';
import { isSearchResultsVisible, renderSearchResults } from './SearchResults';
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

// Track if archive infinite scroll listener is set up
let archiveScrollListenerCleanup: (() => void) | null = null;

/**
 * Check if the planner entry should be shown.
 * Only visible when user has Todoist or Google Calendar connected.
 */
export function shouldShowPlanner(user: User | null): boolean {
  if (!user) return false;
  // Check if user has either integration connected
  // These fields are set after fetching integration status in loadInitialData
  return !!(user.todoist_connected || user.calendar_connected);
}

/**
 * Check if the agents entry should be shown.
 * Always visible when user is logged in (agents are a core feature).
 */
export function shouldShowAgents(user: User | null): boolean {
  return !!user;
}

/**
 * Render the planner entry at the top of the conversations list.
 * Note: No divider after planner because agents entry follows it.
 */
function renderPlannerEntry(isActive: boolean): string {
  return `
    <div class="planner-entry ${isActive ? 'active' : ''}" data-route="planner">
      <span class="planner-icon">${PLANNER_ICON}</span>
      <span class="planner-label">Planner</span>
    </div>
  `;
}

/**
 * Render the agents entry in the sidebar (without divider, for use in nav row).
 * Shows three types of indicators:
 * - Purple unread badge: number of unread assistant messages
 * - Amber waiting badge: number of agents waiting for approval
 * - Red error dot: agents with failed last execution
 */
function renderAgentsEntryWithoutDivider(
  isActive: boolean,
  unreadCount: number,
  waitingCount: number,
  errorsCount: number
): string {
  const unreadTooltip = unreadCount === 1 ? '1 unread message' : `${unreadCount} unread messages`;
  const badge = unreadCount > 0 ? `<span class="unread-badge" title="${unreadTooltip}">${unreadCount > 99 ? '99+' : unreadCount}</span>` : '';
  const waitingTooltip = waitingCount === 1 ? '1 agent waiting for approval' : `${waitingCount} agents waiting for approval`;
  const waitingBadge = waitingCount > 0 ? `<span class="waiting-badge" title="${waitingTooltip}">${waitingCount > 99 ? '99+' : waitingCount}</span>` : '';
  const errorTooltip = errorsCount === 1 ? '1 agent failed' : `${errorsCount} agents failed`;
  const errorIndicator = errorsCount > 0 ? `<span class="error-indicator" title="${errorTooltip}"></span>` : '';
  return `
    <div class="agents-entry ${isActive ? 'active' : ''}" data-route="agents">
      <span class="agents-icon">${ROBOT_ICON}</span>
      <span class="agents-label">Agents</span>
      ${errorIndicator}${waitingBadge}${badge}
    </div>
  `;
}

/**
 * Calculate optimal page size based on container height
 */
function calculatePageSize(containerHeight: number): number {
  const itemsNeeded = Math.ceil(containerHeight / CONVERSATION_ITEM_HEIGHT_PX);
  const withBuffer = Math.ceil(itemsNeeded * VIEWPORT_BUFFER_MULTIPLIER);
  return Math.max(CONVERSATIONS_MIN_PAGE_SIZE, withBuffer);
}

/**
 * Check if the archive view is currently visible.
 */
function isArchiveViewVisible(): boolean {
  return useStore.getState().isArchiveView;
}

/**
 * Render the conversations list in the sidebar
 * If search is active, renders search results instead
 * If archive view is active, renders archive view instead
 */
export function renderConversationsList(): void {
  const container = getElementById<HTMLDivElement>('conversations-list');
  if (!container) return;

  // If search is active, render search results instead
  if (isSearchResultsVisible()) {
    renderSearchResults();
    return;
  }

  // If archive view is active, render archive view instead
  if (isArchiveViewVisible()) {
    renderArchiveView(container);
    return;
  }

  const { conversations, currentConversation, isLoading, conversationsPagination, user, isPlannerView, isAgentsView, commandCenterData } = useStore.getState();

  // Build navigation entries row (planner + agents side by side)
  const showPlanner = shouldShowPlanner(user);
  const showAgents = shouldShowAgents(user);
  const agentUnreadCount = commandCenterData?.total_unread ?? 0;
  const agentWaitingCount = commandCenterData?.agents_waiting ?? 0;
  const agentErrorsCount = commandCenterData?.agents_with_errors ?? 0;

  let navEntriesHtml = '';
  if (showPlanner || showAgents) {
    const plannerHtml = showPlanner ? renderPlannerEntry(isPlannerView) : '';
    const agentsHtml = showAgents ? renderAgentsEntryWithoutDivider(isAgentsView, agentUnreadCount, agentWaitingCount, agentErrorsCount) : '';
    // Use 'single' class when only one entry is shown
    const rowClass = (showPlanner && showAgents) ? '' : ' single';
    navEntriesHtml = `
      <div class="sidebar-nav-row${rowClass}">
        ${plannerHtml}${agentsHtml}
      </div>
      <div class="sidebar-divider"></div>
    `;
  }

  if (isLoading && conversations.length === 0) {
    container.innerHTML = navEntriesHtml + `
      <div class="conversations-loading">
        <div class="loading-spinner"></div>
      </div>
    `;
    return;
  }

  if (conversations.length === 0) {
    container.innerHTML = navEntriesHtml + `
      <div class="conversations-empty">
        <p>No conversations yet</p>
        <p class="text-muted">Start a new chat to begin</p>
      </div>
    `;
    return;
  }

  // Render conversations
  const conversationsHtml = conversations
    .map((conv) => renderConversationItem(conv, conv.id === currentConversation?.id && !isPlannerView && !isAgentsView))
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

  container.innerHTML = navEntriesHtml + conversationsHtml + loadMoreHtml;

  // Render archive entry in its own pinned container (always visible, not scrolled)
  renderArchiveEntry();

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
          <button class="conversation-archive" data-archive-id="${conv.id}" aria-label="Archive">
            ${ARCHIVE_ICON}
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
        <button class="conversation-archive-swipe" data-archive-id="${conv.id}" aria-label="Archive">
          ${ARCHIVE_ICON}
        </button>
        <button class="conversation-delete-swipe" data-delete-id="${conv.id}" aria-label="Delete">
          ${DELETE_ICON}
        </button>
      </div>
    </div>
  `;
}

/**
 * Render a single archived conversation item (with rename + unarchive + delete actions)
 */
function renderArchivedConversationItem(conv: Conversation): string {
  const title = escapeHtml(conv.title || DEFAULT_CONVERSATION_TITLE);

  return `
    <div class="conversation-item-wrapper" data-conv-id="${conv.id}">
      <div class="conversation-item">
        <div class="conversation-title">${title}</div>
        <div class="conversation-actions">
          <button class="conversation-rename" data-rename-id="${conv.id}" aria-label="Rename">
            ${EDIT_ICON}
          </button>
          <button class="conversation-unarchive" data-unarchive-id="${conv.id}" aria-label="Unarchive">
            ${UNARCHIVE_ICON}
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
        <button class="conversation-unarchive-swipe" data-unarchive-id="${conv.id}" aria-label="Unarchive">
          ${UNARCHIVE_ICON}
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
      <div class="user-actions-buttons">
        <button id="settings-btn" class="btn-icon-action" title="Settings">
          ${SETTINGS_ICON}
        </button>
        <button id="memories-btn" class="btn-icon-action" title="Memories & Storage">
          ${DATABASE_ICON}
        </button>
        <button id="logout-btn" class="btn-icon-action" title="Logout">
          ${LOGOUT_ICON}
        </button>
      </div>
    </div>
    <button id="monthly-cost" class="btn-monthly-cost" title="Click to view cost history">
      <span class="cost-label">This month:</span>
      <span class="cost-value">—</span>
    </button>
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
  // Remove active from all conversations
  document
    .querySelectorAll<HTMLDivElement>('.conversation-item-wrapper.active')
    .forEach((el) => el.classList.remove('active'));

  // Remove active from planner entry
  document
    .querySelectorAll<HTMLDivElement>('.planner-entry.active')
    .forEach((el) => el.classList.remove('active'));

  // Remove active from agents entry
  document
    .querySelectorAll<HTMLDivElement>('.agents-entry.active')
    .forEach((el) => el.classList.remove('active'));

  // Add active to current conversation
  if (convId) {
    const wrapper = document.querySelector<HTMLDivElement>(
      `.conversation-item-wrapper[data-conv-id="${convId}"]`
    );
    wrapper?.classList.add('active');
  }
}

/**
 * Set planner entry as active in sidebar
 */
export function setPlannerActive(active: boolean): void {
  const plannerEntry = document.querySelector<HTMLDivElement>('.planner-entry');
  if (!plannerEntry) return;

  if (active) {
    // Remove active from all conversations
    document
      .querySelectorAll<HTMLDivElement>('.conversation-item-wrapper.active')
      .forEach((el) => el.classList.remove('active'));
    // Remove active from agents
    document
      .querySelectorAll<HTMLDivElement>('.agents-entry.active')
      .forEach((el) => el.classList.remove('active'));
    // Set planner as active
    plannerEntry.classList.add('active');
  } else {
    plannerEntry.classList.remove('active');
  }
}

/**
 * Set agents entry as active in sidebar
 */
export function setAgentsActive(active: boolean): void {
  const agentsEntry = document.querySelector<HTMLDivElement>('.agents-entry');
  if (!agentsEntry) return;

  if (active) {
    // Remove active from all conversations
    document
      .querySelectorAll<HTMLDivElement>('.conversation-item-wrapper.active')
      .forEach((el) => el.classList.remove('active'));
    // Remove active from planner
    document
      .querySelectorAll<HTMLDivElement>('.planner-entry.active')
      .forEach((el) => el.classList.remove('active'));
    // Set agents as active
    agentsEntry.classList.add('active');
  } else {
    agentsEntry.classList.remove('active');
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
 * Load archived conversations from API and update store.
 */
export async function loadArchivedConversations(): Promise<void> {
  try {
    const result = await conversationsApi.listArchived();
    useStore.getState().setArchivedConversations(result.conversations, result.pagination);
    renderConversationsList();
  } catch (error) {
    log.error('Failed to load archived conversations', { error });
  }
}

/**
 * Render the archive entry in its own pinned container (between conversations and footer).
 * Hidden when archive view is active (the full view replaces conversations-list).
 */
function renderArchiveEntry(): void {
  const entryContainer = getElementById<HTMLDivElement>('archive-entry-container');
  if (!entryContainer) return;

  const { archivedConversations, archivedPagination, isArchiveView } = useStore.getState();

  // Hide when archive view is active or no archived conversations
  if (isArchiveView || (archivedPagination.totalCount === 0 && archivedConversations.length === 0)) {
    clearElement(entryContainer);
    return;
  }

  entryContainer.innerHTML = `
    <div class="archive-entry" data-route="archive">
      <span class="archive-entry-icon">${ARCHIVE_ICON}</span>
      <span class="archive-entry-label">Archive</span>
      <span class="archive-count">${archivedPagination.totalCount}</span>
    </div>
  `;
}

/**
 * Render the full archive view (replaces conversation list content).
 */
function renderArchiveView(container: HTMLDivElement): void {
  // Clear archive entry when showing full archive view
  renderArchiveEntry();
  const { archivedConversations, archivedPagination } = useStore.getState();

  // Header with back button
  const headerHtml = `
    <div class="archive-view-header">
      <button class="archive-back-btn" data-archive-back aria-label="Back to conversations">
        <span class="archive-back-icon">${CHEVRON_RIGHT_ICON}</span>
      </button>
      <span class="archive-view-title">Archive</span>
      <span class="archive-count">${archivedPagination.totalCount}</span>
    </div>
  `;

  // Loading state
  if (archivedConversations.length === 0 && archivedPagination.isLoadingMore) {
    container.innerHTML = headerHtml + `
      <div class="conversations-loading">
        <div class="loading-spinner"></div>
      </div>
    `;
    return;
  }

  // Empty state
  if (archivedConversations.length === 0) {
    container.innerHTML = headerHtml + `
      <div class="conversations-empty">
        <p>No archived conversations</p>
      </div>
    `;
    return;
  }

  // Archived items
  const archivedItemsHtml = archivedConversations
    .map((conv) => renderArchivedConversationItem(conv))
    .join('');

  // Load more indicator
  const loadMoreHtml = archivedPagination.hasMore
    ? `<div class="archive-load-more ${archivedPagination.isLoadingMore ? 'loading' : ''}">
        <div class="loading-dots">
          <span></span>
          <span></span>
          <span></span>
        </div>
      </div>`
    : '';

  container.innerHTML = headerHtml + archivedItemsHtml + loadMoreHtml;

  // Set up infinite scroll for archive
  setupArchiveInfiniteScroll(container);
}

/**
 * Set up infinite scroll for the archive view.
 */
function setupArchiveInfiniteScroll(container: HTMLDivElement): void {
  if (archiveScrollListenerCleanup) return;

  let debounceTimeout: ReturnType<typeof setTimeout> | null = null;

  const handleScroll = () => {
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }

    debounceTimeout = setTimeout(() => {
      const { archivedPagination } = useStore.getState();

      if (archivedPagination.isLoadingMore || !archivedPagination.hasMore) {
        return;
      }

      const scrollTop = container.scrollTop;
      const scrollHeight = container.scrollHeight;
      const clientHeight = container.clientHeight;
      const distanceFromBottom = scrollHeight - scrollTop - clientHeight;

      if (distanceFromBottom < LOAD_MORE_THRESHOLD_PX) {
        loadMoreArchivedConversations();
      }
    }, INFINITE_SCROLL_DEBOUNCE_MS);
  };

  container.addEventListener('scroll', handleScroll);

  archiveScrollListenerCleanup = () => {
    container.removeEventListener('scroll', handleScroll);
    if (debounceTimeout) {
      clearTimeout(debounceTimeout);
    }
  };

  log.debug('Archive infinite scroll set up');
}

/**
 * Clean up archive infinite scroll listener.
 */
export function cleanupArchiveInfiniteScroll(): void {
  if (archiveScrollListenerCleanup) {
    archiveScrollListenerCleanup();
    archiveScrollListenerCleanup = null;
    log.debug('Archive infinite scroll cleaned up');
  }
}

/**
 * Load more archived conversations from API (pagination).
 */
async function loadMoreArchivedConversations(): Promise<void> {
  const store = useStore.getState();
  const { archivedPagination } = store;

  if (!archivedPagination.hasMore || archivedPagination.isLoadingMore) {
    return;
  }

  log.debug('Loading more archived conversations', { cursor: archivedPagination.nextCursor });

  store.setLoadingMoreArchived(true);
  renderConversationsList();

  try {
    const result = await conversationsApi.listArchived(
      undefined,
      archivedPagination.nextCursor ?? undefined
    );

    store.appendArchivedConversations(result.conversations, result.pagination);

    log.info('Loaded more archived conversations', {
      count: result.conversations.length,
      hasMore: result.pagination.has_more,
    });
  } catch (error) {
    log.error('Failed to load more archived conversations', { error });
  } finally {
    store.setLoadingMoreArchived(false);
    renderConversationsList();
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

    // Initialize local message counts for newly paginated conversations
    // This prevents false unread badges when sync runs
    const syncManager = getSyncManager();
    if (syncManager) {
      for (const conv of result.conversations) {
        if (conv.messageCount !== undefined) {
          syncManager.initializeLocalMessageCount(conv.id, conv.messageCount);
        }
      }
    }

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