/**
 * Search results component for displaying full-text search results.
 *
 * Features:
 * - Displays search results replacing the conversation list when active
 * - Shows loading spinner during search
 * - Shows empty state when no results found
 * - Converts [[HIGHLIGHT]] markers to <mark> tags
 * - Displays result count
 */

import { useStore } from '../state/store';
import { escapeHtml, getElementById } from '../utils/dom';
import { createLogger } from '../utils/logger';
import { renderConversationsList } from './Sidebar';
import type { SearchResult } from '../types/api';

const log = createLogger('search-results');

/**
 * Check if search results should be visible
 */
export function isSearchResultsVisible(): boolean {
  const { isSearchActive } = useStore.getState();
  return isSearchActive;
}

/**
 * Render search results in place of conversation list
 */
export function renderSearchResults(): void {
  const container = getElementById<HTMLDivElement>('conversations-list');
  if (!container) return;

  const { searchQuery, searchResults, searchTotal, isSearching, isSearchActive } = useStore.getState();

  // If search is not active, don't render
  if (!isSearchActive) {
    return;
  }

  // Loading state
  if (isSearching) {
    container.innerHTML = `
      <div class="search-loading">
        <div class="loading-spinner"></div>
        <p>Searching...</p>
      </div>
    `;
    return;
  }

  // Empty query - show hint
  if (!searchQuery.trim()) {
    container.innerHTML = `
      <div class="search-empty">
        <p>Type to search conversations</p>
      </div>
    `;
    return;
  }

  // No results
  if (searchResults.length === 0) {
    container.innerHTML = `
      <div class="search-empty">
        <p>No results found for "${escapeHtml(searchQuery)}"</p>
      </div>
    `;
    return;
  }

  // Render results
  const resultsHtml = searchResults.map(renderSearchResultItem).join('');
  const countText = searchTotal === 1 ? '1 result' : `${searchTotal} results`;

  container.innerHTML = `
    <div class="search-results-header">
      <span class="search-results-count">${countText}</span>
    </div>
    <div class="search-results-list">
      ${resultsHtml}
    </div>
  `;

  log.debug('Search results rendered', { count: searchResults.length, total: searchTotal });
}

/**
 * Render a single search result item
 */
function renderSearchResultItem(result: SearchResult): string {
  const title = escapeHtml(result.conversation_title);
  const isMessageMatch = result.match_type === 'message';

  // Format the snippet with highlights
  let snippetHtml = '';
  if (isMessageMatch && result.message_snippet) {
    snippetHtml = formatSnippet(result.message_snippet);
  }

  // Build data attributes for navigation
  const dataAttrs = `data-conv-id="${result.conversation_id}"${
    result.message_id ? ` data-message-id="${result.message_id}"` : ''
  }`;

  return `
    <div class="search-result-item" ${dataAttrs}>
      <div class="search-result-title">${title}</div>
      ${snippetHtml ? `<div class="search-result-snippet">${snippetHtml}</div>` : ''}
      <div class="search-result-meta">
        <span class="search-result-type">${isMessageMatch ? 'Message' : 'Title'}</span>
        ${result.created_at ? `<span class="search-result-date">${formatDate(result.created_at)}</span>` : ''}
      </div>
    </div>
  `;
}

/**
 * Format snippet text, converting [[HIGHLIGHT]] markers to <mark> tags
 */
function formatSnippet(snippet: string): string {
  // First escape HTML, then convert markers
  // The markers use [[ and ]] which are safe after escaping
  let escaped = escapeHtml(snippet);

  // Replace [[HIGHLIGHT]] markers with <mark> tags
  // Pattern: [[HIGHLIGHT]]text[[/HIGHLIGHT]]
  escaped = escaped.replace(/\[\[HIGHLIGHT\]\]/g, '<mark>');
  escaped = escaped.replace(/\[\[\/HIGHLIGHT\]\]/g, '</mark>');

  return escaped;
}

/**
 * Format date for display
 */
function formatDate(isoDate: string): string {
  try {
    const date = new Date(isoDate);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) {
      // Today - show time
      return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
    } else if (diffDays === 1) {
      return 'Yesterday';
    } else if (diffDays < 7) {
      // Within a week - show day name
      return date.toLocaleDateString(undefined, { weekday: 'long' });
    } else {
      // Older - show date
      return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    }
  } catch {
    return '';
  }
}

/**
 * Subscribe to store changes and re-render when search state changes
 */
export function subscribeToSearchChanges(onResultClick: (convId: string, messageId: string | null) => void): () => void {
  // Track previous search active state to detect when search is deactivated
  let wasSearchActive = useStore.getState().isSearchActive;

  // Subscribe to search state changes
  const unsubscribe = useStore.subscribe(
    (state) => ({
      isSearchActive: state.isSearchActive,
      searchResults: state.searchResults,
      isSearching: state.isSearching,
      searchQuery: state.searchQuery,
    }),
    (state) => {
      // If search was active and now it's not, re-render conversation list
      if (wasSearchActive && !state.isSearchActive) {
        log.debug('Search deactivated, re-rendering conversation list');
        renderConversationsList();
      }
      // Update tracking variable
      wasSearchActive = state.isSearchActive;

      // Re-render search results when search state changes and search is active
      if (isSearchResultsVisible()) {
        renderSearchResults();
      }
    },
    { equalityFn: (a, b) =>
      a.isSearchActive === b.isSearchActive &&
      a.searchResults === b.searchResults &&
      a.isSearching === b.isSearching &&
      a.searchQuery === b.searchQuery
    }
  );

  // Set up click handler for results
  const container = getElementById<HTMLDivElement>('conversations-list');
  if (container) {
    const handleClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      const resultItem = target.closest<HTMLDivElement>('.search-result-item');

      if (resultItem) {
        const convId = resultItem.dataset.convId;
        const messageId = resultItem.dataset.messageId || null;

        if (convId) {
          log.debug('Search result clicked', { convId, messageId });
          onResultClick(convId, messageId);
        }
      }
    };

    container.addEventListener('click', handleClick);

    // Return cleanup function
    return () => {
      unsubscribe();
      container.removeEventListener('click', handleClick);
    };
  }

  return unsubscribe;
}
