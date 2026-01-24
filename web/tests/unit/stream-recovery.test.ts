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
};

vi.mock('@/sync/SyncManager', () => ({
  getSyncManager: vi.fn(() => mockSyncManager),
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
} from '@/components/messages';
import { getSyncManager } from '@/sync/SyncManager';

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

  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
    vi.useFakeTimers();

    // Default mock implementations
    const mockDismiss = vi.fn();
    mockToastLoading.mockReturnValue({ dismiss: mockDismiss });
    mockGetStreamingElement.mockReturnValue(null);

    // Reset shared sync manager mock
    mockSyncManager.incrementLocalMessageCount.mockClear();
    mockSyncManager.setConversationStreaming.mockClear();
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

    it('does not overwrite existing pending recovery', () => {
      markStreamForRecovery('conv-1', 'msg-123', 'content1', 'visibility');
      markStreamForRecovery('conv-1', 'msg-456', 'content2', 'network');

      const recovery = getPendingRecovery('conv-1');
      expect(recovery?.expectedMessageId).toBe('msg-123'); // First one preserved
      expect(recovery?.reason).toBe('visibility'); // First reason preserved
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

    it('shows warning toast when message has no content', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockGetMessage.mockResolvedValue(createMessage('msg-123', ''));

      await attemptRecovery('conv-1');

      expect(mockToastWarning).toHaveBeenCalledWith('Response may be incomplete');
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

    it('updates sync manager message count on success', async () => {
      markStreamForRecovery('conv-1', 'msg-123', 'partial', 'network');
      const conv = createConversation('conv-1');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockGetMessage.mockResolvedValue(createMessage('msg-123', 'content'));
      mockGetStreamingElement.mockReturnValue(document.createElement('div'));

      await attemptRecovery('conv-1');

      // Use the shared mock instance
      expect(mockSyncManager.incrementLocalMessageCount).toHaveBeenCalledWith('conv-1', 2);
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
});
