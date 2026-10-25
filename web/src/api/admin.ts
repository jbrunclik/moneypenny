/**
 * Admin page and spend status API (S12).
 */
import type { AdminOverview, SpendStatus } from '../types/api';
import { requestWithRetry } from './http';

export const admin = {
  /** Everything the admin page shows (403 for non-admins). */
  async getOverview(): Promise<AdminOverview> {
    return requestWithRetry<AdminOverview>('/api/admin/overview');
  },

  /** The signed-in user's spend today against the warning threshold. */
  async getSpendStatus(): Promise<SpendStatus> {
    return requestWithRetry<SpendStatus>('/api/users/me/spend-status');
  },
};
