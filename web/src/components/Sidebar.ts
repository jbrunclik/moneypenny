import { escapeHtml, getElementById, clearElement } from '../utils/dom';
import { formatRelativeTime, groupForDate } from '../utils/relative-time';
import { renderUserAvatarHtml } from '../utils/avatar';
import { ARCHIVE_ICON, CHEVRON_RIGHT_ICON, COST_ICON, DATABASE_ICON, DELETE_ICON, EDIT_ICON, LANGUAGE_ICON, LOGOUT_ICON, PLANNER_ICON, ROBOT_ICON, SETTINGS_ICON, SPORTS_ICON, UNARCHIVE_ICON } from '../utils/icons';
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
 * Check if the sports entry should be shown.
 * Always visible when user is logged in.
 */
export function shouldShowSports(user: User | null): boolean {
  return !!user;
}

/**
 * Check if the language entry should be shown.
 * Always visible when user is logged in.
 */
export function shouldShowLanguage(user: User | null): boolean {
  return !!user;
}

/**
 * Render the planner entry at the top of the conversations list.
 * Note: No divider after planner because agents entry follows it.
 */
function renderPlannerEntry(isActive: boolean): string {
  return `
    <div class="planner-entry ${isActive ? 'active' : ''}" data-route="planner" title="Planner" role="button" tabindex="0">
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
    <div class="agents-entry ${isActive ? 'active' : ''}" data-route="agents" title="Agents" role="button" tabindex="0">
      <span class="agents-icon">${ROBOT_ICON}</span>
      <span class="agents-label">Agents</span>
      ${errorIndicator}${waitingBadge}${badge}
    </div>
  `;
}

/**
 * Render the sports entry in the sidebar nav row.
 */
function renderSportsEntry(isActive: boolean): string {
  return `
    <div class="sports-entry ${isActive ? 'active' : ''}" data-route="sports" title="Sports" role="button" tabindex="0">
      <span class="sports-icon">${SPORTS_ICON}</span>
      <span class="sports-label">Sports</span>
    </div>
  `;
}

/**
 * Render the language entry in the sidebar nav row.
 */
