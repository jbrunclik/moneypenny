/**
 * Proposal cards: approve (one of the card's options), decline, or re-offer a
 * started deep-research card. The server applies the stored option, so what
 * runs is what the card showed (docs/features/proposals.md).
 */
import type { Proposal, ReopenReason } from '../types/api';
import { request } from './http';

export const proposals = {
  /** Approve a card's option (0 when it has one); returns the outcome. */
  async approve(proposalId: string, choice = 0): Promise<Proposal> {
    return request<Proposal>(`/api/proposals/${proposalId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ choice }),
    });
  },

  /** Re-offer a started deep-research card instead of re-running its turn:
   *  the Start message and what followed are deleted (409 while a turn runs). */
  async reopen(proposalId: string, messageId: string, reason: ReopenReason): Promise<Proposal> {
    return request<Proposal>(`/api/proposals/${proposalId}/reopen`, {
      method: 'POST',
      body: JSON.stringify({ message_id: messageId, reason }),
    });
  },

  /** Decline a card ("Not now"). */
  async decline(proposalId: string): Promise<Proposal> {
    return request<Proposal>(`/api/proposals/${proposalId}/decline`, { method: 'POST' });
  },
};
