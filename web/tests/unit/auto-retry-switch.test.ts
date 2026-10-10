/**
 * The 2s auto-retry after a transient send failure went straight back to
 * dispatching - after a conversation switch it rendered the streaming
 * bubble into the conversation now on screen.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useStore } from '@/state/store';

const pendingCreates: (() => void)[] = [];
vi.mock('@/api/conversations', () => ({
  conversations: {
    create: vi.fn(
      () =>
        new Promise((resolve) => {
          pendingCreates.push(() =>
            resolve({ id: 'real-1', title: 'New Conversation', model: 'm', created_at: '', updated_at: '' })
          );
        })
    ),
  },
}));
vi.mock('@/core/stream-send', () => ({ sendStreamingMessage: vi.fn() }));
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
let composerText = 'Hello';
vi.mock('@/components/MessageInput', () => ({
  getMessageInput: () => composerText,
  clearMessageInput: () => {
    composerText = '';
  },
  refocusMessageInputAfterSend: vi.fn(),
  setInputLoading: vi.fn(),
  shouldAutoFocusInput: () => false,
}));
vi.mock('@/components/FileUpload', () => ({ getPendingFiles: () => [], clearPendingFiles: vi.fn() }));
vi.mock('@/components/VoiceInput', () => ({ stopVoiceRecording: vi.fn() }));
vi.mock('@/router/deeplink', () => ({ setConversationHash: vi.fn() }));
vi.mock('@/core/toolbar', () => ({ resetForceTools: vi.fn() }));

import { sendStreamingMessage } from '@/core/stream-send';
import { sendMessage } from '@/core/messaging';
import { ApiError } from '@/api/http';
import { SEND_AUTO_RETRY_DELAY_MS } from '@/config';

describe('auto-retry after a transient failure', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    composerText = 'Hello';
    useStore.setState({
      currentConversation: { id: 'c1', title: 'T', model: 'm', created_at: '', updated_at: '' } as never,
      streamingEnabled: true,
    });
    vi.mocked(sendStreamingMessage).mockRejectedValueOnce(
      new ApiError('Network error', 0, { isNetworkError: true } as never)
    );
    vi.mocked(sendStreamingMessage).mockResolvedValue(undefined);
  });

  it('retries in the conversation the user is still in', async () => {
    vi.useFakeTimers();
    const sent = sendMessage();
    await vi.advanceTimersByTimeAsync(SEND_AUTO_RETRY_DELAY_MS + 100);
    await sent;
    vi.useRealTimers();
    expect(sendStreamingMessage).toHaveBeenCalledTimes(2);
  });

  it('does not retry into another conversation the user switched to meanwhile', async () => {
    vi.useFakeTimers();
    const sent = sendMessage();
    await vi.advanceTimersByTimeAsync(100);
    useStore.setState({
      currentConversation: { id: 'c2', title: 'Other', model: 'm', created_at: '', updated_at: '' } as never,
    });
    await vi.advanceTimersByTimeAsync(SEND_AUTO_RETRY_DELAY_MS + 100);
    await sent;
    vi.useRealTimers();
    expect(sendStreamingMessage).toHaveBeenCalledTimes(1);
    // Left failed (Retry when they come back), not pending forever
    const msg = useStore.getState().getMessages('c1').filter((m) => m.content === 'Hello').pop();
    expect(msg?.status).toBe('failed');
  });
});
