/**
 * A deep-research start always goes over the stream endpoint (the run takes
 * minutes; only the stream path has resume and push), even with streaming off.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useStore } from '@/state/store';
import type { Conversation } from '@/types/api';

vi.mock('@/core/stream-send', () => ({ sendStreamingMessage: vi.fn(() => Promise.resolve()) }));
vi.mock('@/core/batch-send', () => ({ sendBatchMessage: vi.fn(() => Promise.resolve()) }));
vi.mock('@/core/location', () => ({ getClientLocation: vi.fn(() => Promise.resolve(null)) }));
vi.mock('@/components/Sidebar', () => ({ renderConversationsList: vi.fn(), setActiveConversation: vi.fn() }));
vi.mock('@/components/messages', () => ({
  addMessageToUI: vi.fn(),
  hideLoadingIndicator: vi.fn(),
  hasPendingApproval: vi.fn(() => false),
  loadAllRemainingNewerMessages: vi.fn(),
  cleanupNewerMessagesScrollListener: vi.fn(),
}));
vi.mock('@/components/Toast', () => ({
  toast: { info: vi.fn(), error: vi.fn(), warning: vi.fn(), success: vi.fn() },
}));
vi.mock('@/api/conversations', () => ({
  conversations: { stop: vi.fn(), finishNow: vi.fn() },
  messages: { delete: vi.fn(), declineResearchOffer: vi.fn(() => Promise.resolve()) },
}));

import { sendStreamingMessage } from '@/core/stream-send';
import { sendBatchMessage } from '@/core/batch-send';
import { dispatchSend } from '@/core/messaging';
import { declineDeepResearch, startDeepResearch } from '@/core/deep-research';
import { getOutboxEntry } from '@/core/outbox';
import { messages } from '@/api/conversations';
import { toast } from '@/components/Toast';

const CONV: Conversation = {
  id: 'c1',
  title: 'T',
  model: 'gemini-3-flash-preview',
  created_at: '2026-10-03T08:00:00',
  updated_at: '2026-10-03T08:00:00',
};
const PAGE = { older_cursor: null, newer_cursor: null, has_older: false, has_newer: false, total_count: 1 };
const PLAN = { offer_message_id: 'm1', sub_questions: ['A?', 'B?'], context: 'ctx' };

describe('deep research send', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useStore.setState({ currentConversation: CONV, streamingEnabled: false });
    useStore.getState().setMessages('c1', [
      { id: 'm1', role: 'assistant', content: 'x', created_at: '2026-10-03T08:00:00' },
    ], PAGE);
  });

  it('dispatchSend streams a deep-research entry even with streaming off', async () => {
    await dispatchSend('c1', {
      id: 'u1', content: 'Start deep research', files: [], forceTools: [], anonymousMode: false, deepResearch: PLAN,
    });
    expect(sendBatchMessage).not.toHaveBeenCalled();
    expect(vi.mocked(sendStreamingMessage).mock.calls[0][8]).toEqual(PLAN);
  });

  it('a plain entry still uses batch with streaming off', async () => {
    await dispatchSend('c1', { id: 'u2', content: 'hi', files: [], forceTools: [], anonymousMode: false });
    expect(sendBatchMessage).toHaveBeenCalled();
    expect(sendStreamingMessage).not.toHaveBeenCalled();
  });

  it('startDeepResearch sends "Start deep research" with the plan and keeps it in the outbox', async () => {
    await startDeepResearch('m1', ['A?', 'B?'], 'ctx');
    const [, content, , , tempId] = vi.mocked(sendStreamingMessage).mock.calls[0];
    expect(content).toBe('Start deep research');
    expect(vi.mocked(sendStreamingMessage).mock.calls[0][8]).toEqual(PLAN);
    // A retry after a failure resends the plan (the entry carries it)
    expect(getOutboxEntry('c1', tempId)?.deepResearch).toEqual(PLAN);
    const userMsg = useStore.getState().getMessages('c1').find((m) => m.id === tempId);
    expect(userMsg?.content).toBe('Start deep research');
  });

  it('startDeepResearch waits while a reply is still running', async () => {
    useStore.getState().setActiveRequest('c1', { requestId: 'r', messageId: 'a1' } as never);
    await startDeepResearch('m1', ['A?'], '');
    expect(sendStreamingMessage).not.toHaveBeenCalled();
    expect(toast.info).toHaveBeenCalled();
  });

  it('declineDeepResearch patches the offer and marks it declined in the store', async () => {
    useStore.getState().setMessages('c1', [
      {
        id: 'm1', role: 'assistant', content: 'x', created_at: '2026-10-03T08:00:00',
        research: { offer: { status: 'offered' } as never },
      },
    ], PAGE);
    await declineDeepResearch('m1');
    expect(messages.declineResearchOffer).toHaveBeenCalledWith('m1');
    const m = useStore.getState().getMessages('c1')[0];
    expect(m.research?.offer?.status).toBe('declined');
  });
});
