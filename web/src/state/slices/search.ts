import type { SearchResult } from '../../types/api';
import type { AppSlice } from '../store';

export interface SearchData {
  searchQuery: string;
  searchResults: SearchResult[];
  searchTotal: number;
  isSearching: boolean;
  isSearchActive: boolean; // True when search UI is shown (even with empty query)
  viewedSearchResultId: number | null; // Index of currently viewed search result (unique per result list)
}

export interface SearchSlice extends SearchData {
  setSearchQuery: (query: string) => void;
  setSearchResults: (results: SearchResult[], total: number) => void;
  setIsSearching: (searching: boolean) => void;
  activateSearch: () => void;
  deactivateSearch: () => void;
  clearSearch: () => void;
  setViewedSearchResult: (resultIndex: number | null) => void;
}

/** Initial search state; also what logout resets to. */
export function initialSearchData(): SearchData {
  return {
    searchQuery: '',
    searchResults: [],
    searchTotal: 0,
    isSearching: false,
    isSearchActive: false,
    viewedSearchResultId: null,
  };
}

export const createSearchSlice: AppSlice<SearchSlice> = (set) => ({
  ...initialSearchData(),

  setSearchQuery: (searchQuery) => set({ searchQuery }),
  setSearchResults: (searchResults, searchTotal) => set({ searchResults, searchTotal }),
  setIsSearching: (isSearching) => set({ isSearching }),
  activateSearch: () => set({ isSearchActive: true }),
  deactivateSearch: () =>
    set({ isSearchActive: false, searchQuery: '', searchResults: [], searchTotal: 0, viewedSearchResultId: null }),
  clearSearch: () =>
    set({ searchQuery: '', searchResults: [], searchTotal: 0, isSearching: false, isSearchActive: false, viewedSearchResultId: null }),
  setViewedSearchResult: (viewedSearchResultId) => set({ viewedSearchResultId }),
});
