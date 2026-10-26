import { createElement, getElementById, clearElement } from '../utils/dom';
import { formatRelativeTime, groupForDate } from '../utils/relative-time';
import { createUserAvatarElement } from '../utils/avatar';
import { isSidebarPreviewsEnabled, getSwipeQuickAction } from '../utils/preferences';
import { ACTIVITY_ICON, ARCHIVE_ICON, CHECK_ICON, CHEVRON_RIGHT_ICON, COST_ICON, DATABASE_ICON, DELETE_ICON, EDIT_ICON, LANGUAGE_ICON, LOGOUT_ICON, PIN_ICON, PLANNER_ICON, ROBOT_ICON, SETTINGS_ICON, SPORTS_ICON, UNARCHIVE_ICON, UNPIN_ICON, createIconButton, createIconElement, iconNodes, type IconHtml } from '../utils/icons';
import { useStore } from '../state/store';
import { DEFAULT_CONVERSATION_TITLE } from '../types/api';
import type { CommandCenterResponse, Conversation, User } from '../types/api';
import { conversations as conversationsApi } from '../api/conversations';
import { costs } from '../api/costs';
import { createLogger } from '../utils/logger';
import { getSyncManager } from '../sync/SyncManager';
import { isSearchResultsVisible, renderSearchResults } from './SearchResults';
import { renderTrashEntry, renderTrashView } from './TrashView';
import { selectionCheckbox } from './SidebarSelection';
import { isConversationSelected } from '../state/slices/selection';
import {
  LOAD_MORE_THRESHOLD_PX,
  INFINITE_SCROLL_DEBOUNCE_MS,
  CONVERSATION_ITEM_HEIGHT_PX,
  CONVERSATIONS_MIN_PAGE_SIZE,
  VIEWPORT_BUFFER_MULTIPLIER,
  SIDEBAR_TIME_REFRESH_INTERVAL_MS,
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
function shouldShowPlanner(user: User | null): boolean {
  if (!user) return false;
  // Check if user has either integration connected
  // These fields are set after fetching integration status in loadInitialData
  return !!(user.todoist_connected || user.calendar_connected);
}

/**
 * Check if the agents entry should be shown.
 * Always visible when user is logged in (agents are a core feature).
 */
function shouldShowAgents(user: User | null): boolean {
  return !!user;
}

/**
 * Check if the sports entry should be shown.
 * Always visible when user is logged in.
 */
function shouldShowSports(user: User | null): boolean {
  return !!user;
}

/**
 * Check if the language entry should be shown.
 * Always visible when user is logged in.
 */
function shouldShowLanguage(user: User | null): boolean {
  return !!user;
}

const el = createElement;

/** A nav row entry (planner, agents, sports, language): icon, label, extras. */
function navEntry(name: string, label: string, icon: IconHtml, isActive: boolean, title: string, extras: HTMLElement[] = []): HTMLElement {
  return el('div', { class: `${name}-entry ${isActive ? 'active' : ''}`, 'data-route': name, title, role: 'button', tabindex: '0' }, [
    createIconElement(`${name}-icon`, icon),
    el('span', { class: `${name}-label` }, [label]),
    ...extras,
  ]);
}

/**
 * The agents entry in the sidebar nav row. Shows three types of indicators:
 * - Purple unread badge: number of unread assistant messages
 * - Amber waiting badge: number of agents waiting for approval
 * - Red error dot: agents with failed last execution
 */
function agentsEntry(isActive: boolean, unreadCount: number, waitingCount: number, errorsCount: number): HTMLElement {
  const unreadTooltip = unreadCount === 1 ? '1 unread message' : `${unreadCount} unread messages`;
  const waitingTooltip = waitingCount === 1 ? '1 agent waiting for approval' : `${waitingCount} agents waiting for approval`;
  const count = (n: number): string => (n > 99 ? '99+' : String(n));
  // One badge only: two side by side truncated the label in the nav grid.
  // Waiting approvals need action, so they win; the tooltip carries both.
  const badge =
    waitingCount > 0
      ? el('span', { class: 'waiting-badge', title: waitingTooltip }, [count(waitingCount)])
      : unreadCount > 0
        ? el('span', { class: 'unread-badge', title: unreadTooltip }, [count(unreadCount)])
        : null;
  const errorTooltip = errorsCount === 1 ? '1 agent failed' : `${errorsCount} agents failed`;
  const errorIndicator = errorsCount > 0 ? el('span', { class: 'error-indicator', title: errorTooltip }) : null;
  const title = ['Agents', waitingCount > 0 ? waitingTooltip : '', unreadCount > 0 ? unreadTooltip : '']
    .filter(Boolean)
    .join(' · ');
  return navEntry('agents', 'Agents', ROBOT_ICON, isActive, title, [errorIndicator, badge].filter((e): e is HTMLElement => !!e));
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

// A detached copy of the list last written to the conversations container:
// callers re-render on every sync poll even when nothing changed - an equal
// newly built list lets the no-op case skip the DOM write entirely. The
// first-child anchor detects when ANY other renderer (search results,
// archive, tests rebuilding the DOM) has since written to the shared
// container, forcing a real render.
let lastRenderedList: DocumentFragment | null = null;
let lastRenderedFirstChild: Element | null = null;

/**
 * Search results, the archive or the trash take the list's place when
 * active. Returns whether one of them rendered.
 */
function renderAlternateList(container: HTMLDivElement): boolean {
  if (isSearchResultsVisible()) {
    renderSearchResults();
    return true;
  }
  if (isArchiveViewVisible()) {
    renderArchiveView(container);
    return true;
  }
  if (useStore.getState().isTrashView) {
    renderTrashView(container, renderConversationsList);
    return true;
  }
  return false;
}

/** The agents entry with the command center's unread, waiting and error counts. */
function agentsEntryWithCounts(isAgentsView: boolean, commandCenterData: CommandCenterResponse | null): HTMLElement {
  return agentsEntry(
    isAgentsView,
    commandCenterData?.total_unread ?? 0,
    commandCenterData?.agents_waiting ?? 0,
    commandCenterData?.agents_with_errors ?? 0
  );
}

/** Navigation entries row (planner + agents + sports + language side by side) and its divider; none when none show. */
function navEntries(): HTMLElement[] {
  const { user, isPlannerView, isAgentsView, isSportsView, isLanguageView, commandCenterData } = useStore.getState();
  const showPlanner = shouldShowPlanner(user);
  const showAgents = shouldShowAgents(user);
  const showSports = shouldShowSports(user);
  const showLanguage = shouldShowLanguage(user);
  if (!showPlanner && !showAgents && !showSports && !showLanguage) return [];

  // Count visible entries for layout
  const visibleCount = [showPlanner, showAgents, showSports, showLanguage].filter(Boolean).length;
  const rowClass = visibleCount === 1 ? ' single' : '';
  return [
    el('div', { class: `sidebar-nav-row${rowClass}` }, [
      showPlanner && navEntry('planner', 'Planner', PLANNER_ICON, isPlannerView, 'Planner'),
      showAgents && agentsEntryWithCounts(isAgentsView, commandCenterData),
      showSports && navEntry('sports', 'Sports', SPORTS_ICON, isSportsView, 'Sports'),
      showLanguage && navEntry('language', 'Language', LANGUAGE_ICON, isLanguageView, 'Language'),
    ]),
    el('div', { class: 'sidebar-divider' }),
  ];
}

function groupLabel(text: string): HTMLElement {
  return el('div', { class: 'conversation-group-label' }, [text]);
}

/** The conversation rows: a Pinned group, then recency groups with labels. */
function conversationGroups(conversations: Conversation[]): HTMLElement[] {
  const { currentConversation, isPlannerView, isAgentsView, isSportsView, isLanguageView, isStorageView } = useStore.getState();
  // A conversation row is highlighted only in the plain chat view - special
  // views (planner, agents, sports, language, storage) set currentConversation
  // to their own conversation, which must not re-highlight a list row on
  // re-render
  const inSpecialView = isPlannerView || isAgentsView || isSportsView || isLanguageView || isStorageView;
  const activeId = inSpecialView ? undefined : currentConversation?.id;

  // Pinned conversations get their own group at the top; the rest are
  // grouped by recency (list arrives sorted by updated_at desc, so a label
  // is emitted whenever the group changes)
  const pinnedConversations = conversations.filter((c) => c.pinned);
  const regularConversations = conversations.filter((c) => !c.pinned);

  const rows: HTMLElement[] = [];
  if (pinnedConversations.length) {
    rows.push(groupLabel('Pinned'), ...pinnedConversations.map((conv) => conversationItem(conv, conv.id === activeId)));
  }

  let lastGroup: string | null = null;
  for (const conv of regularConversations) {
    const group = groupForDate(conv.updated_at);
    if (group !== lastGroup) rows.push(groupLabel(group));
    lastGroup = group;
    rows.push(conversationItem(conv, conv.id === activeId));
  }
  return rows;
}

/** Three bouncing dots under a list while more rows can load. */
function loadMoreDots(className: string, loading: boolean): HTMLElement {
  return el('div', { class: `${className} ${loading ? 'loading' : ''}` }, [
    el('div', { class: 'loading-dots' }, [el('span'), el('span'), el('span')]),
  ]);
}

/**
 * Render the conversations list in the sidebar
 * If search is active, renders search results instead
 * If archive view is active, renders archive view instead
 */
export function renderConversationsList(): void {
  const container = getElementById<HTMLDivElement>('conversations-list');
  if (!container) return;

  if (renderAlternateList(container)) {
    lastRenderedList = null;
    return;
  }

  // Archive/trash menu entry counts change on archive/delete - refresh them
  // before the empty/loading early returns below
  renderArchiveEntry();
  renderTrashEntry();

  const { conversations, isLoading, conversationsPagination } = useStore.getState();
  const nav = navEntries();

  if (isLoading && conversations.length === 0) {
    lastRenderedList = null;
    container.replaceChildren(
      ...nav,
      el('div', { class: 'conversations-loading' }, [
        el('div', { class: 'conversation-skeleton' }),
        el('div', { class: 'conversation-skeleton' }),
        el('div', { class: 'conversation-skeleton' }),
      ])
    );
    return;
  }

  if (conversations.length === 0) {
    lastRenderedList = null;
    container.replaceChildren(
      ...nav,
      el('div', { class: 'conversations-empty' }, [
        el('p', {}, ['No conversations yet']),
        el('p', { class: 'text-muted' }, ['Start a new chat to begin']),
      ])
    );
    return;
  }

  const list = document.createDocumentFragment();
  list.append(
    ...nav,
    ...conversationGroups(conversations),
    // Loading indicator for "load more" if there are more pages
    ...(conversationsPagination.hasMore ? [loadMoreDots('conversations-load-more', conversationsPagination.isLoadingMore)] : [])
  );
  // F3: skip no-op renders entirely (preserves scroll position and hover
  // state across sync polls); when content DID change, keep the offset
  const unchanged =
    lastRenderedList !== null &&
    lastRenderedFirstChild !== null &&
    container.firstElementChild === lastRenderedFirstChild &&
    list.isEqualNode(lastRenderedList);
  if (!unchanged) {
    const scrollTop = container.scrollTop;
    lastRenderedList = list.cloneNode(true) as DocumentFragment;
    container.replaceChildren(list);
    container.scrollTop = scrollTop;
    lastRenderedFirstChild = container.firstElementChild;
    ensureListTabStop(container);
  }

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
    items[0]?.setAttribute('tabindex', '0');
  }
}

/** A row's relative time (null without an update time). */
function conversationTime(conv: Conversation): HTMLElement | null {
  return conv.updated_at ? el('span', { class: 'conversation-time' }, [formatRelativeTime(conv.updated_at)]) : null;
}

/** "⋯ More" on a swiped row. */
function moreButton(dataAttribute: string, id: string): HTMLButtonElement {
  return el('button', { class: 'conversation-more-swipe', [dataAttribute]: id, 'aria-label': 'More actions' }, ['⋯']);
}

/**
 * A single conversation item
 */
function conversationItem(conv: Conversation, isActive: boolean): HTMLElement {
  const id = conv.id;
  // Bulk delete selection mode: a checkbox per row (none outside it)
  const state = useStore.getState();
  const selected = state.isSelecting && isConversationSelected(state, conv);
  const unread = conv.unreadCount ?? 0;
  const pinLabel = conv.pinned ? 'Unpin' : 'Pin';

  return el('div', { class: `conversation-item-wrapper ${isActive ? 'active' : ''}${selected ? ' selected' : ''}`, 'data-conv-id': id }, [
    el('div', { class: 'conversation-item', role: 'button', tabindex: isActive ? '0' : '-1', ...(isActive ? { 'aria-current': 'true' } : {}) }, [
      selectionCheckbox(conv),
      el('div', { class: 'conversation-text' }, [
        el('div', { class: 'conversation-title' }, [conv.title || DEFAULT_CONVERSATION_TITLE]),
        // One-line snippet of the newest message (iMessage-style
        // scanability); per-device settings toggle
        !!conv.last_message_preview &&
          isSidebarPreviewsEnabled() &&
          el('div', { class: 'conversation-preview' }, [conv.last_message_preview]),
      ]),
      unread > 0 && el('span', { class: 'unread-badge' }, [unread > 99 ? '99+' : String(unread)]),
      conversationTime(conv),
      el('div', { class: 'conversation-actions' }, [
        createIconButton({ class: 'conversation-pin', 'data-pin-id': id, 'aria-label': pinLabel, title: pinLabel }, conv.pinned ? UNPIN_ICON : PIN_ICON),
        createIconButton({ class: 'conversation-rename', 'data-rename-id': id, 'aria-label': 'Rename' }, EDIT_ICON),
        createIconButton({ class: 'conversation-archive', 'data-archive-id': id, 'aria-label': 'Archive' }, ARCHIVE_ICON),
        createIconButton({ class: 'conversation-delete', 'data-delete-id': id, 'aria-label': 'Delete' }, DELETE_ICON),
      ]),
    ]),
    swipeActions(id),
  ]);
}

/**
 * Swipe-revealed action row: ⋯ More plus one quick action. Which quick
 * action (Archive or Delete) is a per-device preference - some people
 * delete far more often than they archive. Delete reuses the existing
 * data-delete-id delegation, so the confirm dialog still applies.
 */
export function swipeActions(convId: string): HTMLElement {
  const quickAction =
    getSwipeQuickAction() === 'delete'
      ? createIconButton({ class: 'conversation-delete-swipe', 'data-delete-id': convId, 'aria-label': 'Delete' }, DELETE_ICON)
      : createIconButton({ class: 'conversation-archive-swipe', 'data-archive-id': convId, 'aria-label': 'Archive' }, ARCHIVE_ICON);
  return el('div', { class: 'conversation-actions-swipe' }, [moreButton('data-more-id', convId), quickAction]);
}

/**
 * A single archived conversation item (with rename + unarchive + delete actions)
 */
function archivedConversationItem(conv: Conversation): HTMLElement {
  const id = conv.id;
  return el('div', { class: 'conversation-item-wrapper', 'data-conv-id': id }, [
    el('div', { class: 'conversation-item', role: 'button', tabindex: '-1' }, [
      el('div', { class: 'conversation-title' }, [conv.title || DEFAULT_CONVERSATION_TITLE]),
      conversationTime(conv),
      el('div', { class: 'conversation-actions' }, [
        createIconButton({ class: 'conversation-rename', 'data-rename-id': id, 'aria-label': 'Rename' }, EDIT_ICON),
        createIconButton({ class: 'conversation-unarchive', 'data-unarchive-id': id, 'aria-label': 'Unarchive' }, UNARCHIVE_ICON),
        createIconButton({ class: 'conversation-delete', 'data-delete-id': id, 'aria-label': 'Delete' }, DELETE_ICON),
      ]),
    ]),
    el('div', { class: 'conversation-actions-swipe' }, [
      moreButton('data-more-archived-id', id),
      createIconButton({ class: 'conversation-unarchive-swipe', 'data-unarchive-id': id, 'aria-label': 'Unarchive' }, UNARCHIVE_ICON),
    ]),
  ]);
}

/** A user-menu item: its icon, label and extras. */
function menuItem(attributes: Record<string, string>, icon: IconHtml, label: string, extras: HTMLElement[] = []): HTMLButtonElement {
  return el('button', { ...attributes, role: 'menuitem' }, [iconNodes(icon), el('span', {}, [label]), ...extras]);
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

  container.replaceChildren(
    el('button', { id: 'user-menu-btn', class: 'user-menu-btn', 'aria-haspopup': 'menu', 'aria-expanded': 'false' }, [
      createUserAvatarElement(user.picture || undefined, name),
      el('span', { class: 'user-name' }, [name]),
      el('span', { id: 'monthly-cost', class: 'user-cost', title: "This month's cost" }, ['—']),
    ]),
    el('div', { class: 'user-menu hidden', role: 'menu' }, [
      menuItem({ id: 'settings-btn', class: 'user-menu-item' }, SETTINGS_ICON, 'Settings'),
      menuItem({ id: 'memories-btn', class: 'user-menu-item' }, DATABASE_ICON, 'Data'),
      menuItem({ class: 'user-menu-item user-menu-archive hidden', 'data-route': 'archive' }, ARCHIVE_ICON, 'Archive', [
        el('span', { class: 'archive-count' }, ['0']),
      ]),
      menuItem({ class: 'user-menu-item user-menu-trash hidden', 'data-route': 'trash' }, DELETE_ICON, 'Trash', [
        el('span', { class: 'archive-count trash-count' }, ['0']),
      ]),
      menuItem({ id: 'select-chats-btn', class: 'user-menu-item' }, CHECK_ICON, 'Select chats'),
      menuItem({ id: 'cost-history-btn', class: 'user-menu-item' }, COST_ICON, 'Cost history'),
      ...(user.is_admin ? [menuItem({ id: 'admin-btn', class: 'user-menu-item' }, ACTIVITY_ICON, 'Admin')] : []),
      menuItem({ id: 'logout-btn', class: 'user-menu-item user-menu-item-danger' }, LOGOUT_ICON, 'Log out'),
    ])
  );

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

  // Re-apply archive/trash badge state (the menu was just re-rendered)
  renderArchiveEntry();
  renderTrashEntry();
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

// Timer that keeps relative-time labels ("2m", "3h") and date-group headers
// fresh: they are computed at render time and would otherwise only update
// when a sync poll returns changed data
let timeRefreshInterval: ReturnType<typeof setInterval> | null = null;

/**
 * Periodically re-render the conversations list so relative times and date
 * groups stay accurate. Gated on tab visibility; the unchanged-list check
 * makes ticks cheap when no label actually changed (no DOM write).
 */
export function initSidebarTimeRefresh(): void {
  if (timeRefreshInterval) return;
  timeRefreshInterval = setInterval(() => {
    if (document.visibilityState !== 'visible') return;
    renderConversationsList();
  }, SIDEBAR_TIME_REFRESH_INTERVAL_MS);
}

/**
 * Stop the relative-time refresh timer (tests / teardown).
 */
export function cleanupSidebarTimeRefresh(): void {
  if (timeRefreshInterval) {
    clearInterval(timeRefreshInterval);
    timeRefreshInterval = null;
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
  const header = el('div', { class: 'archive-view-header' }, [
    el('button', { class: 'archive-back-btn', 'data-archive-back': '', 'aria-label': 'Back to conversations' }, [
      createIconElement('archive-back-icon', CHEVRON_RIGHT_ICON),
    ]),
    el('span', { class: 'archive-view-title' }, ['Archive']),
    el('span', { class: 'archive-count' }, [String(archivedPagination.totalCount)]),
  ]);

  // Loading state
  if (archivedConversations.length === 0 && archivedPagination.isLoadingMore) {
    container.replaceChildren(header, el('div', { class: 'conversations-loading' }, [el('div', { class: 'loading-spinner' })]));
    return;
  }

  // Empty state
  if (archivedConversations.length === 0) {
    container.replaceChildren(header, el('div', { class: 'conversations-empty' }, [el('p', {}, ['No archived conversations'])]));
    return;
  }

  container.replaceChildren(
    header,
    ...archivedConversations.map(archivedConversationItem),
    // Load more indicator
    ...(archivedPagination.hasMore ? [loadMoreDots('archive-load-more', archivedPagination.isLoadingMore)] : [])
  );
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
        void loadMoreArchivedConversations();
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
        void loadMoreConversations(container);
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

/** Seed the sync manager's message counts for conversations it has not seen. */
function initializeLocalMessageCounts(conversations: Conversation[]): void {
  const syncManager = getSyncManager();
  if (!syncManager) return;
  for (const conv of conversations) {
    if (conv.messageCount !== undefined) {
      syncManager.initializeLocalMessageCount(conv.id, conv.messageCount);
    }
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
    initializeLocalMessageCounts(result.conversations);

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