function renderLanguageEntry(isActive: boolean): string {
  return `
    <div class="language-entry ${isActive ? 'active' : ''}" data-route="language" title="Language" role="button" tabindex="0">
      <span class="language-icon">${LANGUAGE_ICON}</span>
      <span class="language-label">Language</span>
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

// Last HTML written to the conversations list (F3): callers re-render on
// every sync poll even when nothing changed - the string compare lets the
// no-op case skip the DOM entirely. The first-child anchor detects when
// ANY other renderer (search results, archive, tests rebuilding the DOM)
// has since written to the shared container, forcing a real render.
let lastRenderedListHtml = '';
let lastRenderedFirstChild: Element | null = null;

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
    lastRenderedListHtml = '';
    renderSearchResults();
    return;
  }

  // If archive view is active, render archive view instead
  if (isArchiveViewVisible()) {
    lastRenderedListHtml = '';
    renderArchiveView(container);
    return;
  }

  const { conversations, currentConversation, isLoading, conversationsPagination, user, isPlannerView, isAgentsView, isSportsView, isLanguageView, commandCenterData } = useStore.getState();

  // Build navigation entries row (planner + agents + sports + language side by side)
  const showPlanner = shouldShowPlanner(user);
  const showAgents = shouldShowAgents(user);
  const showSports = shouldShowSports(user);
  const showLanguage = shouldShowLanguage(user);
  const agentUnreadCount = commandCenterData?.total_unread ?? 0;
  const agentWaitingCount = commandCenterData?.agents_waiting ?? 0;
  const agentErrorsCount = commandCenterData?.agents_with_errors ?? 0;

  let navEntriesHtml = '';
  if (showPlanner || showAgents || showSports || showLanguage) {
    const plannerHtml = showPlanner ? renderPlannerEntry(isPlannerView) : '';
    const agentsHtml = showAgents ? renderAgentsEntryWithoutDivider(isAgentsView, agentUnreadCount, agentWaitingCount, agentErrorsCount) : '';
    const sportsHtml = showSports ? renderSportsEntry(isSportsView) : '';
    const languageHtml = showLanguage ? renderLanguageEntry(isLanguageView) : '';
    // Count visible entries for layout
    const visibleCount = [showPlanner, showAgents, showSports, showLanguage].filter(Boolean).length;
    const rowClass = visibleCount === 1 ? ' single' : '';
    navEntriesHtml = `
      <div class="sidebar-nav-row${rowClass}">
        ${plannerHtml}${agentsHtml}${sportsHtml}${languageHtml}
      </div>
      <div class="sidebar-divider"></div>
    `;
  }

  if (isLoading && conversations.length === 0) {
    lastRenderedListHtml = '';
    container.innerHTML = navEntriesHtml + `
      <div class="conversations-loading">
        <div class="conversation-skeleton"></div>
        <div class="conversation-skeleton"></div>
        <div class="conversation-skeleton"></div>
      </div>
    `;
    return;
  }

  if (conversations.length === 0) {
    lastRenderedListHtml = '';
    container.innerHTML = navEntriesHtml + `
      <div class="conversations-empty">
        <p>No conversations yet</p>
        <p class="text-muted">Start a new chat to begin</p>
      </div>
    `;
    return;
  }

  // Render conversations grouped by recency (list arrives sorted by
  // updated_at desc, so a label is emitted whenever the group changes)
  let lastGroup: string | null = null;
  const conversationsHtml = conversations
    .map((conv) => {
      const group = groupForDate(conv.updated_at);
      const label =
        group !== lastGroup
          ? `<div class="conversation-group-label">${escapeHtml(group)}</div>`
          : '';
      lastGroup = group;
      return (
        label +
        renderConversationItem(conv, conv.id === currentConversation?.id && !isPlannerView && !isAgentsView)
      );
    })
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

  const listHtml = navEntriesHtml + conversationsHtml + loadMoreHtml;
  // F3: skip no-op renders entirely (preserves scroll position and hover
  // state across sync polls); when content DID change, keep the offset
  const unchanged =
    listHtml === lastRenderedListHtml &&
    lastRenderedFirstChild !== null &&
    container.firstElementChild === lastRenderedFirstChild;
  if (!unchanged) {
    const scrollTop = container.scrollTop;
    container.innerHTML = listHtml;
    container.scrollTop = scrollTop;
    lastRenderedListHtml = listHtml;
    lastRenderedFirstChild = container.firstElementChild;
    ensureListTabStop(container);
  }

  // Render archive entry in its own pinned container (always visible, not scrolled)
  renderArchiveEntry();

  // Set up infinite scroll if not already set up
  setupInfiniteScroll(container);
}

/**
 * Roving tabindex: exactly one conversation row should be reachable via
 * Tab (the active one, or the first). Arrow keys move focus from there.
 */
function ensureListTabStop(container: HTMLElement): void {
  const items = container.querySelectorAll<HTMLElement>('.conversation-item');
  if (items.length === 0) return;
  const hasStop = Array.from(items).some((el) => el.getAttribute('tabindex') === '0');
  if (!hasStop) {
    items[0].setAttribute('tabindex', '0');
  }
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

  const relativeTime = conv.updated_at
    ? `<span class="conversation-time">${escapeHtml(formatRelativeTime(conv.updated_at))}</span>`
    : '';

  // One-line snippet of the newest message (iMessage-style scanability)
  const preview = conv.last_message_preview
    ? `<div class="conversation-preview">${escapeHtml(conv.last_message_preview)}</div>`
    : '';

  return `
    <div class="conversation-item-wrapper ${isActive ? 'active' : ''}" data-conv-id="${conv.id}">
      <div class="conversation-item" role="button" tabindex="${isActive ? '0' : '-1'}"${isActive ? ' aria-current="true"' : ''}>
        <div class="conversation-text">
          <div class="conversation-title">${title}</div>
          ${preview}
        </div>
        ${unreadBadge}
        ${relativeTime}
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

  const relativeTime = conv.updated_at
    ? `<span class="conversation-time">${escapeHtml(formatRelativeTime(conv.updated_at))}</span>`
    : '';

  return `
    <div class="conversation-item-wrapper" data-conv-id="${conv.id}">
      <div class="conversation-item" role="button" tabindex="-1">
        <div class="conversation-title">${title}</div>
        ${relativeTime}
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
    <button id="user-menu-btn" class="user-menu-btn" aria-haspopup="menu" aria-expanded="false">
      ${avatarHtml}
      <span class="user-name">${escapeHtml(name)}</span>
      <span id="monthly-cost" class="user-cost" title="This month's cost">—</span>
    </button>
    <div class="user-menu hidden" role="menu">
      <button id="settings-btn" class="user-menu-item" role="menuitem">
        ${SETTINGS_ICON}<span>Settings</span>
      </button>
      <button id="memories-btn" class="user-menu-item" role="menuitem">
        ${DATABASE_ICON}<span>Data</span>
      </button>
      <button class="user-menu-item user-menu-archive hidden" role="menuitem" data-route="archive">
        ${ARCHIVE_ICON}<span>Archive</span><span class="archive-count">0</span>
      </button>
      <button id="cost-history-btn" class="user-menu-item" role="menuitem">
        ${COST_ICON}<span>Cost history</span>
      </button>
      <button id="logout-btn" class="user-menu-item user-menu-item-danger" role="menuitem">
        ${LOGOUT_ICON}<span>Log out</span>
      </button>
    </div>
  `;

  // Fetch monthly cost after rendering
  const now = new Date();
  costs.getMonthlyCost(now.getFullYear(), now.getMonth() + 1)
    .then(monthlyCost => {
      const costValueEl = container.querySelector('#monthly-cost');
      if (costValueEl) {
        costValueEl.textContent = monthlyCost.formatted;
      }
    })
    .catch((error) => {
      // Ignore errors - cost display is optional, but log for debugging
      log.warn('Failed to fetch monthly cost', { error });
    });

  // Re-apply archive badge state (the menu was just re-rendered)
  renderArchiveEntry();
}

