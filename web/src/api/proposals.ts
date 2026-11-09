/**
 * Proposal cards: approve (one of the card's options) or decline. The server
 * applies the stored option, so what runs is what the card showed
 * (docs/features/proposals.md).
 */
import type { Proposal } from '../types/api';
import { request } from './http';

export const proposals = {
  /** Approve a card's option (0 when it has one); returns the outcome. */
  async approve(proposalId: string, choice = 0): Promise<Proposal> {
    return request<Proposal>(`/api/proposals/${proposalId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ choice }),
    });
  },

  /** Decline a card ("Not now"). */
  async decline(proposalId: string): Promise<Proposal> {
    return request<Proposal>(`/api/proposals/${proposalId}/decline`, { method: 'POST' });
  },
};
