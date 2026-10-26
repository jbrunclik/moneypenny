/**
 * Search results in the sidebar: while search is active the conversation
 * list shows a spinner, a "type to search" hint, a "no results" line or the
 * results (count, title, highlighted snippet for message matches, match
 * type, date, the viewed one marked active). Server text is escaped before
 * the [[HIGHLIGHT]] markers become <mark>. The subscription re-renders on
 * search state changes, restores the conversation list when search closes,
 * and reports result clicks until cleaned up.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { SearchResult } from '@/types/api';

const sidebar = vi.hoisted(() => ({ renderConversationsList: vi.fn() }));
vi.mock('@/components/Sidebar', () => sidebar);

import { useStore } from '@/state/store';
import { renderSearchResults, subscribeToSearchChanges, isSearchResultsVisible } from '@/components/SearchResults';

function result(overrides: Partial<SearchResult> = {}): SearchResult {
  return {
    conversation_id: 'c1',
    conversation_title: 'Trip planning',
    message_id: 'm1',
    message_snippet: 'book the [[HIGHLIGHT]]train[[/HIGHLIGHT]] early',
    match_type: 'message',
    created_at: null,
    ...overrides,
  };
}

const list = (): HTMLElement => document.getElementById('conversations-list') as HTMLElement;
const items = (): HTMLElement[] => Array.from(list().querySelectorAll<HTMLElement>('.search-result-item'));

function showResults(results: SearchResult[], query = 'train', total = results.length): void {
  const store = useStore.getState();
  store.activateSearch();
  store.setSearchQuery(query);
  store.setSearchResults(results, total);
}

describe('SearchResults', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStore.setState(useStore.getInitialState(), true);
    document.body.innerHTML = '<div id="conversations-list"><div class="conversation-item">old</div></div>';
  });

  describe('renderSearchResults', () => {
    it('leaves the conversation list alone while search is closed', () => {
      renderSearchResults();
      expect(isSearchResultsVisible()).toBe(false);
      expect(list().textContent).toBe('old');
    });

    it('shows a spinner while searching', () => {
      useStore.getState().activateSearch();
      useStore.getState().setSearchQuery('train');
      useStore.getState().setIsSearching(true);
      renderSearchResults();
      expect(list().querySelector('.search-loading')?.textContent).toContain('Searching...');
    });

    it('shows a hint for an empty or blank query', () => {
      useStore.getState().activateSearch();
      useStore.getState().setSearchQuery('   ');
      renderSearchResults();
      expect(list().querySelector('.search-empty')?.textContent?.trim()).toBe('Type to search conversations');
    });

    it('says nothing was found, with the query escaped', () => {
      showResults([], '<b>x</b>');
      renderSearchResults();
      expect(list().querySelector('.search-empty')?.textContent?.trim()).toBe('No results found for "<b>x</b>"');
      expect(list().querySelector('b')).toBeNull();
    });

    it('counts the results, singular and plural, from the server total', () => {
      showResults([result()], 'train', 1);
      renderSearchResults();
      expect(list().querySelector('.search-results-count')?.textContent).toBe('1 result');

      showResults([result(), result({ conversation_id: 'c2' })], 'train', 37);
      renderSearchResults();
      expect(list().querySelector('.search-results-count')?.textContent).toBe('37 results');
      expect(items()).toHaveLength(2);
    });

    it('highlights the matched words in a message snippet', () => {
      showResults([result()]);
      renderSearchResults();
      const snippet = list().querySelector('.search-result-snippet');
      expect(snippet?.querySelector('mark')?.textContent).toBe('train');
      expect(snippet?.textContent).toBe('book the train early');
      expect(list().querySelector('.search-result-type')?.textContent).toBe('Message');
    });

    it('escapes the title and the snippet before adding highlights', () => {
      showResults([
        result({
          conversation_title: '<img src=x onerror=alert(1)>',
          message_snippet: '<script>x</script> [[HIGHLIGHT]]<i>hit</i>[[/HIGHLIGHT]]',
        }),
      ]);
      renderSearchResults();
      expect(list().querySelector('img, script, i')).toBeNull();
      expect(list().querySelector('.search-result-title')?.textContent).toBe('<img src=x onerror=alert(1)>');
      expect(list().querySelector('mark')?.textContent).toBe('<i>hit</i>');
    });

    it('shows a title match without a snippet or message id', () => {
      showResults([result({ match_type: 'conversation', message_id: null, message_snippet: null })]);
      renderSearchResults();
      const [item] = items();
      expect(item?.querySelector('.search-result-snippet')).toBeNull();
      expect(item?.querySelector('.search-result-type')?.textContent).toBe('Title');
      expect(item?.hasAttribute('data-message-id')).toBe(false);
      expect(item?.dataset.convId).toBe('c1');
    });

    it('shows a date only when the result has one', () => {
      showResults([result(), result({ conversation_id: 'c2', created_at: new Date().toISOString() })]);
      renderSearchResults();
      const [noDate, withDate] = items();
      expect(noDate?.querySelector('.search-result-date')).toBeNull();
      expect(withDate?.querySelector('.search-result-date')?.textContent).not.toBe('');
    });

    it('marks the viewed result active by its position', () => {
      // The same message can appear twice; the index tells them apart
      showResults([result(), result()]);
      useStore.getState().setViewedSearchResult(1);
      renderSearchResults();
      expect(items().map((i) => i.classList.contains('active'))).toEqual([false, true]);
    });
  });

  describe('subscribeToSearchChanges', () => {
    it('re-renders when the search state changes', () => {
      const cleanup = subscribeToSearchChanges(vi.fn());
      showResults([result()]);
      expect(items()).toHaveLength(1);

      useStore.getState().setViewedSearchResult(0);
      expect(items()[0]?.classList.contains('active')).toBe(true);
      cleanup();
    });

    it('restores the conversation list when search closes', () => {
      const cleanup = subscribeToSearchChanges(vi.fn());
      showResults([result()]);
      expect(sidebar.renderConversationsList).not.toHaveBeenCalled();

      useStore.getState().deactivateSearch();
      expect(sidebar.renderConversationsList).toHaveBeenCalledTimes(1);
      cleanup();
    });

    it('reports a clicked result with its conversation, message and position', () => {
      const onClick = vi.fn();
      const cleanup = subscribeToSearchChanges(onClick);
      showResults([result(), result({ conversation_id: 'c2', message_id: null, match_type: 'conversation' })]);

      items()[0]?.querySelector('mark')?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      items()[1]?.click();

      expect(onClick).toHaveBeenNthCalledWith(1, 'c1', 'm1', 0);
      expect(onClick).toHaveBeenNthCalledWith(2, 'c2', null, 1);
      cleanup();
    });

    it('ignores clicks outside a result', () => {
      const onClick = vi.fn();
      const cleanup = subscribeToSearchChanges(onClick);
      showResults([result()]);
      (list().querySelector('.search-results-count') as HTMLElement).click();
      expect(onClick).not.toHaveBeenCalled();
      cleanup();
    });

    it('stops rendering and reporting clicks after cleanup', () => {
      const onClick = vi.fn();
      const cleanup = subscribeToSearchChanges(onClick);
      showResults([result()]);
      cleanup();

      useStore.getState().setSearchResults([result(), result()], 2);
      expect(items()).toHaveLength(1);
      items()[0]?.click();
      expect(onClick).not.toHaveBeenCalled();
    });
  });
});
