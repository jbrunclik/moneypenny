/**
 * The background memory review labels a reply already on screen. The merge
 * patches that label in place: a changed memory_note is not an edit, so the
 * reply is neither re-rendered nor replaced.
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
vi.mock('@/components/messages', async () => ({
  addMessageToUI: vi.fn(),
  lockOlderQuizBlocks: vi.fn(),
  updateLatestAssistantMarker: vi.fn(),
  // The real patcher: the DOM it writes is what this file checks
  setMemoryNote: (await vi.importActual<typeof import('@/components/messages/memory-note')>(
    '@/components/messages/memory-note'
  )).setMemoryNote,
}));
vi.mock('@/components/ScrollToBottom', () => ({ showNewMessagesPill: vi.fn() }));
vi.mock('@/sync/SyncManager', () => ({ getSyncManager: () => ({ markConversationRead: vi.fn() }) }));
vi.mock('@/core/conversation', () => ({ markAgentViewedAndRefresh: vi.fn(), reloadCurrentConversation: vi.fn() }));
vi.mock('@/core/stream-resume', () => ({ followRemoteStream: vi.fn() }));
vi.mock('@/utils/programmatic-scroll', () => ({ programmaticScrollToBottom: vi.fn() }));

import { useStore } from '@/state/store';
import { mergeExternalChanges } from '@/core/remote-merge';
import { reloadCurrentConversation } from '@/core/conversation';

const PAGE = { older_cursor: null, newer_cursor: null, has_older: false, has_newer: false, total_count: 2 };
const user: Message = { id: 'u1', role: 'user', content: 'Ema has ballet on Tuesdays', created_at: '2026-11-08T12:00:00' };
const reply: Message = { id: 'a1', role: 'assistant', content: 'Noted!', created_at: '2026-11-08T12:00:01' };

function noteText(): string | null | undefined {
  return document.querySelector('[data-message-id="a1"] .message-memory-note-text')?.textContent;
}

describe('memory note merge', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStore.setState({
      currentConversation: { id: 'c1', title: 'T', model: 'm', created_at: '', updated_at: '' } as never,
    });
    useStore.getState().removeActiveRequest('c1');
    useStore.getState().setMessages('c1', [user, reply], PAGE);
    document.body.innerHTML = `<div id="messages">
      <div class="message user" data-message-id="u1"><div class="message-content-wrapper">Ema</div></div>
      <div class="message assistant" data-message-id="a1"><div class="message-content-wrapper"><div class="message-content">Noted!</div></div></div>
    </div>`;
  });

  it('patches a new memory note into a rendered reply without re-rendering', async () => {
    const before = document.querySelector('[data-message-id="a1"]');
    server.messages = [user, { ...reply, memory_note: 'Ema - ballet on Tuesdays' }];

    await mergeExternalChanges('c1');

    expect(document.querySelector('[data-message-id="a1"]')).toBe(before);
    expect(noteText()).toBe('Memory updated: Ema - ballet on Tuesdays');
    expect(useStore.getState().getMessages('c1')[1]?.memory_note).toBe('Ema - ballet on Tuesdays');
    expect(reloadCurrentConversation).not.toHaveBeenCalled();
  });

  it('replaces an older note instead of adding a second', async () => {
    server.messages = [user, { ...reply, memory_note: 'First' }];
    await mergeExternalChanges('c1');
    server.messages = [user, { ...reply, memory_note: 'Second' }];
    await mergeExternalChanges('c1');

    expect(document.querySelectorAll('.message-memory-note')).toHaveLength(1);
    expect(noteText()).toBe('Memory updated: Second');
  });

  it('leaves replies with an unchanged note alone', async () => {
    server.messages = [user, reply];
    await mergeExternalChanges('c1');
    expect(noteText()).toBeUndefined();
  });
});
