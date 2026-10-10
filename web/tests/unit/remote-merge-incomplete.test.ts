/**
 * A reply bubble left "incomplete" on screen (a stop whose done never came,
 * a recovery that gave up with partial text) carries the reply's id but is
 * not in the store. The merge counted it as rendered and skipped the server's
 * saved version: the partial stayed until a reload even though the full
 * reply was saved.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
vi.mock('@/core/conversation', () => ({ isTempConversation: () => false, markAgentViewedAndRefresh: vi.fn() }));
vi.mock('@/core/stream-resume', () => ({ followRemoteStream: vi.fn() }));
vi.mock('@/core/sync-banner', () => ({ reloadCurrentConversation: vi.fn() }));
vi.mock('@/utils/thumbnails', () => ({ programmaticScrollToBottom: vi.fn() }));

import { useStore } from '@/state/store';
import { mergeExternalChanges } from '@/core/remote-merge';
import { reloadCurrentConversation } from '@/core/sync-banner';

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
    expect(bubbles[0].textContent).toBe('The full saved answer');
    expect(bubbles[0].classList.contains('message-incomplete')).toBe(false);
    expect(useStore.getState().getMessages('c1').map((m) => m.id)).toEqual(['u1', 'a1']);
    expect(reloadCurrentConversation).not.toHaveBeenCalled();
  });
});
