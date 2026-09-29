/**
 * Conversation search API.
 */
import { type SearchResponse } from '../types/api';
import { requestWithRetry } from './http';

// Search endpoints
export const search = {
  /**
   * Search across all conversations and messages.
   *
   * @param query - Search query string
   * @param limit - Maximum results to return (default: 20, max: 50)
   * @param offset - Number of results to skip for pagination
   * @returns Search results with conversation info and message snippets
   */
  async query(query: string, limit: number = 20, offset: number = 0): Promise<SearchResponse> {
    const params = new URLSearchParams({
      q: query,
      limit: String(limit),
      offset: String(offset),
    });
    return requestWithRetry<SearchResponse>(`/api/search?${params}`);
  },
};
