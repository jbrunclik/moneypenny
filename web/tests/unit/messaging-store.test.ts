/**
 * The Zustand store must stay authoritative for a conversation's messages:
 * a completed assistant reply (streamed or batch) is appended to the store,
 * not only rendered to the DOM.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import type { Conversation } from '@/types/api';

vi.mock('@/api/client', () => ({
  chat: {
    stream: vi.fn(),
    sendBatch: vi.fn(),
    resumeStream: vi.fn(),
  },
  conversations: {
    get: vi.fn(),
    create: vi.fn(),
    unarchive: vi.fn(),
    interject: vi.fn(),
    truncate: vi.fn(),
  },
  messages: { delete: vi.fn() },
}));

vi.mock('@/components/Toast', () => ({
  toast: {
    loading: vi.fn(() => ({ dismiss: vi.fn() })),
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}));

vi.mock('@/components/Sidebar', () => ({
  renderConversationsList: vi.fn(),
  setActiveConversation: vi.fn(),
}));

vi.mock('@/components/messages', () => ({
  addMessageToUI: vi.fn(),
  appendStoppedEarlyNote: vi.fn(),
  renderMessages: vi.fn(),
  removeRenderedMessagesFrom: vi.fn(),
  addStreamingMessage: vi.fn(() => document.createElement('div')),
  updateStreamingMessage: vi.fn(),
  finalizeStreamingMessage: vi.fn(() => false),
  updateStreamingThinking: vi.fn(),
  updateStreamingToolStart: vi.fn(),
  updateStreamingToolDetail: vi.fn(),
  updateStreamingToolEnd: vi.fn(),
  updateStreamingRetryStatus: vi.fn(),
  cleanupStreamingContext: vi.fn(),
  getStreamingMessageElement: vi.fn(() => null),
  showLoadingIndicator: vi.fn(),
  hideLoadingIndicator: vi.fn(),
  updateUserMessageId: vi.fn(),
  loadAllRemainingNewerMessages: vi.fn(),
  cleanupNewerMessagesScrollListener: vi.fn(),
  hasPendingApproval: vi.fn(() => false),
  lockOlderQuizBlocks: vi.fn(),
}));

vi.mock('@/components/ScrollToBottom', () => ({
  checkScrollButtonVisibility: vi.fn(),
}));

vi.mock('@/components/MessageInput', () => ({
  getMessageInput: vi.fn(() => 'hello'),
  clearMessageInput: vi.fn(),
  focusMessageInput: vi.fn(),
  setInputLoading: vi.fn(),
  shouldAutoFocusInput: vi.fn(() => false),
  showUploadProgress: vi.fn(),
  hideUploadProgress: vi.fn(),
  updateUploadProgress: vi.fn(),
}));

vi.mock('@/components/FileUpload', () => ({
  clearPendingFiles: vi.fn(),
  getPendingFiles: vi.fn(() => []),
}));

vi.mock('@/components/VoiceInput', () => ({
  stopVoiceRecording: vi.fn(),
}));

vi.mock('@/utils/thumbnails', () => ({
  enableScrollOnImageLoad: vi.fn(),
  getThumbnailObserver: vi.fn(() => ({ unobserve: vi.fn() })),
  isProgrammaticScrollActive: vi.fn(() => false),
  observeThumbnail: vi.fn(),
  programmaticScrollToBottom: vi.fn(),
  programmaticScrollToElementTop: vi.fn(),
}));

vi.mock('@/router/deeplink', () => ({
  setConversationHash: vi.fn(),
}));

vi.mock('@/sync/SyncManager', () => ({
  getSyncManager: vi.fn(() => ({
    incrementLocalMessageCount: vi.fn(),
    setConversationStreaming: vi.fn(),
  })),
}));

vi.mock('@/core/conversation', () => ({
  isTempConversation: vi.fn(() => false),
  createConversation: vi.fn(),
  updateConversationTitle: vi.fn(),
}));

vi.mock('@/core/toolbar', () => ({
  updateConversationCost: vi.fn(),
  resetForceTools: vi.fn(),
}));

vi.mock('@/core/location', () => ({
  getClientLocation: vi.fn(async () => null),
}));

vi.mock('@/core/attention', () => ({
  notifyTurnFinished: vi.fn(),
}));

vi.mock('@/components/messages/send-state', () => ({
  setMessageSendState: vi.fn(),
}));

vi.mock('@/components/messages/edit', () => ({
  beginInlineEdit: vi.fn(),
}));

import { sendMessage } from '@/core/messaging';
import { chat } from '@/api/client';

const CONV_ID = 'conv-1';

function conversation(): Conversation {
  return {
    id: CONV_ID,
    title: 'Test',
    model: 'gemini-3-flash-preview',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  };
}

const DONE_FIELDS = {
  id: 'assistant-1',
  created_at: '2024-01-01T00:00:05Z',
  content: 'Hi there',
  sources: [{ title: 'Example', url: 'https://example.com' }],
  generated_images: [{ prompt: 'a cat' }],
  files: [{ name: 'out.csv', type: 'text/csv' }],
  language: 'en',
};

function streamOf(events: Array<Record<string, unknown>>) {
  return async function* () {
    for (const event of events) {
      yield event;
    }
  };
}

function assistantMessages() {
  return useStore.getState().getMessages(CONV_ID).filter((m) => m.role === 'assistant');
}

describe('messaging keeps the store authoritative', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useStore.setState({
      currentConversation: conversation(),
      conversations: [conversation()],
      messages: new Map(),
      messagesPagination: new Map(),
      activeRequests: new Map(),
      streamingConversationId: null,
      forceTools: [],
    });
  });

  it('appends the streamed assistant reply to the store on done', async () => {
    useStore.setState({ streamingEnabled: true });
    vi.mocked(chat.stream).mockImplementation(
      streamOf([
        { type: 'user_message_saved', expected_assistant_message_id: 'assistant-1' },
        { type: 'token', text: 'Hi ' },
        { type: 'token', text: 'there' },
        { type: 'done', ...DONE_FIELDS },
      ]) as unknown as typeof chat.stream
    );

    await sendMessage();

    const assistants = assistantMessages();
    expect(assistants).toHaveLength(1);
    expect(assistants[0]).toMatchObject({
      role: 'assistant',
      ...DONE_FIELDS,
    });
    // The user message stays in place before it
    const all = useStore.getState().getMessages(CONV_ID);
    expect(all.map((m) => m.role)).toEqual(['user', 'assistant']);
  });

  it('falls back to the streamed content when done carries none', async () => {
    useStore.setState({ streamingEnabled: true });
    vi.mocked(chat.stream).mockImplementation(
      streamOf([
        { type: 'token', text: 'Streamed ' },
        { type: 'token', text: 'only' },
        { type: 'done', id: 'assistant-2', created_at: '2024-01-01T00:00:05Z', sources: DONE_FIELDS.sources },
      ]) as unknown as typeof chat.stream
    );

    await sendMessage();

    expect(assistantMessages()).toEqual([
      expect.objectContaining({ id: 'assistant-2', content: 'Streamed only' }),
    ]);
  });

  it('marks a stopped-early streamed reply in the store', async () => {
    useStore.setState({ streamingEnabled: true });
    vi.mocked(chat.stream).mockImplementation(
      streamOf([
        { type: 'token', text: 'Partial' },
        { type: 'done', id: 'assistant-3', created_at: 'now', content: 'Partial', stopped_early: true },
      ]) as unknown as typeof chat.stream
    );

    await sendMessage();

    expect(assistantMessages()[0]).toMatchObject({ id: 'assistant-3', stopped_early: true });
  });

  it('appends the streamed reply even when the user switched away', async () => {
    useStore.setState({ streamingEnabled: true });
    vi.mocked(chat.stream).mockImplementation(async function* () {
      yield { type: 'token', text: 'Hi' };
      useStore.setState({ currentConversation: { ...conversation(), id: 'other' } });
      yield { type: 'done', ...DONE_FIELDS };
    } as unknown as typeof chat.stream);

    await sendMessage();

    expect(assistantMessages()).toEqual([expect.objectContaining({ id: 'assistant-1' })]);
  });

  it('does not duplicate a reply the recovery path already appended', async () => {
    useStore.setState({ streamingEnabled: true });
    vi.mocked(chat.stream).mockImplementation(async function* () {
      yield { type: 'token', text: 'Hi there' };
      // Stream recovery appended the same saved message meanwhile
      useStore.getState().appendMessage(CONV_ID, {
        id: 'assistant-1',
        role: 'assistant',
        content: 'Hi there',
        created_at: DONE_FIELDS.created_at,
      });
      yield { type: 'done', ...DONE_FIELDS };
    } as unknown as typeof chat.stream);

    await sendMessage();

    expect(assistantMessages()).toHaveLength(1);
    expect(assistantMessages()[0]).toMatchObject(DONE_FIELDS);
  });

  it('appends the batch assistant reply to the store', async () => {
    useStore.setState({ streamingEnabled: false });
    vi.mocked(chat.sendBatch).mockResolvedValue({
      ...DONE_FIELDS,
      role: 'assistant',
      stopped_early: false,
    } as unknown as Awaited<ReturnType<typeof chat.sendBatch>>);

    await sendMessage();

    const assistants = assistantMessages();
    expect(assistants).toHaveLength(1);
    expect(assistants[0]).toMatchObject({ role: 'assistant', ...DONE_FIELDS, stopped_early: false });
  });

  it('appends the batch reply even when the user switched away', async () => {
    useStore.setState({ streamingEnabled: false });
    vi.mocked(chat.sendBatch).mockImplementation(async () => {
      useStore.setState({ currentConversation: { ...conversation(), id: 'other' } });
      return { ...DONE_FIELDS } as unknown as Awaited<ReturnType<typeof chat.sendBatch>>;
    });

    await sendMessage();

    expect(assistantMessages()).toEqual([expect.objectContaining({ id: 'assistant-1' })]);
  });
});
