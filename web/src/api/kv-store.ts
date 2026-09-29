/**
 * Key/value store API.
 */
import { type KVKeysResponse, type KVNamespacesResponse, type KVValueResponse } from '../types/api';
import { request, requestWithRetry } from './http';

// KV Store endpoints
export const kvStore = {
  async getNamespaces(): Promise<KVNamespacesResponse> {
    return requestWithRetry<KVNamespacesResponse>('/api/kv');
  },

  async getKeys(namespace: string): Promise<KVKeysResponse> {
    return requestWithRetry<KVKeysResponse>(`/api/kv/${encodeURIComponent(namespace)}`);
  },

  async getValue(namespace: string, key: string): Promise<KVValueResponse> {
    return requestWithRetry<KVValueResponse>(`/api/kv/${encodeURIComponent(namespace)}/${encodeURIComponent(key)}`);
  },

  async setValue(namespace: string, key: string, value: string): Promise<KVValueResponse> {
    return request<KVValueResponse>(`/api/kv/${encodeURIComponent(namespace)}/${encodeURIComponent(key)}`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    });
  },

  async deleteKey(namespace: string, key: string): Promise<void> {
    await request<{ status: string }>(`/api/kv/${encodeURIComponent(namespace)}/${encodeURIComponent(key)}`, {
      method: 'DELETE',
      retry: true,
    });
  },

  async clearNamespace(namespace: string): Promise<void> {
    await request<{ status: string }>(`/api/kv/${encodeURIComponent(namespace)}`, {
      method: 'DELETE',
    });
  },
};
