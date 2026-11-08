/**
 * Scheduled items set from chat: a chat's items (header chip) and cancel /
 * pause / resume / run. The Command Center's job list comes from api/jobs.ts.
 */
import type { ConversationSchedulesResponse, ScheduledItem } from '../types/api';
import { request, requestWithRetry } from './http';

export const schedules = {
  /** The chat's live items, soonest first. */
  async forConversation(conversationId: string): Promise<ConversationSchedulesResponse> {
    return requestWithRetry<ConversationSchedulesResponse>(
      `/api/conversations/${conversationId}/schedules`,
    );
  },

  /** Cancel an item. */
  async remove(itemId: string): Promise<void> {
    await request<null>(`/api/schedules/${itemId}`, { method: 'DELETE' });
  },

  /** Pause a watcher or recurring check. */
  async pause(itemId: string): Promise<ScheduledItem> {
    return request<ScheduledItem>(`/api/schedules/${itemId}/pause`, { method: 'POST' });
  },

  /** Resume a paused watcher or recurring check. */
  async resume(itemId: string): Promise<ScheduledItem> {
    return request<ScheduledItem>(`/api/schedules/${itemId}/resume`, { method: 'POST' });
  },

  /** Run a standing job now; the status is the run's outcome. */
  async run(itemId: string): Promise<{ status: string }> {
    return request<{ status: string }>(`/api/schedules/${itemId}/run`, { method: 'POST' });
  },
};
