/**
 * A stream's cleanup must not tear down a newer turn in the same conversation.
 *
 * handleStreamDone releases the active request early so a follow-up can start
 * while the cost fetch runs; an autostarted deep research (or a quick follow-up)
 * starts in that window. The old stream's cleanup then cleared the NEW turn's
 * active request and sync "streaming" mark - the sync saw its messages and
 * showed "New messages available" mid-run (Oct 4 2026).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const sync = { setConversationStreaming: vi.fn(), incrementLocalMessageCount: vi.fn() };
vi.mock('@/sync/SyncManager', () => ({ getSyncManager: () => sync }));
vi.mock('@/components/messages', () => ({
  cleanupStreamingContext: vi.fn(),
  addStreamingMessage: vi.fn(() => document.createElement('div')),
}));
vi.mock('@/components/MessageInput', () => ({ hideUploadProgress: vi.fn(), showUploadProgress: vi.fn() }));
vi.mock('@/core/attention', () => ({ notifyTurnFinished: vi.fn() }));

import { useStore } from '@/state/store';
import { cleanupStreamingContext } from '@/components/messages';
import { trackRequest } from '@/core/active-requests';
import { cleanupStreamingRequest } from '@/core/stream-session';

describe('cleanupStreamingRequest', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStore.getState().removeActiveRequest('c1');
  });

  it('a finished turn releases everything', () => {
    trackRequest('old', { conversationId: 'c1', type: 'stream' });
    useStore.getState().setActiveRequest('c1', { conversationId: 'c1', type: 'stream' });

    cleanupStreamingRequest('old', 'c1', true);

    expect(useStore.getState().getActiveRequest('c1')).toBeUndefined();
    expect(sync.setConversationStreaming).toHaveBeenCalledWith('c1', false);
    expect(cleanupStreamingContext).toHaveBeenCalled();
    expect(sync.incrementLocalMessageCount).toHaveBeenCalledWith('c1', 2);
  });

  it('a newer turn in the same conversation keeps its state', () => {
    trackRequest('old', { conversationId: 'c1', type: 'stream' });
    trackRequest('new', { conversationId: 'c1', type: 'stream' });
    useStore.getState().setActiveRequest('c1', { conversationId: 'c1', type: 'stream' });

    cleanupStreamingRequest('old', 'c1', true);

    expect(useStore.getState().getActiveRequest('c1')).toBeDefined();
    expect(sync.setConversationStreaming).not.toHaveBeenCalledWith('c1', false);
    expect(cleanupStreamingContext).not.toHaveBeenCalled();
    // The finished turn's own messages are still counted
    expect(sync.incrementLocalMessageCount).toHaveBeenCalledWith('c1', 2);
    cleanupStreamingRequest('new', 'c1', true);
  });
});
