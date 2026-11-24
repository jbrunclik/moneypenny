/**
 * Saved documents API (document memory).
 */
import { API_DEFAULT_TIMEOUT_MS } from '../config';
import { type DocumentsResponse } from '../types/api';
import { ApiError, fetchWithConnectTimeout, getToken, request, requestWithRetry } from './http';

export const documents = {
  /** Live documents, recently deleted ones and the caps. */
  async list(): Promise<DocumentsResponse> {
    return requestWithRetry<DocumentsResponse>('/api/documents');
  },

  async delete(documentId: string): Promise<void> {
    // DELETE is idempotent, safe to retry
    await request<{ status: string }>(`/api/documents/${documentId}`, {
      method: 'DELETE',
      retry: true,
    });
  },

  async restore(documentId: string): Promise<void> {
    await request<{ status: string }>(`/api/documents/${documentId}/restore`, {
      method: 'POST',
    });
  },

  /** The document's file (JWT is header-only, so no plain link). */
  async fetchFile(documentId: string): Promise<Blob> {
    const token = getToken();
    // Connect timeout only - large file bodies may legitimately take longer
    const response = await fetchWithConnectTimeout(
      `/api/documents/${documentId}/file`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      API_DEFAULT_TIMEOUT_MS
    );
    if (!response.ok) {
      throw new ApiError('Failed to fetch document', response.status);
    }
    return response.blob();
  },
};
