/**
 * Unit tests for SyncManager
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import type { Conversation, ConversationSummary, SyncResponse } from '@/types/api';

// Mock the API client
vi.mock('@/api/client', () => ({
  conversations: {
    sync: vi.fn(),
  },
}));

// Mock the toast component
vi.mock('@/components/Toast', () => ({
  toast: {
    warning: vi.fn(),
    error: vi.fn(),
    success: vi.fn(),
    info: vi.fn(),
  },
}));

// Import after mocks are set up
import { SyncManager, type SyncManagerCallbacks } from '@/sync/SyncManager';
import { conversations as conversationsApi } from '@/api/client';
import { toast } from '@/components/Toast';

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
function createConversation(id: string, title: string, messageCount?: number): Conversation {
  return {
    id,
    title,
    model: 'gemini-3-flash-preview',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    messageCount,
  };
}

// Helper to create a mock conversation summary (from sync API)
function createConversationSummary(
  id: string,
  title: string,
  messageCount: number
): ConversationSummary {
  return {
    id,
    title,
    model: 'gemini-3-flash-preview',
    updated_at: '2024-01-01T00:00:00Z',
    message_count: messageCount,
  };
}

// Helper to create mock sync response
function createSyncResponse(
  conversations: ConversationSummary[],
  isFullSync: boolean = true
): SyncResponse {
  return {
    conversations,
    server_time: '2024-01-01T00:00:00Z',
    is_full_sync: isFullSync,
  };
}

describe('SyncManager', () => {
  let syncManager: SyncManager;
  let callbacks: SyncManagerCallbacks;
  const mockSync = conversationsApi.sync as ReturnType<typeof vi.fn>;

  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
    vi.useFakeTimers();

    // Create mock callbacks
    callbacks = {
      onConversationsUpdated: vi.fn(),
      onCurrentConversationDeleted: vi.fn(),
      onCurrentConversationExternalUpdate: vi.fn(),
    };

    // Default mock implementation
    mockSync.mockResolvedValue(createSyncResponse([]));
  });

  afterEach(() => {
    syncManager?.stop();
    vi.useRealTimers();
  });

  describe('start', () => {
    it('performs initial full sync', async () => {
      const serverConvs = [createConversationSummary('conv-1', 'Test', 5)];
      mockSync.mockResolvedValue(createSyncResponse(serverConvs));

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      expect(mockSync).toHaveBeenCalledWith(null, true);
    });

    it('adds new conversations from server to store', async () => {
      const serverConvs = [createConversationSummary('conv-1', 'Test', 5)];
      mockSync.mockResolvedValue(createSyncResponse(serverConvs));

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      expect(useStore.getState().conversations).toHaveLength(1);
      expect(useStore.getState().conversations[0].id).toBe('conv-1');
      expect(callbacks.onConversationsUpdated).toHaveBeenCalled();
    });

    it('schedules polling after start', async () => {
      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Advance timer past poll interval
      mockSync.mockClear();
      vi.advanceTimersByTime(60000); // 1 minute
      await vi.runOnlyPendingTimersAsync();

      // Should have called incremental sync
      expect(mockSync).toHaveBeenCalled();
    });
  });

  describe('stop', () => {
    it('clears poll timer', async () => {
      syncManager = new SyncManager(callbacks);
      await syncManager.start();
      syncManager.stop();

      mockSync.mockClear();
      vi.advanceTimersByTime(120000); // 2 minutes
      await vi.runOnlyPendingTimersAsync();

      // Should not have called sync after stop
      expect(mockSync).not.toHaveBeenCalled();
    });
  });

  describe('fullSync', () => {
    it('detects deleted conversations', async () => {
      // Set up local conversation that doesn't exist on server
      const localConv = createConversation('local-only', 'Local Only');
      useStore.getState().addConversation(localConv);

      // Server returns empty list
      mockSync.mockResolvedValue(createSyncResponse([]));

      syncManager = new SyncManager(callbacks);
      await syncManager.fullSync();

      // Local conversation should be removed
      expect(useStore.getState().conversations).toHaveLength(0);
    });

    it('shows toast and calls callback when current conversation is deleted', async () => {
      const conv = createConversation('deleted-conv', 'Deleted');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      // Server returns empty list (conversation was deleted)
      mockSync.mockResolvedValue(createSyncResponse([]));

      syncManager = new SyncManager(callbacks);
      await syncManager.fullSync();

      expect(toast.warning).toHaveBeenCalledWith('This conversation was deleted.');
      expect(callbacks.onCurrentConversationDeleted).toHaveBeenCalled();
    });

    it('does not delete temp conversations', async () => {
      const tempConv = createConversation('temp-123', 'Temp Conv');
      useStore.getState().addConversation(tempConv);

      // Server returns empty list
      mockSync.mockResolvedValue(createSyncResponse([]));

      syncManager = new SyncManager(callbacks);
      await syncManager.fullSync();

      // Temp conversation should not be removed
      expect(useStore.getState().conversations).toHaveLength(1);
      expect(useStore.getState().conversations[0].id).toBe('temp-123');
    });
  });

  describe('incrementalSync', () => {
    it('performs full sync if no previous sync time', async () => {
      syncManager = new SyncManager(callbacks);
      // Don't call start, so no lastSyncTime
      await syncManager.incrementalSync();

      // Should perform full sync
      expect(mockSync).toHaveBeenCalledWith(null, true);
    });

    it('uses last sync time for incremental sync', async () => {
      const serverTime = '2024-01-01T12:00:00Z';
      mockSync.mockResolvedValue({
        conversations: [],
        server_time: serverTime,
        is_full_sync: true,
      });

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      mockSync.mockClear();
      mockSync.mockResolvedValue(createSyncResponse([], false));

      await syncManager.incrementalSync();

      expect(mockSync).toHaveBeenCalledWith(serverTime, false);
    });

    it('updates existing conversations', async () => {
      // Set up initial conversation
      const conv = createConversation('conv-1', 'Original', 5);
      useStore.getState().addConversation(conv);

      mockSync.mockResolvedValue(createSyncResponse([], true));
      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Incremental sync returns updated conversation
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('conv-1', 'Updated Title', 10)],
        server_time: '2024-01-01T12:00:00Z',
        is_full_sync: false,
      });

      await syncManager.incrementalSync();

      const updated = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated?.title).toBe('Updated Title');
    });
  });

  describe('unread count calculation', () => {
    it('calculates unread count for non-current conversations', async () => {
      // Add conversation with known message count
      const conv = createConversation('conv-1', 'Test', 5);
      useStore.getState().addConversation(conv);

      // Mark the conversation as read with 5 messages
      mockSync.mockResolvedValue(createSyncResponse([createConversationSummary('conv-1', 'Test', 5)]));
      syncManager = new SyncManager(callbacks);
      await syncManager.start();
      syncManager.markConversationRead('conv-1', 5);

      // Incremental sync shows 8 messages now
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('conv-1', 'Test', 8)],
        server_time: '2024-01-01T12:00:00Z',
        is_full_sync: false,
      });

      await syncManager.incrementalSync();

      const updated = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated?.unreadCount).toBe(3); // 8 - 5 = 3
    });

    it('does not show unread count for current conversation', async () => {
      const conv = createConversation('conv-1', 'Test', 5);
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockSync.mockResolvedValue(createSyncResponse([createConversationSummary('conv-1', 'Test', 5)]));
      syncManager = new SyncManager(callbacks);
      await syncManager.start();
      syncManager.markConversationRead('conv-1', 5);

      // Incremental sync shows 8 messages now
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('conv-1', 'Test', 8)],
        server_time: '2024-01-01T12:00:00Z',
        is_full_sync: false,
      });

      await syncManager.incrementalSync();

      const updated = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated?.unreadCount).toBe(0);
      expect(updated?.hasExternalUpdate).toBe(true);
      expect(callbacks.onCurrentConversationExternalUpdate).toHaveBeenCalledWith(8);
    });

    it('preserves unread count across multiple incremental syncs', async () => {
      // Add conversation with known message count
      const conv = createConversation('conv-1', 'Test', 5);
      useStore.getState().addConversation(conv);

      // Mark the conversation as read with 5 messages
      mockSync.mockResolvedValue(createSyncResponse([createConversationSummary('conv-1', 'Test', 5)]));
      syncManager = new SyncManager(callbacks);
      await syncManager.start();
      syncManager.markConversationRead('conv-1', 5);

      // First incremental sync shows 8 messages (3 unread)
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('conv-1', 'Test', 8)],
        server_time: '2024-01-01T12:00:00Z',
        is_full_sync: false,
      });

      await syncManager.incrementalSync();

      let updated = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated?.unreadCount).toBe(3);

      // Second incremental sync - count should still be 3 (not reset to 0)
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('conv-1', 'Test', 8)],
        server_time: '2024-01-01T12:01:00Z',
        is_full_sync: false,
      });

      await syncManager.incrementalSync();

      updated = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated?.unreadCount).toBe(3); // Should still be 3, not 0
    });

    it('continues tracking new messages while conversation has unread', async () => {
      // Add conversation with known message count
      const conv = createConversation('conv-1', 'Test', 5);
      useStore.getState().addConversation(conv);

      // Mark the conversation as read with 5 messages
      mockSync.mockResolvedValue(createSyncResponse([createConversationSummary('conv-1', 'Test', 5)]));
      syncManager = new SyncManager(callbacks);
      await syncManager.start();
      syncManager.markConversationRead('conv-1', 5);

      // First incremental sync shows 8 messages (3 unread)
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('conv-1', 'Test', 8)],
        server_time: '2024-01-01T12:00:00Z',
        is_full_sync: false,
      });

      await syncManager.incrementalSync();

      let updated = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated?.unreadCount).toBe(3);

      // Third incremental sync - even MORE messages arrive (3 more)
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('conv-1', 'Test', 11)],
        server_time: '2024-01-01T12:02:00Z',
        is_full_sync: false,
      });

      await syncManager.incrementalSync();

      updated = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated?.unreadCount).toBe(6); // 11 - 5 = 6 (original local count preserved)
    });
  });

  describe('markConversationRead', () => {
    it('clears unread count and hasExternalUpdate', async () => {
      // Add conversation with unread count
      const conv = createConversation('conv-1', 'Test', 5);
      conv.unreadCount = 3;
      conv.hasExternalUpdate = true;
      useStore.getState().addConversation(conv);

      // Start sync manager (initializes with existing conversations)
      mockSync.mockResolvedValue(createSyncResponse([createConversationSummary('conv-1', 'Test', 5)]));
      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Mark as read with current message count
      syncManager.markConversationRead('conv-1', 5);

      const updated = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated?.unreadCount).toBe(0);
      expect(updated?.hasExternalUpdate).toBe(false);
      expect(updated?.messageCount).toBe(5);
    });
  });

  describe('incrementLocalMessageCount', () => {
    it('increments local message count', async () => {
      const conv = createConversation('conv-1', 'Test', 5);
      useStore.getState().addConversation(conv);

      mockSync.mockResolvedValue(createSyncResponse([createConversationSummary('conv-1', 'Test', 5)]));
      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      syncManager.incrementLocalMessageCount('conv-1', 2);

      const updated = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated?.messageCount).toBe(7); // 5 + 2
    });
  });

  describe('visibility change handling', () => {
    it('performs full sync after long inactivity', async () => {
      mockSync.mockResolvedValue(createSyncResponse([]));
      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      mockSync.mockClear();

      // Simulate tab becoming hidden
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));

      // Advance time by 6 minutes (> SYNC_FULL_SYNC_THRESHOLD_MS)
      vi.advanceTimersByTime(6 * 60 * 1000);

      // Simulate tab becoming visible
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        writable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));

      await vi.runOnlyPendingTimersAsync();

      // Should have performed full sync (with full=true)
      expect(mockSync).toHaveBeenCalledWith(null, true);
    });

    it('performs incremental sync after short inactivity', async () => {
      const serverTime = '2024-01-01T00:00:00Z';
      mockSync.mockResolvedValue({
        conversations: [],
        server_time: serverTime,
        is_full_sync: true,
      });
      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      mockSync.mockClear();
      mockSync.mockResolvedValue(createSyncResponse([], false));

      // Simulate tab becoming hidden
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));

      // Advance time by 2 minutes (< SYNC_FULL_SYNC_THRESHOLD_MS)
      vi.advanceTimersByTime(2 * 60 * 1000);

      // Simulate tab becoming visible
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        writable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));

      await vi.runOnlyPendingTimersAsync();

      // Should have performed incremental sync (with since timestamp)
      expect(mockSync).toHaveBeenCalledWith(serverTime, false);
    });
  });

  describe('error handling', () => {
    it('continues on sync failure', async () => {
      mockSync.mockRejectedValue(new Error('Network error'));

      syncManager = new SyncManager(callbacks);
      // Should not throw
      await expect(syncManager.fullSync()).resolves.not.toThrow();
    });

    it('does not update state on sync failure', async () => {
      const conv = createConversation('conv-1', 'Test');
      useStore.getState().addConversation(conv);

      mockSync.mockRejectedValue(new Error('Network error'));

      syncManager = new SyncManager(callbacks);
      await syncManager.fullSync();

      // Conversation should still exist
      expect(useStore.getState().conversations).toHaveLength(1);
      expect(callbacks.onConversationsUpdated).not.toHaveBeenCalled();
    });
  });

  describe('concurrent sync prevention', () => {
    it('skips sync if another sync is in progress', async () => {
      // Create a slow sync that resolves after a delay
      let resolveSlowSync: (value: SyncResponse) => void;
      const slowSyncPromise = new Promise<SyncResponse>((resolve) => {
        resolveSlowSync = resolve;
      });
      mockSync.mockReturnValueOnce(slowSyncPromise);

      syncManager = new SyncManager(callbacks);

      // Start first sync (will be slow)
      const firstSync = syncManager.fullSync();

      // Try to start second sync while first is in progress
      mockSync.mockResolvedValueOnce(createSyncResponse([]));
      await syncManager.fullSync();

      // Second sync should have been skipped (only 1 call)
      expect(mockSync).toHaveBeenCalledTimes(1);

      // Complete the first sync
      resolveSlowSync!(createSyncResponse([]));
      await firstSync;
    });

    it('allows sync after previous sync completes', async () => {
      mockSync.mockResolvedValue(createSyncResponse([]));

      syncManager = new SyncManager(callbacks);
      await syncManager.fullSync();
      mockSync.mockClear();

      // Should allow another sync now
      await syncManager.fullSync();
      expect(mockSync).toHaveBeenCalledTimes(1);
    });
  });

  describe('streaming conversation handling', () => {
    it('skips sync updates for streaming conversations', async () => {
      const conv = createConversation('conv-1', 'Test', 5);
      useStore.getState().addConversation(conv);

      mockSync.mockResolvedValue(
        createSyncResponse([createConversationSummary('conv-1', 'Updated Title', 10)])
      );
      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      mockSync.mockClear();

      // Mark conversation as streaming
      syncManager.setConversationStreaming('conv-1', true);

      // Sync should skip updates for this conversation
      mockSync.mockResolvedValue(
        createSyncResponse([createConversationSummary('conv-1', 'Another Update', 15)])
      );
      await syncManager.incrementalSync();

      // Conversation should NOT have been updated (still has old title/count)
      const updated = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated?.title).toBe('Updated Title'); // From initial sync
      expect(updated?.messageCount).toBe(10); // From initial sync
    });

    it('allows sync updates after streaming completes', async () => {
      const conv = createConversation('conv-1', 'Test', 5);
      useStore.getState().addConversation(conv);

      mockSync.mockResolvedValue(
        createSyncResponse([createConversationSummary('conv-1', 'Test', 5)])
      );
      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Mark as streaming then clear it
      syncManager.setConversationStreaming('conv-1', true);
      syncManager.setConversationStreaming('conv-1', false);

      // Sync should now update the conversation
      mockSync.mockResolvedValue(
        createSyncResponse([createConversationSummary('conv-1', 'New Title', 10)])
      );
      await syncManager.incrementalSync();

      const updated = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated?.title).toBe('New Title');
      expect(updated?.messageCount).toBe(10);
    });

    it('allows updates to non-streaming conversations while one is streaming', async () => {
      const conv1 = createConversation('conv-1', 'Test 1', 5);
      const conv2 = createConversation('conv-2', 'Test 2', 3);
      useStore.getState().addConversation(conv1);
      useStore.getState().addConversation(conv2);

      mockSync.mockResolvedValue(
        createSyncResponse([
          createConversationSummary('conv-1', 'Test 1', 5),
          createConversationSummary('conv-2', 'Test 2', 3),
        ])
      );
      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Mark only conv-1 as streaming
      syncManager.setConversationStreaming('conv-1', true);

      // Sync with updates for both
      mockSync.mockResolvedValue(
        createSyncResponse([
          createConversationSummary('conv-1', 'Updated 1', 10),
          createConversationSummary('conv-2', 'Updated 2', 8),
        ])
      );
      await syncManager.incrementalSync();

      // conv-1 should NOT be updated (streaming)
      const updated1 = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated1?.title).toBe('Test 1');
      expect(updated1?.messageCount).toBe(5);

      // conv-2 SHOULD be updated (not streaming)
      const updated2 = useStore.getState().conversations.find((c) => c.id === 'conv-2');
      expect(updated2?.title).toBe('Updated 2');
      expect(updated2?.messageCount).toBe(8);
    });
  });
});
