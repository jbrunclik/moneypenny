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
import { createElement, getElementById } from '../utils/dom';
import { createLogger } from '../utils/logger';
import { formatRelativeTime } from '../utils/relative-time';
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

  const { searchQuery, searchResults, searchTotal, isSearching, isSearchActive, viewedSearchResultId } = useStore.getState();

  // If search is not active, don't render
  if (!isSearchActive) {
    return;
  }

  // Loading state
  if (isSearching) {
    container.replaceChildren(
      createElement('div', { class: 'search-loading' }, [
        createElement('div', { class: 'loading-spinner' }),
        createElement('p', {}, ['Searching...']),
      ])
    );
    return;
  }

  // Empty query - show hint
  if (!searchQuery.trim()) {
    // Forensics for a rare load-dependent E2E flake where this hint
    // rendered after the test filled the input: if the DOM input still
    // has text while the store query is empty, the input event was
    // lost; if both are empty, something cleared the input. Shows up in
    // Playwright traces (CI records them on retry).
    const inputEl = document.getElementById('search-input') as HTMLInputElement | null;
    if (inputEl?.value.trim()) {
      log.warn('Search query empty in store but input has text', {
        inputValue: inputEl.value,
      });
    }
    container.replaceChildren(searchEmpty('Type to search conversations'));
    return;
  }

  // No results
  if (searchResults.length === 0) {
    container.replaceChildren(searchEmpty(`No results found for "${searchQuery}"`));
    return;
  }

  // Render results with active state (use index for unique identification)
  const countText = searchTotal === 1 ? '1 result' : `${searchTotal} results`;

  container.replaceChildren(
    createElement('div', { class: 'search-results-header' }, [
      createElement('span', { class: 'search-results-count' }, [countText]),
    ]),
    createElement(
      'div',
      { class: 'search-results-list' },
      searchResults.map((result, index) => searchResultItem(result, index, viewedSearchResultId))
    )
  );

  log.debug('Search results rendered', { count: searchResults.length, total: searchTotal });
}

function searchEmpty(text: string): HTMLElement {
  return createElement('div', { class: 'search-empty' }, [createElement('p', {}, [text])]);
}

/**
 * A single search result item
 */
function searchResultItem(result: SearchResult, index: number, viewedResultIndex: number | null): HTMLElement {
  const isMessageMatch = result.match_type === 'message';
  const snippet = isMessageMatch && result.message_snippet ? formatSnippet(result.message_snippet) : null;

  // Check if this result is currently being viewed (by index, not by message_id)
  const isActive = viewedResultIndex === index;

  return createElement(
    'div',
    {
      class: `search-result-item${isActive ? ' active' : ''}`,
      // Data attributes for navigation (index for the click handler)
      'data-conv-id': result.conversation_id,
      'data-result-index': String(index),
      ...(result.message_id ? { 'data-message-id': result.message_id } : {}),
    },
    [
      createElement('div', { class: 'search-result-title' }, [result.conversation_title]),
      snippet,
      createElement('div', { class: 'search-result-meta' }, [
        createElement('span', { class: 'search-result-type' }, [isMessageMatch ? 'Message' : 'Title']),
        !!result.created_at &&
          createElement('span', { class: 'search-result-date' }, [formatRelativeTime(result.created_at)]),
      ]),
    ]
  );
}

const HIGHLIGHT_MARKER = /(\[\[HIGHLIGHT\]\]|\[\[\/HIGHLIGHT\]\])/;

/**
 * The snippet with its [[HIGHLIGHT]]text[[/HIGHLIGHT]] spans as <mark>s (an
 * unclosed one runs to the end, a stray close is dropped); null when empty.
 */
function formatSnippet(snippet: string): HTMLElement | null {
  const root = createElement('div', { class: 'search-result-snippet' });
  const open: HTMLElement[] = [];
  for (const part of snippet.split(HIGHLIGHT_MARKER)) {
    const parent = open.at(-1) ?? root;
    if (part === '[[HIGHLIGHT]]') {
      const mark = createElement('mark');
      parent.appendChild(mark);
      open.push(mark);
    } else if (part === '[[/HIGHLIGHT]]') {
      open.pop();
    } else if (part) {
      parent.append(part);
    }
  }
  root.normalize(); // text around a dropped marker is one node, as parsed
  return root.hasChildNodes() ? root : null;
}

/**
 * Subscribe to store changes and re-render when search state changes;
 * `onSearchClosed` restores the conversation list.
 */
export function subscribeToSearchChanges(
  onResultClick: (convId: string, messageId: string | null, resultIndex: number) => void,
  onSearchClosed: () => void
): () => void {
  // Track previous search active state to detect when search is deactivated
  let wasSearchActive = useStore.getState().isSearchActive;

  // Subscribe to search state changes
  const unsubscribe = useStore.subscribe(
    (state) => ({
      isSearchActive: state.isSearchActive,
      searchResults: state.searchResults,
      isSearching: state.isSearching,
      searchQuery: state.searchQuery,
      viewedSearchResultId: state.viewedSearchResultId,
    }),
    (state) => {
      // If search was active and now it's not, re-render conversation list
      if (wasSearchActive && !state.isSearchActive) {
        log.debug('Search deactivated, re-rendering conversation list');
        onSearchClosed();
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
      a.searchQuery === b.searchQuery &&
      a.viewedSearchResultId === b.viewedSearchResultId
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
        const resultIndex = resultItem.dataset.resultIndex;

        if (convId && resultIndex !== undefined) {
          log.debug('Search result clicked', { convId, messageId, resultIndex });
          onResultClick(convId, messageId, parseInt(resultIndex, 10));
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