/**
 * Update the monthly cost display in the sidebar
 */
export async function updateMonthlyCost(): Promise<void> {
  const costValueEl = document.querySelector('#user-info #monthly-cost');
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

  // Remove active from sports entry
  document
    .querySelectorAll<HTMLDivElement>('.sports-entry.active')
    .forEach((el) => el.classList.remove('active'));

  // Remove active from language entry
  document
    .querySelectorAll<HTMLDivElement>('.language-entry.active')
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
    document.querySelectorAll<HTMLDivElement>('.conversation-item-wrapper.active').forEach((el) => el.classList.remove('active'));
    document.querySelectorAll<HTMLDivElement>('.agents-entry.active').forEach((el) => el.classList.remove('active'));
    document.querySelectorAll<HTMLDivElement>('.sports-entry.active').forEach((el) => el.classList.remove('active'));
    document.querySelectorAll<HTMLDivElement>('.language-entry.active').forEach((el) => el.classList.remove('active'));
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
    document.querySelectorAll<HTMLDivElement>('.conversation-item-wrapper.active').forEach((el) => el.classList.remove('active'));
    document.querySelectorAll<HTMLDivElement>('.planner-entry.active').forEach((el) => el.classList.remove('active'));
    document.querySelectorAll<HTMLDivElement>('.sports-entry.active').forEach((el) => el.classList.remove('active'));
    document.querySelectorAll<HTMLDivElement>('.language-entry.active').forEach((el) => el.classList.remove('active'));
    agentsEntry.classList.add('active');
  } else {
    agentsEntry.classList.remove('active');
  }
}

/**
 * Set sports entry as active in sidebar
 */
export function setSportsActive(active: boolean): void {
  const sportsEntry = document.querySelector<HTMLDivElement>('.sports-entry');
  if (!sportsEntry) return;

  if (active) {
    // Remove active from all conversations
    document
      .querySelectorAll<HTMLDivElement>('.conversation-item-wrapper.active')
      .forEach((el) => el.classList.remove('active'));
    // Remove active from planner, agents, and language
    document
      .querySelectorAll<HTMLDivElement>('.planner-entry.active')
      .forEach((el) => el.classList.remove('active'));
    document
      .querySelectorAll<HTMLDivElement>('.agents-entry.active')
      .forEach((el) => el.classList.remove('active'));
    document
      .querySelectorAll<HTMLDivElement>('.language-entry.active')
      .forEach((el) => el.classList.remove('active'));
    // Set sports as active
    sportsEntry.classList.add('active');
  } else {
    sportsEntry.classList.remove('active');
  }
}

/**
 * Set language entry as active in sidebar
 */
export function setLanguageActive(active: boolean): void {
  const languageEntry = document.querySelector<HTMLDivElement>('.language-entry');
  if (!languageEntry) return;

  if (active) {
    // Remove active from all conversations
    document
      .querySelectorAll<HTMLDivElement>('.conversation-item-wrapper.active')
      .forEach((el) => el.classList.remove('active'));
    // Remove active from planner, agents, and sports
    document
      .querySelectorAll<HTMLDivElement>('.planner-entry.active')
      .forEach((el) => el.classList.remove('active'));
    document
      .querySelectorAll<HTMLDivElement>('.agents-entry.active')
      .forEach((el) => el.classList.remove('active'));
    document
      .querySelectorAll<HTMLDivElement>('.sports-entry.active')
      .forEach((el) => el.classList.remove('active'));
    // Set language as active
    languageEntry.classList.add('active');
  } else {
    languageEntry.classList.remove('active');
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
  const archiveItem = document.querySelector<HTMLButtonElement>('.user-menu-archive');
  if (!archiveItem) return;

  const { archivedConversations, archivedPagination } = useStore.getState();

  const total = archivedPagination.totalCount || archivedConversations.length;
  archiveItem.classList.toggle('hidden', total === 0);
  const badge = archiveItem.querySelector('.archive-count');
  if (badge) badge.textContent = String(total);
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
  ensureListTabStop(container);

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