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
    // the test DOM has no layout: the arrows scroll the picked result into view
    Element.prototype.scrollIntoView = vi.fn();
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

  it('arrows move through the results and Enter opens the selected one', async () => {
    const { initSearchInput } = await import('@/components/SearchInput');
    document.body.innerHTML = `
      <div id="search-container"></div>
      <div id="conversations-list">
        <div class="search-result-item" data-result-index="0"></div>
        <div class="search-result-item" data-result-index="1"></div>
        <div class="search-result-item" data-result-index="2"></div>
      </div>`;
    initSearchInput();
    const input = document.getElementById('search-input') as HTMLInputElement;
    const items = [...document.querySelectorAll<HTMLElement>('.search-result-item')];
    const opened: string[] = [];
    for (const item of items) item.addEventListener('click', () => opened.push(item.dataset.resultIndex ?? ''));
    const key = (k: string): KeyboardEvent => {
      const e = new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true });
      input.dispatchEvent(e);
      return e;
    };
    const selected = (): number => items.findIndex((i) => i.classList.contains('keyboard-selected'));

    expect(key('ArrowDown').defaultPrevented).toBe(true);
    expect(selected()).toBe(0);
    key('ArrowDown');
    key('ArrowDown');
    key('ArrowDown'); // stays on the last
    expect(selected()).toBe(2);
    key('ArrowUp');
    expect(selected()).toBe(1);
    expect(items[1]?.getAttribute('aria-selected')).toBe('true');

    key('Enter');
    expect(opened).toEqual(['1']);
  });

  it('Enter with nothing selected opens the first result', async () => {
    const { initSearchInput } = await import('@/components/SearchInput');
    document.body.innerHTML = `
      <div id="search-container"></div>
      <div id="conversations-list">
        <div class="search-result-item" data-result-index="0"></div>
      </div>`;
    initSearchInput();
    const input = document.getElementById('search-input') as HTMLInputElement;
    const first = document.querySelector<HTMLElement>('.search-result-item');
    let opened = false;
    first?.addEventListener('click', () => {
      opened = true;
    });

    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));

    expect(opened).toBe(true);
  });
});
