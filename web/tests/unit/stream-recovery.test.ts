/**
 * Unit tests for stream-recovery module
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import type { Conversation, Message } from '@/types/api';

// Mock the API client
vi.mock('@/api/client', () => ({
  conversations: {
    getMessage: vi.fn(),
    get: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
    }
  },
}));

// Mock the toast component
vi.mock('@/components/Toast', () => ({
  toast: {
    loading: vi.fn(() => ({ dismiss: vi.fn() })),
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}));

// Mock messages components
vi.mock('@/components/messages', () => ({
  updateStreamingMessage: vi.fn(),
  finalizeStreamingMessage: vi.fn(),
  getStreamingMessageElement: vi.fn(),
  cleanupStreamingContext: vi.fn(),
  addMessageToUI: vi.fn(),
}));

// Mock DOM utilities
vi.mock('@/utils/dom', () => ({
  getElementById: vi.fn(),
  scrollToBottom: vi.fn(),
}));

// Mock conversation/toolbar functions
vi.mock('@/core/conversation', () => ({
  updateConversationTitle: vi.fn(),
}));

vi.mock('@/core/toolbar', () => ({
  updateConversationCost: vi.fn(),
}));

// Mock SyncManager - need to keep consistent mock instance
const mockSyncManager = {
  incrementLocalMessageCount: vi.fn(),
  setConversationStreaming: vi.fn(),
  incrementalSync: vi.fn(),
};

vi.mock('@/sync/SyncManager', () => ({
  getSyncManager: vi.fn(() => mockSyncManager),
}));

// Mock sync-banner
vi.mock('@/core/sync-banner', () => ({
  hideNewMessagesAvailableBanner: vi.fn(),
}));

// Import after mocks are set up
import {
  markStreamForRecovery,
  clearPendingRecovery,
  hasPendingRecovery,
  getPendingRecovery,
  attemptRecovery,
} from '@/core/stream-recovery';
import { conversations as conversationsApi, ApiError } from '@/api/client';
import { toast } from '@/components/Toast';
import {
  updateStreamingMessage,
  finalizeStreamingMessage,
  getStreamingMessageElement,
  cleanupStreamingContext,
  addMessageToUI,
} from '@/components/messages';
import { getElementById, scrollToBottom } from '@/utils/dom';
import { getSyncManager } from '@/sync/SyncManager';
import { hideNewMessagesAvailableBanner } from '@/core/sync-banner';

// Helper to reset store state
function resetStore() {
  useStore.setState({
    token: null,
    user: null,
    googleClientId: null,
    conversations: [],
    currentConversation: null,
    models: [],
    defaultModel: 'gemini-3-flash-preview',
    pendingModel: null,
    isLoading: false,
    isSidebarOpen: false,
    streamingEnabled: true,
    streamingConversationId: null,
    forceTools: [],
    pendingFiles: [],
    uploadConfig: {
      maxFileSize: 20 * 1024 * 1024,
      maxFilesPerMessage: 10,
      allowedFileTypes: [],
    },
    appVersion: null,
    newVersionAvailable: false,
    versionBannerDismissed: false,
    notifications: [],
    draftMessage: '',
    draftFiles: [],
  });
}

// Helper to create a mock conversation
function createConversation(id: string, title: string = 'Test'): Conversation {
  return {
    id,
    title,
    model: 'gemini-3-flash-preview',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  };
}

// Helper to create a mock message
function createMessage(id: string, content: string): Message {
  return {
    id,
    role: 'assistant',
    content,
    created_at: '2024-01-01T00:00:00Z',
  };
}

describe('stream-recovery', () => {
  const mockGetMessage = conversationsApi.getMessage as ReturnType<typeof vi.fn>;
  const mockGetConversation = conversationsApi.get as ReturnType<typeof vi.fn>;
  const mockToastLoading = toast.loading as ReturnType<typeof vi.fn>;
  const mockToastSuccess = toast.success as ReturnType<typeof vi.fn>;
  const mockToastWarning = toast.warning as ReturnType<typeof vi.fn>;
  const mockToastError = toast.error as ReturnType<typeof vi.fn>;
  const mockGetStreamingElement = getStreamingMessageElement as ReturnType<typeof vi.fn>;
  const mockUpdateStreamingMessage = updateStreamingMessage as ReturnType<typeof vi.fn>;
  const mockFinalizeStreamingMessage = finalizeStreamingMessage as ReturnType<typeof vi.fn>;
  const mockCleanupStreamingContext = cleanupStreamingContext as ReturnType<typeof vi.fn>;
  const mockAddMessageToUI = addMessageToUI as ReturnType<typeof vi.fn>;
  const mockGetElementById = getElementById as ReturnType<typeof vi.fn>;
  const mockScrollToBottom = scrollToBottom as ReturnType<typeof vi.fn>;
  const mockHideNewMessagesBanner = hideNewMessagesAvailableBanner as ReturnType<typeof vi.fn>;

  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
    vi.useFakeTimers();

    // Default mock implementations
    const mockDismiss = vi.fn();
    mockToastLoading.mockReturnValue({ dismiss: mockDismiss });
    mockGetStreamingElement.mockReturnValue(null);
    mockGetElementById.mockReturnValue(null);

    // Reset shared sync manager mock
    mockSyncManager.incrementLocalMessageCount.mockClear();
    mockSyncManager.setConversationStreaming.mockClear();
    mockSyncManager.incrementalSync.mockClear();
  });

  afterEach(() => {
    // Clear all pending recoveries between tests
    clearPendingRecovery('conv-1');
    clearPendingRecovery('conv-2');
    vi.useRealTimers();
  });

  describe('markStreamForRecovery', () => {
    it('stores recovery state with correct reason', () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial content', 'visibility');

      expect(hasPendingRecovery('conv-1')).toBe(true);
      const recovery = getPendingRecovery('conv-1');
      expect(recovery).toBeDefined();
      expect(recovery?.conversationId).toBe('conv-1');
      expect(recovery?.expectedMessageId).toBe('msg-123');
      expect(recovery?.capturedContent).toBe('partial content');
      expect(recovery?.reason).toBe('visibility');
    });

    it('does not overwrite existing pending recovery with same or lower severity', () => {
      markStreamForRecovery('conv-1', 'msg-123', 'content1', 'network');
      markStreamForRecovery('conv-1', 'msg-456', 'content2', 'visibility');

      const recovery = getPendingRecovery('conv-1');
      expect(recovery?.expectedMessageId).toBe('msg-123'); // First one preserved
      expect(recovery?.reason).toBe('network'); // Higher severity preserved
    });

    it('upgrades reason from visibility to network (more severe)', () => {
      markStreamForRecovery('conv-1', 'msg-123', 'content1', 'visibility');
      markStreamForRecovery('conv-1', 'msg-456', 'content2', 'network');

      const recovery = getPendingRecovery('conv-1');
      expect(recovery?.expectedMessageId).toBe('msg-123'); // Message ID preserved
      expect(recovery?.reason).toBe('network'); // Reason upgraded
    });

    it('upgrades reason from visibility to timeout (more severe)', () => {
      markStreamForRecovery('conv-1', 'msg-123', 'content1', 'visibility');
      markStreamForRecovery('conv-1', 'msg-456', 'content2', 'timeout');

      const recovery = getPendingRecovery('conv-1');
      expect(recovery?.expectedMessageId).toBe('msg-123'); // Message ID preserved
      expect(recovery?.reason).toBe('timeout'); // Reason upgraded
    });

    it('does not downgrade reason from network to visibility', () => {
      markStreamForRecovery('conv-1', 'msg-123', 'content1', 'network');
      markStreamForRecovery('conv-1', 'msg-456', 'content2', 'visibility');

      const recovery = getPendingRecovery('conv-1');
      expect(recovery?.reason).toBe('network'); // Not downgraded
    });

    it('allows multiple conversations to have pending recoveries', () => {
      markStreamForRecovery('conv-1', 'msg-1', 'content1', 'visibility');
      markStreamForRecovery('conv-2', 'msg-2', 'content2', 'network');

      expect(hasPendingRecovery('conv-1')).toBe(true);
      expect(hasPendingRecovery('conv-2')).toBe(true);
      expect(getPendingRecovery('conv-1')?.expectedMessageId).toBe('msg-1');
      expect(getPendingRecovery('conv-2')?.expectedMessageId).toBe('msg-2');
    });
  });

  describe('clearPendingRecovery', () => {
    it('removes pending recovery for conversation', () => {
      markStreamForRecovery('conv-1', 'msg-123', 'content', 'visibility');
      expect(hasPendingRecovery('conv-1')).toBe(true);

      clearPendingRecovery('conv-1');
      expect(hasPendingRecovery('conv-1')).toBe(false);
    });

    it('does nothing if no pending recovery exists', () => {
      expect(() => clearPendingRecovery('nonexistent')).not.toThrow();
    });

    it('only clears specified conversation', () => {
      markStreamForRecovery('conv-1', 'msg-1', 'content1', 'visibility');
      markStreamForRecovery('conv-2', 'msg-2', 'content2', 'network');

      clearPendingRecovery('conv-1');

      expect(hasPendingRecovery('conv-1')).toBe(false);
      expect(hasPendingRecovery('conv-2')).toBe(true);
    });
  });

  describe('hasPendingRecovery', () => {
    it('returns false when no recovery pending', () => {
      expect(hasPendingRecovery('conv-1')).toBe(false);
    });

    it('returns true when recovery is pending', () => {
      markStreamForRecovery('conv-1', 'msg-123', 'content', 'visibility');
      expect(hasPendingRecovery('conv-1')).toBe(true);
    });
  });

  describe('attemptRecovery', () => {
    it('returns false when no pending recovery', async () => {
      const result = await attemptRecovery('conv-1');
      expect(result).toBe(false);
    });

    it('shows loading toast during recovery', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'content', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockGetMessage.mockResolvedValue(createMessage('msg-123', 'recovered content'));
      mockGetStreamingElement.mockReturnValue(document.createElement('div'));

      await attemptRecovery('conv-1');

      expect(mockToastLoading).toHaveBeenCalledWith('Recovering response...');
    });

    it('fetches message and updates UI on success', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      const recoveredMessage = createMessage('msg-123', 'full recovered content');
      mockGetMessage.mockResolvedValue(recoveredMessage);
      const mockElement = document.createElement('div');
      mockGetStreamingElement.mockReturnValue(mockElement);

      const result = await attemptRecovery('conv-1');

      expect(result).toBe(true);
      expect(mockGetMessage).toHaveBeenCalledWith('msg-123');
      expect(mockUpdateStreamingMessage).toHaveBeenCalledWith(mockElement, 'full recovered content');
      expect(mockFinalizeStreamingMessage).toHaveBeenCalled();
      expect(mockToastSuccess).toHaveBeenCalledWith('Response recovered');
    });

    it('returns true on successful recovery', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockGetMessage.mockResolvedValue(createMessage('msg-123', 'content'));
      mockGetStreamingElement.mockReturnValue(document.createElement('div'));

      const result = await attemptRecovery('conv-1');
      expect(result).toBe(true);
    });

    it('returns false on failure', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockGetMessage.mockRejectedValue(new ApiError('Not found', 404));

      const recoveryPromise = attemptRecovery('conv-1');

      // Advance through all retry delays (500 + 1000 + 2000 + 4000 + 8000 = 15500ms)
      await vi.advanceTimersByTimeAsync(20000);

      const result = await recoveryPromise;
      expect(result).toBe(false);
    }, 30000);

    it('clears pending recovery after success', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockGetMessage.mockResolvedValue(createMessage('msg-123', 'content'));
      mockGetStreamingElement.mockReturnValue(document.createElement('div'));

      await attemptRecovery('conv-1');

      expect(hasPendingRecovery('conv-1')).toBe(false);
    });

    it('clears pending recovery after failure', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockGetMessage.mockRejectedValue(new ApiError('Not found', 404));

      const recoveryPromise = attemptRecovery('conv-1');

      // Advance through all retry delays
      await vi.advanceTimersByTimeAsync(20000);

      await recoveryPromise;

      expect(hasPendingRecovery('conv-1')).toBe(false);
    }, 30000);

    it('shows warning toast when message has no content, files, or images', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockGetMessage.mockResolvedValue(createMessage('msg-123', ''));

      await attemptRecovery('conv-1');

      expect(mockToastWarning).toHaveBeenCalledWith('Response may be incomplete');
    });

    it('succeeds when message has files but no text content', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      // Message with files but empty text content
      mockGetMessage.mockResolvedValue({
        id: 'msg-123',
        role: 'assistant',
        content: '',
        created_at: '2024-01-01T00:00:00Z',
        files: [{ id: 'file-1', name: 'doc.pdf', type: 'application/pdf', size: 1024 }],
      });
      mockGetStreamingElement.mockReturnValue(document.createElement('div'));

      const result = await attemptRecovery('conv-1');

      expect(result).toBe(true);
      expect(mockToastSuccess).toHaveBeenCalledWith('Response recovered');
      expect(mockToastWarning).not.toHaveBeenCalled();
    });

    it('succeeds when message has generated images but no text content', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      // Message with generated images but empty text content
      mockGetMessage.mockResolvedValue({
        id: 'msg-123',
        role: 'assistant',
        content: '',
        created_at: '2024-01-01T00:00:00Z',
        generated_images: [{ url: 'https://example.com/image.png', prompt: 'test' }],
      });
      mockGetStreamingElement.mockReturnValue(document.createElement('div'));

      const result = await attemptRecovery('conv-1');

      expect(result).toBe(true);
      expect(mockToastSuccess).toHaveBeenCalledWith('Response recovered');
      expect(mockToastWarning).not.toHaveBeenCalled();
    });

    it('shows error toast with reload option on final failure', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockGetMessage.mockRejectedValue(new ApiError('Not found', 404));

      const recoveryPromise = attemptRecovery('conv-1');

      // Advance through all retry delays
      await vi.advanceTimersByTimeAsync(20000);

      await recoveryPromise;

      expect(mockToastError).toHaveBeenCalledWith(
        'Response may be incomplete. Tap to reload.',
        expect.objectContaining({
          action: expect.objectContaining({
            label: 'Reload',
          }),
        })
      );
    }, 30000);

    it('cleans up streaming context on success', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockGetMessage.mockResolvedValue(createMessage('msg-123', 'content'));
      mockGetStreamingElement.mockReturnValue(document.createElement('div'));

      await attemptRecovery('conv-1');

      expect(mockCleanupStreamingContext).toHaveBeenCalled();
    });

    it('does NOT increment message count (cleanup handles it to avoid double increment)', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockGetMessage.mockResolvedValue(createMessage('msg-123', 'content'));
      mockGetStreamingElement.mockReturnValue(document.createElement('div'));

      await attemptRecovery('conv-1');

      // Recovery does NOT increment the count - cleanupStreamingRequest handles it
      // when messageSuccessful=true. Incrementing in both places would cause +4 drift.
      expect(mockSyncManager.incrementLocalMessageCount).not.toHaveBeenCalled();
    });
  });

  describe('recovery with retries (race condition handling)', () => {
    it('retries on 404 with exponential backoff', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      // First call returns 404, second returns success
      mockGetMessage
        .mockRejectedValueOnce(new ApiError('Not found', 404))
        .mockResolvedValueOnce(createMessage('msg-123', 'content'));
      mockGetStreamingElement.mockReturnValue(document.createElement('div'));

      const recoveryPromise = attemptRecovery('conv-1');

      // Advance timer for first retry delay (500ms)
      await vi.advanceTimersByTimeAsync(500);

      const result = await recoveryPromise;

      expect(result).toBe(true);
      expect(mockGetMessage).toHaveBeenCalledTimes(2);
    });

    it('gives up after max retry attempts', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      // All calls return 404
      mockGetMessage.mockRejectedValue(new ApiError('Not found', 404));

      const recoveryPromise = attemptRecovery('conv-1');

      // Advance through all retry delays (500 + 1000 + 2000 + 4000 + 8000 = 15500ms)
      await vi.advanceTimersByTimeAsync(20000);

      const result = await recoveryPromise;

      expect(result).toBe(false);
      // Should have tried 6 times (initial + 5 retries)
      expect(mockGetMessage).toHaveBeenCalledTimes(6);
    });

    it('succeeds when message saves during retry window', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      // First 3 calls return 404, 4th returns success
      mockGetMessage
        .mockRejectedValueOnce(new ApiError('Not found', 404))
        .mockRejectedValueOnce(new ApiError('Not found', 404))
        .mockRejectedValueOnce(new ApiError('Not found', 404))
        .mockResolvedValueOnce(createMessage('msg-123', 'finally saved'));
      mockGetStreamingElement.mockReturnValue(document.createElement('div'));

      const recoveryPromise = attemptRecovery('conv-1');

      // Advance through retries
      await vi.advanceTimersByTimeAsync(10000);

      const result = await recoveryPromise;

      expect(result).toBe(true);
      expect(mockGetMessage).toHaveBeenCalledTimes(4);
    });
  });

  describe('debouncing and concurrency', () => {
    it('allows new recovery after successful one (debounce clears with pending)', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockGetMessage.mockResolvedValue(createMessage('msg-123', 'content'));
      mockGetStreamingElement.mockReturnValue(document.createElement('div'));

      // First attempt - succeeds and clears pending recovery (including debounce state)
      const result1 = await attemptRecovery('conv-1');
      expect(result1).toBe(true);

      // Clear was done by the first recovery
      // Mark again and try immediately - this should work because
      // clearPendingRecovery also clears the debounce timestamp
      mockGetMessage.mockResolvedValue(createMessage('msg-456', 'new content'));
      markStreamForRecovery('conv-1', 'msg-456', 'content2', 'network');

      // This second attempt should succeed (not debounced) because
      // clearPendingRecovery clears the lastRecoveryAttempt timestamp
      const result2 = await attemptRecovery('conv-1');
      expect(result2).toBe(true);

      // Two getMessage calls - one for each successful recovery
      expect(mockGetMessage).toHaveBeenCalledTimes(2);
    });

    it('prevents concurrent recovery attempts for same conversation', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      // Slow response
      mockGetMessage.mockImplementation(async () => {
        await new Promise((r) => setTimeout(r, 1000));
        return createMessage('msg-123', 'content');
      });
      mockGetStreamingElement.mockReturnValue(document.createElement('div'));

      // Start first recovery
      const promise1 = attemptRecovery('conv-1');

      // Try to start second recovery while first is in progress
      // Need to advance time a bit first and re-mark
      await vi.advanceTimersByTimeAsync(350); // Past debounce
      markStreamForRecovery('conv-1', 'msg-456', 'content2', 'network');
      const promise2 = attemptRecovery('conv-1');

      await vi.advanceTimersByTimeAsync(2000);
      const [result1, result2] = await Promise.all([promise1, promise2]);

      // Both should return the same result (second one waits for first)
      expect(result1).toBe(true);
      expect(result2).toBe(true);
      // But getMessage should only be called once
      expect(mockGetMessage).toHaveBeenCalledTimes(1);
    });
  });

  describe('visibility-based recovery', () => {
    it('skips recovery if not hidden long enough', async () => {
      // Mark with visibility reason
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'visibility');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockGetMessage.mockResolvedValue(createMessage('msg-123', 'content'));

      // Immediately attempt recovery (hidden for 0ms)
      const result = await attemptRecovery('conv-1');

      expect(result).toBe(false);
      expect(mockGetMessage).not.toHaveBeenCalled();
    });

    it('proceeds with recovery if hidden long enough', async () => {
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      // Mark for recovery
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'visibility');

      // Wait for minimum hidden duration
      await vi.advanceTimersByTimeAsync(600);

      mockGetMessage.mockResolvedValue(createMessage('msg-123', 'content'));
      mockGetStreamingElement.mockReturnValue(document.createElement('div'));

      const result = await attemptRecovery('conv-1');

      expect(result).toBe(true);
      expect(mockGetMessage).toHaveBeenCalled();
    });
  });

  describe('non-current conversation handling', () => {
    it('still recovers for non-current conversation but does not update UI', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv1 = createConversation('conv-1');
      const conv2 = createConversation('conv-2');
      useStore.getState().addConversation(conv1);
      useStore.getState().addConversation(conv2);
      useStore.getState().setCurrentConversation(conv2); // Different conversation

      mockGetMessage.mockResolvedValue(createMessage('msg-123', 'content'));

      const result = await attemptRecovery('conv-1');

      expect(result).toBe(true);
      expect(mockUpdateStreamingMessage).not.toHaveBeenCalled();
      expect(mockFinalizeStreamingMessage).not.toHaveBeenCalled();
    });
  });

  describe('fallback when streaming context is missing', () => {
    it('updates orphaned streaming element in DOM when context is null', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      // Mock: context returns null, but there's still a streaming element in DOM
      mockGetStreamingElement.mockReturnValue(null);

      // Create a mock container with an orphaned streaming element
      const mockContainer = document.createElement('div');
      const orphanedElement = document.createElement('div');
      orphanedElement.className = 'message assistant streaming';
      mockContainer.appendChild(orphanedElement);
      mockGetElementById.mockReturnValue(mockContainer);

      mockGetMessage.mockResolvedValue(createMessage('msg-123', 'recovered content'));

      const result = await attemptRecovery('conv-1');

      expect(result).toBe(true);
      // Should update the existing element, not add a new one
      expect(mockUpdateStreamingMessage).toHaveBeenCalledWith(orphanedElement, 'recovered content');
      expect(mockFinalizeStreamingMessage).toHaveBeenCalled();
      // Should NOT add a new message
      expect(mockAddMessageToUI).not.toHaveBeenCalled();
      expect(mockScrollToBottom).toHaveBeenCalledWith(mockContainer);
    });

    it('updates orphaned incomplete element in DOM when context is null', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      // Mock: context returns null, but there's an incomplete element in DOM
      mockGetStreamingElement.mockReturnValue(null);

      const mockContainer = document.createElement('div');
      const incompleteElement = document.createElement('div');
      incompleteElement.className = 'message assistant message-incomplete';
      mockContainer.appendChild(incompleteElement);
      mockGetElementById.mockReturnValue(mockContainer);

      mockGetMessage.mockResolvedValue(createMessage('msg-123', 'recovered content'));

      const result = await attemptRecovery('conv-1');

      expect(result).toBe(true);
      // Should update the existing incomplete element
      expect(mockUpdateStreamingMessage).toHaveBeenCalledWith(incompleteElement, 'recovered content');
      expect(mockFinalizeStreamingMessage).toHaveBeenCalled();
      expect(mockAddMessageToUI).not.toHaveBeenCalled();
    });

    it('finds element by data-message-id for reliable lookup', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      // Mock: context returns null, but element exists with data-message-id
      mockGetStreamingElement.mockReturnValue(null);

      const mockContainer = document.createElement('div');
      const elementWithId = document.createElement('div');
      elementWithId.className = 'message assistant'; // No streaming/incomplete class
      elementWithId.dataset.messageId = 'msg-123'; // But has the correct ID
      mockContainer.appendChild(elementWithId);
      mockGetElementById.mockReturnValue(mockContainer);

      mockGetMessage.mockResolvedValue(createMessage('msg-123', 'recovered content'));

      const result = await attemptRecovery('conv-1');

      expect(result).toBe(true);
      // Should find and update the element by ID
      expect(mockUpdateStreamingMessage).toHaveBeenCalledWith(elementWithId, 'recovered content');
      expect(mockFinalizeStreamingMessage).toHaveBeenCalled();
      expect(mockAddMessageToUI).not.toHaveBeenCalled();
    });

    it('adds new message only when no streaming element exists in DOM', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      // Mock: no context and no streaming element in DOM
      mockGetStreamingElement.mockReturnValue(null);

      const mockContainer = document.createElement('div');
      // Container has no streaming/incomplete elements
      mockGetElementById.mockReturnValue(mockContainer);

      mockGetMessage.mockResolvedValue(createMessage('msg-123', 'recovered content'));

      const result = await attemptRecovery('conv-1');

      expect(result).toBe(true);
      // Should add a new message since no existing element
      expect(mockAddMessageToUI).toHaveBeenCalledWith(
        expect.objectContaining({
          id: 'msg-123',
          role: 'assistant',
          content: 'recovered content',
        }),
        mockContainer
      );
      expect(mockScrollToBottom).toHaveBeenCalledWith(mockContainer);
    });

    it('hides banner and triggers sync to check for genuinely new messages', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockGetStreamingElement.mockReturnValue(document.createElement('div'));
      mockGetMessage.mockResolvedValue(createMessage('msg-123', 'content'));

      await attemptRecovery('conv-1');

      // Should hide the "new messages available" banner
      expect(mockHideNewMessagesBanner).toHaveBeenCalled();
      // Should trigger incremental sync to re-check for genuinely new messages
      // If there are new messages from another device, the sync will re-show the banner
      expect(mockSyncManager.incrementalSync).toHaveBeenCalled();
    });

    it('appends message to store only when adding new message', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockGetStreamingElement.mockReturnValue(null);
      const mockContainer = document.createElement('div');
      // No existing streaming element
      mockGetElementById.mockReturnValue(mockContainer);
      mockGetMessage.mockResolvedValue(createMessage('msg-123', 'recovered content'));

      await attemptRecovery('conv-1');

      // Check that appendMessage was called on the store
      const messages = useStore.getState().getMessages('conv-1');
      expect(messages.some(m => m.id === 'msg-123')).toBe(true);
    });
  });
});
