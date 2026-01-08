/**
 * Search input component for full-text search across conversations.
 *
 * Features:
 * - Debounced input (300ms) to avoid excessive API calls
 * - Search icon and clear button
 * - Escape key clears search and deactivates search mode
 * - Focus activates search mode (shows search results panel)
 */

import { useStore } from '../state/store';
import { search as searchApi } from '../api/client';
import { SEARCH_ICON, CLOSE_ICON } from '../utils/icons';
import { getElementById } from '../utils/dom';
import { createLogger } from '../utils/logger';
import { SEARCH_DEBOUNCE_MS } from '../config';

const log = createLogger('search-input');

let debounceTimeout: ReturnType<typeof setTimeout> | null = null;
let currentSearchQuery: string = ''; // Track current query to handle race conditions

/**
 * Initialize search input event handlers
 */
export function initSearchInput(): void {
  const container = getElementById<HTMLDivElement>('search-container');
  if (!container) return;

  // Render the search input
  renderSearchInput();

  // Set up event delegation for the container
  container.addEventListener('input', handleInput);
  container.addEventListener('keydown', handleKeydown);
  container.addEventListener('focus', handleFocus, true);
  container.addEventListener('click', handleClick);

  log.debug('Search input initialized');
}

/**
 * Render the search input HTML
 */
export function renderSearchInput(): void {
  const container = getElementById<HTMLDivElement>('search-container');
  if (!container) return;

  const { searchQuery, isSearchActive } = useStore.getState();

  // Show clear button when search is active (even with empty query) so mobile users can exit
  const showClearBtn = isSearchActive || searchQuery;

  container.innerHTML = `
    <div class="search-input-wrapper">
      <span class="search-icon">${SEARCH_ICON}</span>
      <input
        type="text"
        id="search-input"
        class="search-input"
        placeholder="Search conversations..."
        value="${escapeAttr(searchQuery)}"
        autocomplete="off"
        spellcheck="false"
      />
      <button
        type="button"
        class="search-clear-btn ${showClearBtn ? '' : 'hidden'}"
        aria-label="Clear search"
      >
        ${CLOSE_ICON}
      </button>
    </div>
  `;
}

/**
 * Handle input changes with debounce
 */
function handleInput(event: Event): void {
  const target = event.target as HTMLInputElement;
  if (target.id !== 'search-input') return;

  const query = target.value;

  // Update store immediately for UI responsiveness
  useStore.getState().setSearchQuery(query);

  // Show/hide clear button
  const clearBtn = document.querySelector('.search-clear-btn');
  if (clearBtn) {
    clearBtn.classList.toggle('hidden', !query);
  }

  // Debounce the actual search
  if (debounceTimeout) {
    clearTimeout(debounceTimeout);
  }

  debounceTimeout = setTimeout(() => {
    performSearch(query);
  }, SEARCH_DEBOUNCE_MS);
}

/**
 * Handle keyboard events
 */
function handleKeydown(event: KeyboardEvent): void {
  const target = event.target as HTMLInputElement;
  if (target.id !== 'search-input') return;

  if (event.key === 'Escape') {
    event.preventDefault();
    clearSearch();
    target.blur();
  }
}

/**
 * Handle focus - activate search mode
 */
function handleFocus(event: FocusEvent): void {
  const target = event.target as HTMLInputElement;
  if (target.id !== 'search-input') return;

  useStore.getState().activateSearch();

  // Show clear button so user can exit search mode
  const clearBtn = document.querySelector('.search-clear-btn');
  clearBtn?.classList.remove('hidden');

  log.debug('Search activated');
}

/**
 * Handle click events (clear button)
 *
 * UX behavior:
 * - If there's text in the input: clear it but keep search mode active (user might want to search again)
 * - If input is empty (button shown because search is active): exit search mode entirely
 */
function handleClick(event: MouseEvent): void {
  const target = event.target as HTMLElement;
  const clearBtn = target.closest('.search-clear-btn');

  if (clearBtn) {
    event.preventDefault();
    const input = getElementById<HTMLInputElement>('search-input');
    const hasText = input && input.value.trim().length > 0;

    if (hasText) {
      // Clear text but keep search mode active for a new search
      clearSearchText();
      input?.focus();
    } else {
      // No text - exit search mode entirely
      clearSearch();
      input?.blur();
    }
  }
}

/**
 * Perform the search API call
 */
async function performSearch(query: string): Promise<void> {
  // Track this query to handle race conditions
  currentSearchQuery = query;

  // Empty query - clear results but keep search active
  if (!query.trim()) {
    useStore.getState().setSearchResults([], 0);
    useStore.getState().setIsSearching(false);
    return;
  }

  const store = useStore.getState();
  store.setIsSearching(true);

  try {
    log.debug('Searching', { query });
    const response = await searchApi.query(query);

    // Guard: check if query changed during API call
    if (currentSearchQuery !== query) {
      log.debug('Search query changed during API call, ignoring results', {
        searchedQuery: query,
        currentQuery: currentSearchQuery,
      });
      return;
    }

    store.setSearchResults(response.results, response.total);
    log.info('Search completed', { query, resultCount: response.results.length, total: response.total });
  } catch (error) {
    log.error('Search failed', { query, error });
    // Keep previous results on error, just clear loading state
  } finally {
    // Only clear loading if this is still the current query
    if (currentSearchQuery === query) {
      useStore.getState().setIsSearching(false);
    }
  }
}

/**
 * Clear search text but keep search mode active (for typing a new query)
 */
function clearSearchText(): void {
  // Cancel any pending debounced search
  if (debounceTimeout) {
    clearTimeout(debounceTimeout);
    debounceTimeout = null;
  }

  currentSearchQuery = '';

  // Clear results but keep search active
  useStore.getState().setSearchQuery('');
  useStore.getState().setSearchResults([], 0);

  // Update input
  const input = getElementById<HTMLInputElement>('search-input');
  if (input) {
    input.value = '';
  }

  log.debug('Search text cleared, search mode still active');
}

/**
 * Clear search and deactivate search mode
 */
export function clearSearch(): void {
  // Cancel any pending debounced search
  if (debounceTimeout) {
    clearTimeout(debounceTimeout);
    debounceTimeout = null;
  }

  currentSearchQuery = '';

  // Update store
  useStore.getState().clearSearch();

  // Update input
  const input = getElementById<HTMLInputElement>('search-input');
  if (input) {
    input.value = '';
  }

  // Hide clear button
  const clearBtn = document.querySelector('.search-clear-btn');
  clearBtn?.classList.add('hidden');

  log.debug('Search cleared');
}

/**
 * Focus the search input
 */
export function focusSearchInput(): void {
  const input = getElementById<HTMLInputElement>('search-input');
  input?.focus();
}

/**
 * Escape HTML attribute value
 */
function escapeAttr(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
