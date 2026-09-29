/**
 * User settings API.
 */
import { type UserSettings } from '../types/api';
import { request, requestWithRetry } from './http';

// Settings endpoints
export const settings = {
  async get(): Promise<UserSettings> {
    return requestWithRetry<UserSettings>('/api/users/me/settings');
  },

  async update(data: Partial<UserSettings>): Promise<void> {
    // PATCH is idempotent (same update = same result), safe to retry
    await request<{ status: string }>('/api/users/me/settings', {
      method: 'PATCH',
      body: JSON.stringify(data),
      retry: true,
    });
  },
};
