/**
 * A second Enter / Send tap while the first send is still preparing (the
 * first message of a chat creates the conversation on the server first) read
 * the same composer text - not yet cleared - and sent it again: a duplicate
 * message, or a second conversation.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useStore } from '@/state/store';

const pendingCreates: (() => void)[] = [];
const releaseCreate = (): void => pendingCreates.splice(0).forEach((release) => release());
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

import { conversations } from '@/api/conversations';
import { sendStreamingMessage } from '@/core/stream-send';
import { sendMessage } from '@/core/messaging';

describe('sendMessage re-entry', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    composerText = 'Hello';
    useStore.setState({
      currentConversation: { id: 'temp-1', title: 'New Conversation', model: 'm', created_at: '', updated_at: '' } as never,
      streamingEnabled: true,
    });
  });

  it('a second send while the first still prepares is ignored', async () => {
    const first = sendMessage();
    const second = sendMessage();
    await vi.waitFor(() => expect(conversations.create).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 20)); // a second create, if any
    releaseCreate();
    await Promise.all([first, second]);

    expect(conversations.create).toHaveBeenCalledTimes(1);
    expect(sendStreamingMessage).toHaveBeenCalledTimes(1);
  });
});
