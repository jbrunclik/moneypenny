import { beforeEach, describe, expect, it } from 'vitest';
import { useStore } from '@/state/store';
import { findActionReply } from '@/core/message-links';
import type { Message } from '@/types/api';

const PAGE = { older_cursor: null, newer_cursor: null, has_older: false, has_newer: false, total_count: 0 };
const T = '2026-10-03T08:00:00';

function look(id: string, source: string, claim: number): Message {
  return {
    id, role: 'user', content: 'Look up and verify: x', created_at: T,
    action: { type: 'verify_claim', source_message_id: source, claim_index: claim, quote: 'x' },
  };
}
const answer = (id: string): Message => ({ id, role: 'assistant', content: 'a', created_at: T });

describe('findActionReply', () => {
  beforeEach(() => useStore.getState().setMessages('c1', [], PAGE));

  it('finds the reply after the action for that claim', () => {
    useStore.getState().setMessages('c1', [answer('a1'), look('u1', 'a1', 2), answer('r1')], PAGE);
    expect(findActionReply('c1', 'a1', 2)).toBe('r1');
  });

  it('is null before the reply arrives, or for another claim', () => {
    useStore.getState().setMessages('c1', [answer('a1'), look('u1', 'a1', 2)], PAGE);
    expect(findActionReply('c1', 'a1', 2)).toBeNull();
    useStore.getState().setMessages('c1', [answer('a1'), look('u1', 'a1', 2), answer('r1')], PAGE);
    expect(findActionReply('c1', 'a1', 1)).toBeNull();
  });

  it('the latest look-up wins', () => {
    useStore.getState().setMessages(
      'c1', [answer('a1'), look('u1', 'a1', 0), answer('r1'), look('u2', 'a1', 0), answer('r2')], PAGE
    );
    expect(findActionReply('c1', 'a1', 0)).toBe('r2');
  });

  it('finds the report of a started offer', () => {
    const start: Message = {
      id: 'u1', role: 'user', content: 'Start deep research', created_at: T,
      action: { type: 'deep_research', offer_message_id: 'o1', items: 3, minutes: 5 },
    };
    useStore.getState().setMessages('c1', [answer('o1'), start, answer('rep')], PAGE);
    expect(findActionReply('c1', 'o1')).toBe('rep');
  });
});
