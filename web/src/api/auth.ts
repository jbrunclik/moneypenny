/**
 * Auth API: Google sign-in, current user, token refresh.
 */
import { type AuthResponse, type User } from '../types/api';
import { request, requestWithRetry } from './http';

// Auth endpoints
export const auth = {
  async getClientId(): Promise<string> {
    const data = await requestWithRetry<{ client_id: string }>('/auth/client-id');
    return data.client_id;
  },

  async googleLogin(credential: string): Promise<AuthResponse> {
    // POST - no retry (not idempotent)
    return request<AuthResponse>('/auth/google', {
      method: 'POST',
      body: JSON.stringify({ credential }),
    });
  },

  async me(): Promise<User> {
    const data = await requestWithRetry<{ user: User }>('/auth/me');
    return data.user;
  },

  async refreshToken(): Promise<string> {
    // POST - no retry (not idempotent, creates new token)
    const data = await request<{ token: string }>('/auth/refresh', {
      method: 'POST',
    });
    return data.token;
  },
};
