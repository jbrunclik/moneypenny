/**
 * Search results are an HTML string: the ids and texts a result carries must
 * stay inside their attributes and elements (F3).
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { useStore } from '@/state/store';
import { renderSearchResults } from '@/components/SearchResults';
import type { SearchResult } from '@/types/api';

const QUOTED = 'c1" data-evil="1';

describe('renderSearchResults', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="conversations-list"></div>';
  });

  it('keeps ids with quotes inside their attributes', () => {
    const result: SearchResult = {
      conversation_id: QUOTED,
      conversation_title: '<img src=x onerror="alert(1)">',
      message_id: `m${QUOTED}`,
      message_snippet: 'a [[HIGHLIGHT]]<b>hit</b>[[/HIGHLIGHT]]',
      match_type: 'message',
      created_at: null,
      match_mode: 'all',
    };
    useStore.setState({
      isSearchActive: true,
      isSearching: false,
      searchQuery: 'hit',
      searchResults: [result],
      searchTotal: 1,
      viewedSearchResultId: null,
    });

    renderSearchResults();

    expect(document.querySelector('[data-evil], img, b')).toBeNull();
    const item = document.querySelector<HTMLElement>('.search-result-item');
    expect(item?.dataset.convId).toBe(QUOTED);
    expect(item?.dataset.messageId).toBe(`m${QUOTED}`);
    expect(document.querySelector('mark')?.textContent).toBe('<b>hit</b>');
  });

  it('labels any-word fallback hits as partial matches', () => {
    const base: SearchResult = {
      conversation_id: 'c1',
      conversation_title: 'Škola',
      message_id: 'm1',
      message_snippet: '[[HIGHLIGHT]]olympiády[[/HIGHLIGHT]]',
      match_type: 'message',
      created_at: null,
      match_mode: 'all',
    };
    useStore.setState({
      isSearchActive: true,
      isSearching: false,
      searchQuery: 'olympiáda',
      searchResults: [
        { ...base, match_mode: 'all' },
        { ...base, conversation_id: 'c2', message_id: 'm2', match_mode: 'any' },
      ],
      searchTotal: 2,
      viewedSearchResultId: null,
    });

    renderSearchResults();

    const labels = [...document.querySelectorAll('.search-result-type')].map((el) => el.textContent);
    expect(labels).toEqual(['Message', 'Partial match']);
  });
});
