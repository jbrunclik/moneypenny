/**
 * A batch turn's cleanup must not tear down a newer turn in the same
 * conversation. The batch path releases its active request as soon as the
 * reply arrives (so a follow-up starts a fresh turn), then awaits the cost
 * fetch; a follow-up sent in that window registered turn 2, and turn 1's
 * finally removed turn 2's active request and sync "streaming" mark - a
 * third message was no longer steered, and the sync's own-turn guard was off.
 * The streaming path already guards this (stream-cleanup-superseded).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const sync = {
  setConversationStreaming: vi.fn(),
  setLocalMessageCount: vi.fn(),
  incrementLocalMessageCount: vi.fn(),
};
vi.mock('@/sync/SyncManager', () => ({ getSyncManager: () => sync }));
vi.mock('@/api/chat', () => ({
  chat: {
    sendBatch: vi.fn(() =>
      Promise.resolve({ id: 'a1', response: 'Answer', created_at: '2026-10-10T20:00:00', message_count: 2 })
    ),
  },
}));
vi.mock('@/components/messages', () => ({
  addMessageToUI: vi.fn(),
  showLoadingIndicator: vi.fn(),
  hideLoadingIndicator: vi.fn(),
  updateUserMessageId: vi.fn(),
}));
vi.mock('@/components/ScrollToBottom', () => ({ checkScrollButtonVisibility: vi.fn() }));
vi.mock('@/components/messages/research-offer', () => ({ renderResearchOffer: vi.fn() }));
vi.mock('@/components/MessageInput', () => ({
  showUploadProgress: vi.fn(),
  hideUploadProgress: vi.fn(),
  updateUploadProgress: vi.fn(),
}));
vi.mock('@/core/conversation-actions', () => ({ updateConversationTitle: vi.fn() }));
vi.mock('@/core/attention', () => ({ notifyTurnFinished: vi.fn() }));
vi.mock('@/core/response-scroll', () => ({ scrollToBatchReply: vi.fn(), settleAnchoredReply: vi.fn() }));

let releaseCost: () => void = () => {};
vi.mock('@/core/toolbar', () => ({
  updateConversationCost: vi.fn(
    () =>
      new Promise<void>((resolve) => {
        releaseCost = resolve;
      })
  ),
}));

import { useStore } from '@/state/store';
import { trackRequest, untrackRequest } from '@/core/active-requests';
import { sendBatchMessage } from '@/core/batch-send';

describe('sendBatchMessage cleanup', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useStore.getState().removeActiveRequest('c1');
    document.body.innerHTML = '<div id="messages"></div>';
    useStore.setState({
      currentConversation: { id: 'c1', title: 'T', model: 'm', created_at: '', updated_at: '' } as never,
    });
  });

  it("a follow-up's turn started during the cost fetch keeps its state", async () => {
    const turn1 = sendBatchMessage('c1', 'First', [], [], 'temp-1', false);
    // Reply in, cost fetch pending: the user sends again (turn 2)
    const { updateConversationCost } = await import('@/core/toolbar');
    await vi.waitFor(() => expect(updateConversationCost).toHaveBeenCalled());
    trackRequest('turn-2', { conversationId: 'c1', type: 'batch' });
    useStore.getState().setActiveRequest('c1', { conversationId: 'c1', type: 'batch' });
    sync.setConversationStreaming.mockClear();

    releaseCost();
    await turn1;

    expect(useStore.getState().getActiveRequest('c1')).toBeDefined();
    expect(sync.setConversationStreaming).not.toHaveBeenCalledWith('c1', false);
    untrackRequest('turn-2');
  });
});
