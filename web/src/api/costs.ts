/**
 * Cost tracking API.
 */
import {
  type CostHistoryResponse,
  type ConversationCostResponse,
  type ConversationCompactionResponse,
  type MessageCostResponse,
  type MonthlyCostResponse,
} from '../types/api';
import { requestWithRetry } from './http';

// Cost tracking endpoints
export const costs = {
  async getConversationCost(conversationId: string): Promise<ConversationCostResponse> {
    return requestWithRetry<ConversationCostResponse>(`/api/conversations/${conversationId}/cost`);
  },

  async getConversationCompaction(conversationId: string): Promise<ConversationCompactionResponse> {
    return requestWithRetry<ConversationCompactionResponse>(
      `/api/conversations/${conversationId}/compaction`
    );
  },

  async getMonthlyCost(year?: number, month?: number): Promise<MonthlyCostResponse> {
    const params = new URLSearchParams();
    if (year) params.set('year', year.toString());
    if (month) params.set('month', month.toString());
    const query = params.toString();
    return requestWithRetry<MonthlyCostResponse>(`/api/users/me/costs/monthly${query ? `?${query}` : ''}`);
  },

  async getCostHistory(limit?: number): Promise<CostHistoryResponse> {
    const params = new URLSearchParams();
    if (limit) params.set('limit', limit.toString());
    const query = params.toString();
    return requestWithRetry<CostHistoryResponse>(`/api/users/me/costs/history${query ? `?${query}` : ''}`);
  },

  async getMessageCost(messageId: string): Promise<MessageCostResponse> {
    return requestWithRetry<MessageCostResponse>(`/api/messages/${messageId}/cost`);
  },
};
