/**
 * Memories API.
 */
import { type MemoriesResponse, type Memory } from '../types/api';
import { request, requestWithRetry } from './http';

// Memory endpoints
export const memories = {
  async list(): Promise<Memory[]> {
    const data = await requestWithRetry<MemoriesResponse>('/api/memories');
    return data.memories;
  },

  /**
   * List memories together with the server-side cap, so the UI does not need
   * its own copy of the limit.
   */
  async listWithLimit(): Promise<{ memories: Memory[]; limit: number }> {
    const data = await requestWithRetry<MemoriesResponse>('/api/memories');
    return { memories: data.memories, limit: data.limit ?? 0 };
  },

  /**
   * Recently deleted memories, still restorable until the nightly purge.
   */
  async listDeleted(): Promise<Memory[]> {
    const data = await requestWithRetry<MemoriesResponse>('/api/memories/deleted');
    return data.memories;
  },

  async delete(memoryId: string): Promise<void> {
    // DELETE is idempotent, safe to retry
    await request<{ status: string }>(`/api/memories/${memoryId}`, {
      method: 'DELETE',
      retry: true,
    });
  },

  async restore(memoryId: string): Promise<void> {
    await request<{ status: string }>(`/api/memories/${memoryId}/restore`, {
      method: 'POST',
      retry: true,
    });
  },

  /**
   * Protect a memory so the LLM and the defrag job cannot delete it.
   */
  async setProtected(memoryId: string, isProtected: boolean): Promise<void> {
    await request<{ status: string }>(`/api/memories/${memoryId}/protection`, {
      method: 'PATCH',
      body: JSON.stringify({ protected: isProtected }),
      retry: true,
    });
  },
};
