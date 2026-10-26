/**
 * A reply bubble left "incomplete" on screen (a stop whose done never came,
 * a recovery that gave up with partial text) carries the reply's id but is
 * not in the store. The merge counted it as rendered and skipped the server's
 * saved version: the partial stayed until a reload even though the full
 * reply was saved.
 */
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Message } from '@/types/api';

const server: { messages: Message[] } = { messages: [] };
vi.mock('@/api/conversations', () => ({
  conversations: {
    get: vi.fn(() =>
      Promise.resolve({
        id: 'c1',
        messages: server.messages,
        message_pagination: { total_count: server.messages.length },
        streaming_message_id: null,
      })
    ),
  },
}));
vi.mock('@/components/messages', () => ({
  addMessageToUI: vi.fn((m: Message, container: HTMLElement) => {
    const el = document.createElement('div');
    el.className = `message ${m.role}`;
    el.dataset.messageId = m.id;
    el.textContent = m.content;
    container.appendChild(el);
  }),
  lockOlderQuizBlocks: vi.fn(),
  updateLatestAssistantMarker: vi.fn(),
}));
vi.mock('@/components/ScrollToBottom', () => ({ showNewMessagesPill: vi.fn() }));
vi.mock('@/sync/SyncManager', () => ({ getSyncManager: () => ({ markConversationRead: vi.fn() }) }));
vi.mock('@/core/conversation', () => ({ markAgentViewedAndRefresh: vi.fn(), reloadCurrentConversation: vi.fn() }));
vi.mock('@/core/stream-resume', () => ({ followRemoteStream: vi.fn() }));
vi.mock('@/utils/programmatic-scroll', () => ({ programmaticScrollToBottom: vi.fn() }));

import { useStore } from '@/state/store';
import { mergeExternalChanges, serverRewroteHistory } from '@/core/remote-merge';
import { reloadCurrentConversation } from '@/core/conversation';

const PAGE = { older_cursor: null, newer_cursor: null, has_older: false, has_newer: false, total_count: 1 };
const user: Message = { id: 'u1', role: 'user', content: 'Question', created_at: '2026-10-10T20:00:00' };
const reply: Message = { id: 'a1', role: 'assistant', content: 'The full saved answer', created_at: '2026-10-10T20:00:01' };

describe('merging over an incomplete reply bubble', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStore.setState({
      currentConversation: { id: 'c1', title: 'T', model: 'm', created_at: '', updated_at: '' } as never,
    });
    useStore.getState().removeActiveRequest('c1');
    useStore.getState().setMessages('c1', [user], PAGE);
    document.body.innerHTML = `<div id="messages">
      <div class="message user" data-message-id="u1">Question</div>
      <div class="message assistant streaming message-incomplete" data-message-id="a1">The full</div>
    </div>`;
    server.messages = [user, reply];
  });

  it("replaces the partial with the server's saved reply", async () => {
    await mergeExternalChanges('c1');
    const bubbles = document.querySelectorAll('#messages [data-message-id="a1"]');
    expect(bubbles).toHaveLength(1);
    expect(bubbles[0]?.textContent).toBe('The full saved answer');
    expect(bubbles[0]?.classList.contains('message-incomplete')).toBe(false);
    expect(useStore.getState().getMessages('c1').map((m) => m.id)).toEqual(['u1', 'a1']);
    expect(reloadCurrentConversation).not.toHaveBeenCalled();
  });
});

describe('serverRewroteHistory', () => {
  const later: Message = { id: 'u2', role: 'user', content: 'Follow-up', created_at: '2026-10-10T20:01:00' };

  it('is false when the server only adds messages', () => {
    expect(serverRewroteHistory([user], [user, reply])).toBe(false);
  });

  it('detects a message deleted elsewhere within the server window', () => {
    expect(serverRewroteHistory([user, reply, later], [user, later])).toBe(true);
  });

  it('ignores messages older than the server window and local-only sends', () => {
    expect(serverRewroteHistory([user, reply, later], [reply, later])).toBe(false);
    const pending: Message = { ...later, id: 'p1', status: 'pending' };
    expect(serverRewroteHistory([user, pending], [user])).toBe(false);
  });

  it('detects content edited elsewhere, but not an empty placeholder', () => {
    expect(serverRewroteHistory([user], [{ ...user, content: 'Edited' }])).toBe(true);
    expect(serverRewroteHistory([{ ...user, content: '' }], [user])).toBe(false);
    expect(serverRewroteHistory([user], [{ ...user, content: '' }])).toBe(false);
  });

  it('treats an empty server window as no change', () => {
    expect(serverRewroteHistory([user], [])).toBe(false);
  });
});

describe('serverRewroteHistory window across timestamp formats', () => {
  // Server messages are local-naive; a message sent from this device keeps
  // its optimistic toISOString() created_at. Pinned to the household timezone
  // (UTC+1 on this date) so text order and instant order differ.
  const originalTz = process.env.TZ;
  beforeAll(() => {
    process.env.TZ = 'Europe/Prague';
  });
  afterAll(() => {
    process.env.TZ = originalTz;
  });

  const windowFirst: Message = { id: 's1', role: 'user', content: 'Q', created_at: '2026-10-26T11:30:00.123456' };
  const windowLast: Message = { id: 's2', role: 'assistant', content: 'A', created_at: '2026-10-26T12:30:00' };
  // A message this device sent, with its toISOString() created_at
  const mine = (at: Date): Message => ({ id: 'mine', role: 'user', content: 'Mine', created_at: at.toISOString() });

  it('detects a "Z" message inside the window that the server no longer has', () => {
    // 12:00 Prague: "2026-10-26T11:00:00.000Z"
    const local = [windowFirst, mine(new Date(2026, 9, 26, 12, 0, 0)), windowLast];
    expect(serverRewroteHistory(local, [windowFirst, windowLast])).toBe(true);
  });

  it('ignores a "Z" message from before the window', () => {
    // 11:15 Prague: "2026-10-26T10:15:00.000Z"
    const local = [mine(new Date(2026, 9, 26, 11, 15, 0)), windowFirst, windowLast];
    expect(serverRewroteHistory(local, [windowFirst, windowLast])).toBe(false);
  });

  it('ignores a "Z" message just before a window that starts within the same second', () => {
    // 11:30:00.100 Prague is before the window's 11:30:00.123456
    const local = [mine(new Date(2026, 9, 26, 11, 30, 0, 100)), windowFirst, windowLast];
    expect(serverRewroteHistory(local, [windowFirst, windowLast])).toBe(false);
  });
});
