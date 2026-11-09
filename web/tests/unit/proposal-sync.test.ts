import { beforeEach, describe, expect, it } from 'vitest';
import { hasOpenProposals } from '../../src/core/proposal-sync';
import { useStore } from '../../src/state/store';
import type { Message, Proposal } from '../../src/types/api';

const PAGE = { older_cursor: null, newer_cursor: null, has_older: false, has_newer: false, total_count: 2 };

function card(state: Proposal['state']): Proposal {
  return { id: `p-${state}`, kind: 'schedule_item', summary: 's', details: [], options: [], state, chosen: null, result: null };
}

function reply(id: string, proposals: Proposal[] | null): Message {
  return { id, role: 'assistant', content: 'x', created_at: '2026-11-09T10:00:00Z', proposals } as Message;
}

describe('hasOpenProposals', () => {
  beforeEach(() => {
    useStore.getState().setMessages('c1', [], PAGE);
  });

  it('is true while a card awaits an answer', () => {
    useStore.getState().setMessages('c1', [reply('m1', [card('approved')]), reply('m2', [card('pending')])], PAGE);
    expect(hasOpenProposals('c1')).toBe(true);
  });

  it('is false when every card is resolved or there are none', () => {
    useStore.getState().setMessages('c1', [reply('m1', [card('expired')]), reply('m2', null)], PAGE);
    expect(hasOpenProposals('c1')).toBe(false);
  });
});
