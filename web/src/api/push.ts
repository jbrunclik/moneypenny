/**
 * Web Push API.
 */
import { request, requestWithRetry } from './http';

// Web Push endpoints
export const push = {
  async getVapidPublicKey(): Promise<{ enabled: boolean; public_key: string | null }> {
    return requestWithRetry<{ enabled: boolean; public_key: string | null }>('/api/push/vapid-public-key');
  },

  async subscribe(subscription: { endpoint: string; keys: { p256dh: string; auth: string } }): Promise<{ success: boolean; subscription_id: string }> {
    return request<{ success: boolean; subscription_id: string }>('/api/push/subscriptions', {
      method: 'POST',
      body: JSON.stringify(subscription),
    });
  },

  async unsubscribe(endpoint: string): Promise<void> {
    await request<{ status: string }>('/api/push/subscriptions', {
      method: 'DELETE',
      body: JSON.stringify({ endpoint }),
    });
  },

  async sendTest(): Promise<{ status: string }> {
    return request<{ status: string }>('/api/push/test', { method: 'POST' });
  },
};
