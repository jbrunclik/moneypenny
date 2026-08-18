/**
 * Unit tests for New Chat dedupe: reuse an existing empty conversation
 * instead of piling up untitled ones.
 */
import { describe, it, expect } from 'vitest';
import { findReusableEmptyConversation } from '@/core/conversation';
import { DEFAULT_CONVERSATION_TITLE } from '@/types/api';
import type { Conversation } from '@/types/api';

function conv(over: Partial<Conversation>): Conversation {
  return {
    id: 'x',
    title: DEFAULT_CONVERSATION_TITLE,
    model: 'm',
    created_at: '2026-08-18T00:00:00Z',
    updated_at: '2026-08-18T00:00:00Z',
    messageCount: 0,
    ...over,
  };
}

describe('findReusableEmptyConversation', () => {
  it('returns an empty default-titled conversation', () => {
    expect(findReusableEmptyConversation([conv({ id: 'a' })])?.id).toBe('a');
  });

  it('treats undefined messageCount with empty messages array as empty', () => {
    expect(
      findReusableEmptyConversation([conv({ id: 'b', messageCount: undefined, messages: [] })])?.id,
    ).toBe('b');
  });

  it('skips titled, non-empty, archived and agent conversations', () => {
    expect(
      findReusableEmptyConversation([
        conv({ title: 'Named' }),
        conv({ messageCount: 3 }),
        conv({ archived: true }),
        conv({ is_agent: true }),
      ]),
    ).toBeNull();
  });

  it('returns null for an empty list', () => {
    expect(findReusableEmptyConversation([])).toBeNull();
  });
});
