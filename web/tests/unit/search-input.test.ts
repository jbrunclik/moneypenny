/**
 * Search input: clearing the text while a search is in flight must not leave
 * the results panel stuck on "Searching...".
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

let resolveQuery: (value: { results: never[]; total: number }) => void = () => undefined;
vi.mock('@/api/search', () => ({
  search: {
    query: vi.fn(
      () =>
        new Promise((resolve) => {
          resolveQuery = resolve;
        })
    ),
  },
}));

describe('Search input', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    document.body.innerHTML = '<div id="search-container"></div>';
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('clearing the text mid-search ends the loading state', async () => {
    const { initSearchInput } = await import('@/components/SearchInput');
    const { useStore } = await import('@/state/store');
    const { SEARCH_DEBOUNCE_MS } = await import('@/config');
    initSearchInput();

    const input = document.getElementById('search-input') as HTMLInputElement;
    input.focus();
    input.value = 'test query';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await vi.advanceTimersByTimeAsync(SEARCH_DEBOUNCE_MS + 10);
    expect(useStore.getState().isSearching).toBe(true); // request in flight

    // First click on the clear button: clear the text, stay in search mode
    (document.querySelector('.search-clear-btn') as HTMLButtonElement).click();
    // The stale request finishes after the clear
    resolveQuery({ results: [], total: 0 });
    await vi.advanceTimersByTimeAsync(0);

    const state = useStore.getState();
    expect(state.isSearchActive).toBe(true);
    expect(state.searchQuery).toBe('');
    expect(state.isSearching).toBe(false);
  });
});
