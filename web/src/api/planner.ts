/**
 * Planner API.
 */
import {
  type PlannerConversation,
  type PlannerDashboard,
  type PlannerResetResponse,
  type PlannerSyncResponse,
} from '../types/api';
import { request, requestWithRetry } from './http';

// Planner endpoints
export const planner = {
  /**
   * Get the planner dashboard with events and tasks for the next 7 days.
   * Includes overdue tasks and integration connection status.
   * @param forceRefresh If true, bypasses cache and fetches fresh data
   */
  async getDashboard(forceRefresh: boolean = false): Promise<PlannerDashboard> {
    const url = forceRefresh ? '/api/planner?force_refresh=true' : '/api/planner';
    return requestWithRetry<PlannerDashboard>(url);
  },

  /**
   * Get or create the user's planner conversation.
   * If a reset is due (after 4am), messages will be cleared automatically.
   * @returns The planner conversation with messages and was_reset flag
   */
  async getConversation(): Promise<PlannerConversation> {
    return requestWithRetry<PlannerConversation>('/api/planner/conversation');
  },

  /**
   * Reset the planner conversation (clear all messages).
   * Physically deletes messages but preserves cost data for accuracy.
   */
  async reset(): Promise<PlannerResetResponse> {
    return request<PlannerResetResponse>('/api/planner/reset', {
      method: 'POST',
    });
  },

  /**
   * Get planner conversation state for real-time synchronization.
   * Returns conversation metadata (message count, last reset) to detect
   * external updates, resets, or deletion in other tabs/devices.
   */
  async sync(): Promise<PlannerSyncResponse> {
    return requestWithRetry<PlannerSyncResponse>('/api/planner/sync');
  },
};
