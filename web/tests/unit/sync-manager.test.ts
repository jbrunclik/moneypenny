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

    it('does NOT trigger external update callback when current conversation is streaming', async () => {
      // This tests the specific scenario: user is viewing a conversation, streaming is active,
      // sync happens and sees new message count. Should NOT show "new messages available" banner.
      const conv = createConversation('conv-1', 'Test', 5);
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockSync.mockResolvedValue(createSyncResponse([createConversationSummary('conv-1', 'Test', 5)]));
      syncManager = new SyncManager(callbacks);
      await syncManager.start();
      syncManager.markConversationRead('conv-1', 5);

      // Mark conversation as streaming (simulates user sent a message, streaming response)
      syncManager.setConversationStreaming('conv-1', true);

      // Server reports increased message count (user message was saved to DB)
      // This is the exact scenario that was causing false "new messages" banners
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('conv-1', 'Test', 6)],
        server_time: '2024-01-01T12:00:00Z',
        is_full_sync: false,
      });

      await syncManager.incrementalSync();

      // External update callback should NOT have been called
      expect(callbacks.onCurrentConversationExternalUpdate).not.toHaveBeenCalled();

      // Conversation state should not have changed (streaming skip)
      const updated = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated?.messageCount).toBe(5); // Still 5, not updated
      expect(updated?.hasExternalUpdate).toBeFalsy();
    });

    it('does NOT trigger external update callback during visibility change while streaming', async () => {
      // Same as above but triggered by visibility change (tab refocus)
      const conv = createConversation('conv-1', 'Test', 5);
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      const serverTime = '2024-01-01T00:00:00Z';
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('conv-1', 'Test', 5)],
        server_time: serverTime,
        is_full_sync: true,
      });
      syncManager = new SyncManager(callbacks);
      await syncManager.start();
      syncManager.markConversationRead('conv-1', 5);

      // Mark conversation as streaming
      syncManager.setConversationStreaming('conv-1', true);

      mockSync.mockClear();
      vi.mocked(callbacks.onCurrentConversationExternalUpdate).mockClear();

      // Simulate visibility change (short duration = incremental sync)
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('conv-1', 'Test', 6)],
        server_time: '2024-01-01T12:00:00Z',
        is_full_sync: false,
      });

      // Simulate tab becoming hidden briefly
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));

      // Short delay
      vi.advanceTimersByTime(1000);

      // Simulate tab becoming visible again
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        writable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));

      await vi.runOnlyPendingTimersAsync();

      // External update callback should NOT have been called during streaming
      expect(callbacks.onCurrentConversationExternalUpdate).not.toHaveBeenCalled();
    });

    it('does NOT trigger external update when message count incremented before clearing streaming flag', async () => {
      // This tests the race condition fix: when streaming completes, the message count
      // must be incremented BEFORE clearing the streaming flag. Otherwise, if sync happens
      // between clearing flag and incrementing count, it sees old local count vs new server
      // count and incorrectly shows "new messages available" banner.

      const conv = createConversation('conv-1', 'Test', 5);
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockSync.mockResolvedValue(createSyncResponse([createConversationSummary('conv-1', 'Test', 5)]));
      syncManager = new SyncManager(callbacks);
      await syncManager.start();
      syncManager.markConversationRead('conv-1', 5);

      // Mark conversation as streaming (user sent message)
      syncManager.setConversationStreaming('conv-1', true);

      // Streaming completes - increment count FIRST (simulates fix in finally block)
      syncManager.incrementLocalMessageCount('conv-1', 2); // User msg + assistant msg = 7 now
      // THEN clear streaming flag
      syncManager.setConversationStreaming('conv-1', false);

      // Sync happens immediately after streaming completes
      // Server reports 7 messages (user msg + assistant msg added)
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('conv-1', 'Test', 7)],
        server_time: '2024-01-01T12:00:00Z',
        is_full_sync: false,
      });

      await syncManager.incrementalSync();

      // Should NOT trigger external update callback - counts match!
      expect(callbacks.onCurrentConversationExternalUpdate).not.toHaveBeenCalled();

      // Conversation should be up to date
      const updated = useStore.getState().conversations.find((c: Conversation) => c.id === 'conv-1');
      expect(updated?.messageCount).toBe(7);
      expect(updated?.hasExternalUpdate).toBeFalsy();
      expect(updated?.unreadCount).toBe(0);
    });

    it('WOULD trigger external update if count incremented AFTER clearing streaming flag (race condition)', async () => {
      // This test demonstrates the bug scenario: if we clear streaming flag BEFORE incrementing
      // the local count, a sync happening in between would see mismatched counts.
      // This is kept as a documentation test to show why the fix order matters.

      const conv = createConversation('conv-1', 'Test', 5);
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockSync.mockResolvedValue(createSyncResponse([createConversationSummary('conv-1', 'Test', 5)]));
      syncManager = new SyncManager(callbacks);
      await syncManager.start();
      syncManager.markConversationRead('conv-1', 5);

      // Mark conversation as streaming (user sent message)
      syncManager.setConversationStreaming('conv-1', true);

      // BUG SCENARIO: Clear streaming flag FIRST (wrong order!)
      syncManager.setConversationStreaming('conv-1', false);

      // Sync happens BEFORE incrementLocalMessageCount gets called
      // Server reports 7 messages but local count is still 5
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('conv-1', 'Test', 7)],
        server_time: '2024-01-01T12:00:00Z',
        is_full_sync: false,
      });

      await syncManager.incrementalSync();

      // This WOULD trigger the external update (the bug!)
      expect(callbacks.onCurrentConversationExternalUpdate).toHaveBeenCalledWith(7);

      // Now increment count (too late, banner already shown)
      syncManager.incrementLocalMessageCount('conv-1', 2);
    });
  });

  describe('pagination scenario handling', () => {
    it('does NOT show false unread badge for conversations discovered via fullSync', async () => {
      // This tests the bug where conversations beyond the initial paginated load
      // get false unread badges.
      //
      // Scenario:
      // 1. Initial page load fetches first 30 conversations (newest first)
      // 2. Store is populated with these 30 conversations
      // 3. SyncManager.start() initializes localMessageCounts from store (30 entries)
      // 4. SyncManager.fullSync() returns ALL conversations (e.g., 50)
      // 5. For the 20 conversations NOT in the initial load:
      //    - They're not in localMessageCounts (defaults to 0)
      //    - If message_count > 0, unreadCount = message_count - 0 = FALSE POSITIVE!
      //
      // The fix: When adding NEW conversations via sync (not existing in store),
      // initialize localMessageCounts to server's count to prevent false unread.

      // Initial store has some conversations (simulates paginated load)
      const existingConv = createConversation('existing-conv', 'Existing', 5);
      useStore.getState().addConversation(existingConv);

      // Server returns both existing AND new conversation (discovered via fullSync)
      // The new conversation has 14 messages but user has never seen it
      // Set updated_at to be older than server time to make it pagination-discovered
      const summaries = [
        createConversationSummary('existing-conv', 'Existing', 5),
        createConversationSummary('new-conv', 'New Conversation', 14),
      ];
      summaries[0].updated_at = '2024-01-01T00:00:00Z';
      summaries[1].updated_at = '2024-01-01T00:00:00Z'; // Same as server time, but will be treated as pagination-discovered

      // Create sync response with server time slightly after the conversation timestamps
      const syncResponse: SyncResponse = {
        conversations: summaries,
        server_time: '2024-01-01T00:02:00Z', // 2 minutes after, so conversation is pagination-discovered
        is_full_sync: true,
      };

      mockSync.mockResolvedValue(syncResponse);

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // The NEW conversation should NOT have an unread badge
      // (it's not "unread" - user just hasn't scrolled to see it yet)
      const newConv = useStore.getState().conversations.find((c: Conversation) => c.id === 'new-conv');
      expect(newConv).toBeDefined();
      expect(newConv?.unreadCount).toBe(0); // NOT 14!
      expect(newConv?.messageCount).toBe(14); // Message count is still tracked
    });

    it('inserts conversations from fullSync in correct sorted position (not prepended)', async () => {
      // This tests the ordering bug where conversations discovered via fullSync
      // get prepended to the top of the list instead of being inserted at
      // the correct sorted position.
      //
      // Conversations should be ordered by updated_at DESC (newest first).
      // When a sync discovers an OLD conversation, it should be inserted
      // at the END of the list (or appropriate position), not at the TOP.

      // Initial store has a recent conversation
      const recentConv = createConversation('recent-conv', 'Recent', 5);
      recentConv.updated_at = '2024-01-10T00:00:00Z'; // Recent
      useStore.getState().addConversation(recentConv);

      // Server returns both recent AND old conversation
      const recentSummary = createConversationSummary('recent-conv', 'Recent', 5);
      recentSummary.updated_at = '2024-01-10T00:00:00Z';

      const oldSummary = createConversationSummary('old-conv', 'Old Conversation', 14);
      oldSummary.updated_at = '2024-01-01T00:00:00Z'; // Much older

      mockSync.mockResolvedValue(createSyncResponse([recentSummary, oldSummary]));

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Verify both conversations exist
      const convs = useStore.getState().conversations;
      expect(convs).toHaveLength(2);

      // The OLD conversation should be at the END (index 1), not the TOP (index 0)
      expect(convs[0].id).toBe('recent-conv'); // Recent first
      expect(convs[1].id).toBe('old-conv'); // Old last
    });

    it('handles multiple new conversations from fullSync with correct ordering', async () => {
      // More complex scenario with multiple new conversations

      // Initial store has one conversation
      const conv1 = createConversation('conv-1', 'Conv 1', 3);
      conv1.updated_at = '2024-01-15T00:00:00Z'; // Most recent
      useStore.getState().addConversation(conv1);

      // Server returns 4 conversations with varying timestamps
      // All are older than server time to make them pagination-discovered
      const summaries = [
        { ...createConversationSummary('conv-1', 'Conv 1', 3), updated_at: '2024-01-15T00:00:00Z' },
        { ...createConversationSummary('conv-2', 'Conv 2', 10), updated_at: '2024-01-12T00:00:00Z' },
        { ...createConversationSummary('conv-3', 'Conv 3', 5), updated_at: '2024-01-05T00:00:00Z' },
        { ...createConversationSummary('conv-4', 'Conv 4', 20), updated_at: '2024-01-01T00:00:00Z' },
      ];

      // Create sync response with server time after all conversation timestamps
      // This makes all conversations pagination-discovered (older than initialLoadTime - 1 minute buffer)
      const syncResponse: SyncResponse = {
        conversations: summaries,
        server_time: '2024-01-16T00:02:00Z', // 2 minutes after latest timestamp (ensures > 1 minute buffer)
        is_full_sync: true,
      };

      mockSync.mockResolvedValue(syncResponse);

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Verify all conversations exist
      const convs = useStore.getState().conversations;
      expect(convs).toHaveLength(4);

      // They should be ordered by updated_at DESC
      expect(convs[0].id).toBe('conv-1'); // Jan 15 - newest
      expect(convs[1].id).toBe('conv-2'); // Jan 12
      expect(convs[2].id).toBe('conv-3'); // Jan 5
      expect(convs[3].id).toBe('conv-4'); // Jan 1 - oldest

      // All new conversations are pagination-discovered (older than server time)
      // so they should have no unread badges
      expect(convs[1].unreadCount).toBe(0); // conv-2 has 10 messages but NO badge (pagination-discovered)
      expect(convs[2].unreadCount).toBe(0); // conv-3 has 5 messages but NO badge (pagination-discovered)
      expect(convs[3].unreadCount).toBe(0); // conv-4 has 20 messages but NO badge (pagination-discovered)
    });

    it('distinguishes pagination-discovered from actually new conversations', async () => {
      // This tests the distinction between:
      // 1. Pagination-discovered: Older conversations that existed before initial page load
      // 2. Actually new: Conversations created/updated after initial page load (e.g., on another device)
      //
      // The distinction is made by comparing updated_at to initialLoadTime:
      // - If updated_at < initialLoadTime: Pagination-discovered
      // - If updated_at >= initialLoadTime: Actually new

      // Initial store has one conversation (simulates initial page load)
      const existingConv = createConversation('existing-conv', 'Existing', 5);
      existingConv.updated_at = '2024-01-10T12:00:00Z';
      useStore.getState().addConversation(existingConv);

      // Server time from first full sync (this becomes initialLoadTime)
      const serverTime = '2024-01-10T12:05:00Z'; // 5 minutes after existing conv

      // Server returns:
      // 1. Existing conversation (already in store)
      // 2. Pagination-discovered: Older conversation (updated before server time)
      // 3. Actually new: Recent conversation (updated after server time)
      const summaries = [
        createConversationSummary('existing-conv', 'Existing', 5),
        createConversationSummary('pagination-conv', 'Pagination Discovered', 10),
        createConversationSummary('new-conv', 'Actually New', 15),
      ];

      // Set timestamps: pagination-discovered is older, actually new is newer
      summaries[0].updated_at = '2024-01-10T12:00:00Z'; // Existing
      summaries[1].updated_at = '2024-01-10T12:03:00Z'; // Older than server time (pagination-discovered)
      summaries[2].updated_at = '2024-01-10T12:07:00Z'; // Newer than server time (actually new)

      // Create sync response with custom server time
      const syncResponse: SyncResponse = {
        conversations: summaries,
        server_time: serverTime,
        is_full_sync: true,
      };

      mockSync.mockResolvedValue(syncResponse);

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Verify all conversations exist
      const convs = useStore.getState().conversations;
      expect(convs).toHaveLength(3);

      const paginationConv = convs.find((c) => c.id === 'pagination-conv');
      const newConv = convs.find((c) => c.id === 'new-conv');

      expect(paginationConv).toBeDefined();
      expect(newConv).toBeDefined();

      // Pagination-discovered should have no unread badge (user just hasn't scrolled to it)
      expect(paginationConv?.unreadCount).toBe(0);
      expect(paginationConv?.messageCount).toBe(10);

      // Actually new should show unread badge with message count
      expect(newConv?.unreadCount).toBe(15); // Shows badge with message count
      expect(newConv?.messageCount).toBe(15);
    });

    it('handles boundary case: conversation updated exactly at initialLoadTime - 1 minute buffer', async () => {
      // Test the boundary case where updated_at is exactly at the buffer threshold
      // updated_at = initialLoadTime - 1 minute should be treated as actually new (not <)
      // updated_at = initialLoadTime - 1 minute - 1 second should be pagination-discovered (<)

      const existingConv = createConversation('existing-conv', 'Existing', 5);
      existingConv.updated_at = '2024-01-10T12:00:00Z';
      useStore.getState().addConversation(existingConv);

      const serverTime = '2024-01-10T12:05:00Z'; // This becomes initialLoadTime

      // Test case 1: updated_at exactly at buffer boundary (initialLoadTime - 1 minute)
      // Should be actually new (>= initialLoadTime - buffer)
      const summaries1 = [
        createConversationSummary('existing-conv', 'Existing', 5),
        createConversationSummary('boundary-conv-1', 'Boundary 1', 10),
      ];
      summaries1[0].updated_at = '2024-01-10T12:00:00Z';
      summaries1[1].updated_at = '2024-01-10T12:04:00Z'; // Exactly 1 minute before server time

      const syncResponse1: SyncResponse = {
        conversations: summaries1,
        server_time: serverTime,
        is_full_sync: true,
      };

      mockSync.mockResolvedValue(syncResponse1);
      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      const conv1 = useStore.getState().conversations.find((c) => c.id === 'boundary-conv-1');
      expect(conv1?.unreadCount).toBe(10); // Actually new (shows badge)

      // Reset for second test
      syncManager.stop();
      resetStore();

      // Test case 2: updated_at just before buffer boundary (initialLoadTime - 1 minute - 1 second)
      // Should be pagination-discovered (< initialLoadTime - buffer)
      const summaries2 = [
        createConversationSummary('boundary-conv-2', 'Boundary 2', 10),
      ];
      summaries2[0].updated_at = '2024-01-10T12:03:59Z'; // 1 minute 1 second before server time

      const syncResponse2: SyncResponse = {
        conversations: summaries2,
        server_time: serverTime,
        is_full_sync: true,
      };

      mockSync.mockResolvedValue(syncResponse2);
      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      const conv2 = useStore.getState().conversations.find((c) => c.id === 'boundary-conv-2');
      expect(conv2?.unreadCount).toBe(0); // Pagination-discovered (no badge)
    });

    it('preserves initialLoadTime across multiple full syncs', async () => {
      // initialLoadTime should only be set once (on first full sync)
      // Subsequent full syncs should not change it

      const serverTime1 = '2024-01-10T12:00:00Z';
      const serverTime2 = '2024-01-10T13:00:00Z'; // 1 hour later

      // First full sync
      mockSync.mockResolvedValue({
        conversations: [],
        server_time: serverTime1,
        is_full_sync: true,
      });

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Verify initialLoadTime is set
      const firstSyncTime = (syncManager as any).initialLoadTime;
      expect(firstSyncTime).toBe(serverTime1);

      // Second full sync (e.g., after tab hidden >5 minutes)
      mockSync.mockResolvedValue({
        conversations: [],
        server_time: serverTime2,
        is_full_sync: true,
      });

      await syncManager.fullSync();

      // initialLoadTime should still be the original value
      const secondSyncTime = (syncManager as any).initialLoadTime;
      expect(secondSyncTime).toBe(serverTime1); // Still the first sync time, not the second
    });

    it('treats all incremental sync conversations as actually new', async () => {
      // Incremental syncs only return conversations updated since lastSyncTime,
      // so they should all be treated as actually new (even if they're old)

      const existingConv = createConversation('existing-conv', 'Existing', 5);
      existingConv.updated_at = '2024-01-10T12:00:00Z';
      useStore.getState().addConversation(existingConv);

      // Initial full sync
      const serverTime1 = '2024-01-10T12:05:00Z';
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('existing-conv', 'Existing', 5)],
        server_time: serverTime1,
        is_full_sync: true,
      });

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Mark as read
      syncManager.markConversationRead('existing-conv', 5);

      // Incremental sync returns an old conversation (updated before initialLoadTime)
      // But since it's in incremental sync, it should be treated as actually new
      const oldConvSummary = createConversationSummary('old-conv', 'Old Conversation', 10);
      oldConvSummary.updated_at = '2024-01-10T12:03:00Z'; // Before initialLoadTime (12:05)

      mockSync.mockResolvedValue({
        conversations: [oldConvSummary],
        server_time: '2024-01-10T12:10:00Z',
        is_full_sync: false, // Incremental sync
      });

      await syncManager.incrementalSync();

      const oldConv = useStore.getState().conversations.find((c) => c.id === 'old-conv');
      expect(oldConv).toBeDefined();
      // Even though it's old, incremental sync treats it as actually new
      expect(oldConv?.unreadCount).toBe(10); // Shows badge (treated as actually new)
    });

    it('handles timestamp parsing errors gracefully', async () => {
      // If timestamp parsing fails, should default to pagination-discovered (safe default)

      const existingConv = createConversation('existing-conv', 'Existing', 5);
      useStore.getState().addConversation(existingConv);

      const serverTime = '2024-01-10T12:05:00Z';

      // Create a conversation with invalid timestamp
      const summaries = [
        createConversationSummary('existing-conv', 'Existing', 5),
        createConversationSummary('invalid-conv', 'Invalid Timestamp', 10),
      ];
      summaries[0].updated_at = '2024-01-10T12:00:00Z';
      summaries[1].updated_at = 'invalid-timestamp'; // Invalid format

      const syncResponse: SyncResponse = {
        conversations: summaries,
        server_time: serverTime,
        is_full_sync: true,
      };

      mockSync.mockResolvedValue(syncResponse);
      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Should default to pagination-discovered (safe default, no false unread badge)
      const invalidConv = useStore.getState().conversations.find((c) => c.id === 'invalid-conv');
      expect(invalidConv).toBeDefined();
      expect(invalidConv?.unreadCount).toBe(0); // Defaults to pagination-discovered
    });

    it('correctly updates unread count for actually new conversation when more messages arrive', async () => {
      // Race condition: Actually new conversation discovered, then more messages arrive before user views it
      // The unread count should correctly reflect the total message count

      const existingConv = createConversation('existing-conv', 'Existing', 5);
      existingConv.updated_at = '2024-01-10T12:00:00Z';
      useStore.getState().addConversation(existingConv);

      // First sync: Discover actually new conversation with 10 messages
      const serverTime1 = '2024-01-10T12:05:00Z';
      const newConvSummary1 = createConversationSummary('new-conv', 'New Conversation', 10);
      newConvSummary1.updated_at = '2024-01-10T12:07:00Z'; // After initialLoadTime

      mockSync.mockResolvedValue({
        conversations: [
          createConversationSummary('existing-conv', 'Existing', 5),
          newConvSummary1,
        ],
        server_time: serverTime1,
        is_full_sync: true,
      });

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Verify it's treated as actually new (shows badge with 10 messages)
      const newConv1 = useStore.getState().conversations.find((c) => c.id === 'new-conv');
      expect(newConv1?.unreadCount).toBe(10);
      expect(newConv1?.messageCount).toBe(10);

      // Second sync: More messages arrive (now 15 total)
      const newConvSummary2 = createConversationSummary('new-conv', 'New Conversation', 15);
      newConvSummary2.updated_at = '2024-01-10T12:08:00Z'; // Updated

      mockSync.mockResolvedValue({
        conversations: [newConvSummary2],
        server_time: '2024-01-10T12:10:00Z',
        is_full_sync: false, // Incremental sync
      });

      await syncManager.incrementalSync();

      // Unread count should update to reflect new total (15 - 0 = 15)
      // localMessageCount was initialized to 0 for actually new conversations
      // and should NOT be updated when unreadCount > 0 (preserves unread state)
      const newConv2 = useStore.getState().conversations.find((c) => c.id === 'new-conv');
      expect(newConv2?.unreadCount).toBe(15); // All messages are unread (user hasn't viewed it)
      expect(newConv2?.messageCount).toBe(15);
    });

    it('correctly updates unread count for pagination-discovered conversation when more messages arrive', async () => {
      // Race condition: Pagination-discovered conversation, then more messages arrive
      // The unread count should correctly reflect new messages

      const existingConv = createConversation('existing-conv', 'Existing', 5);
      existingConv.updated_at = '2024-01-10T12:00:00Z';
      useStore.getState().addConversation(existingConv);

      // First sync: Discover pagination-discovered conversation with 10 messages
      const serverTime1 = '2024-01-10T12:05:00Z';
      const oldConvSummary1 = createConversationSummary('old-conv', 'Old Conversation', 10);
      oldConvSummary1.updated_at = '2024-01-10T12:03:00Z'; // Before initialLoadTime (pagination-discovered)

      mockSync.mockResolvedValue({
        conversations: [
          createConversationSummary('existing-conv', 'Existing', 5),
          oldConvSummary1,
        ],
        server_time: serverTime1,
        is_full_sync: true,
      });

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Verify it's treated as pagination-discovered (no badge)
      const oldConv1 = useStore.getState().conversations.find((c) => c.id === 'old-conv');
      expect(oldConv1?.unreadCount).toBe(0);
      expect(oldConv1?.messageCount).toBe(10);

      // Second sync: More messages arrive (now 15 total)
      const oldConvSummary2 = createConversationSummary('old-conv', 'Old Conversation', 15);
      oldConvSummary2.updated_at = '2024-01-10T12:08:00Z'; // Updated

      mockSync.mockResolvedValue({
        conversations: [oldConvSummary2],
        server_time: '2024-01-10T12:10:00Z',
        is_full_sync: false, // Incremental sync
      });

      await syncManager.incrementalSync();

      // Unread count should show new messages (15 - 10 = 5)
      // localMessageCount was initialized to 10 for pagination-discovered conversations
      const oldConv2 = useStore.getState().conversations.find((c) => c.id === 'old-conv');
      expect(oldConv2?.unreadCount).toBe(5); // New messages since discovery
      expect(oldConv2?.messageCount).toBe(15);
    });

    it('uses correct total count when marking conversation as read (not paginated count)', async () => {
      // This tests the critical pagination bug: when opening an existing conversation
      // with pagination, we must use the TOTAL message count from the API response,
      // not the length of the paginated messages array.
      //
      // Scenario:
      // 1. Conversation has 100 messages on server
      // 2. Pagination returns only 50 messages
      // 3. If we call markConversationRead(convId, 50) - WRONG!
      // 4. After streaming adds 2 messages and server has 102, sync sees:
      //    - localCount: 52 (50 + 2 from streaming)
      //    - serverCount: 102
      //    - Difference detected -> false "new messages" banner!
      //
      // Correct behavior: markConversationRead(convId, 100) - using total_count

      const conv = createConversation('conv-1', 'Test', 100);
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockSync.mockResolvedValue(
        createSyncResponse([createConversationSummary('conv-1', 'Test', 100)])
      );
      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // CORRECT: Mark as read with TOTAL count (100), not paginated count (50)
      syncManager.markConversationRead('conv-1', 100);

      // User sends a message, streaming begins
      syncManager.setConversationStreaming('conv-1', true);

      // Streaming completes - increment count FIRST
      syncManager.incrementLocalMessageCount('conv-1', 2); // Now 102 local
      // THEN clear streaming flag
      syncManager.setConversationStreaming('conv-1', false);

      // Sync happens - server reports 102 messages
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('conv-1', 'Test', 102)],
        server_time: '2024-01-01T12:00:00Z',
        is_full_sync: false,
      });

      await syncManager.incrementalSync();

      // Should NOT trigger external update - counts match (102 == 102)
      expect(callbacks.onCurrentConversationExternalUpdate).not.toHaveBeenCalled();

      const updated = useStore.getState().conversations.find((c: Conversation) => c.id === 'conv-1');
      expect(updated?.messageCount).toBe(102);
      expect(updated?.hasExternalUpdate).toBeFalsy();
    });

    it('WOULD show false banner if paginated count used instead of total (documents the bug)', async () => {
      // This test documents the bug that occurred before the fix:
      // Using conv.messages.length (paginated) instead of total_count

      const conv = createConversation('conv-1', 'Test', 100);
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockSync.mockResolvedValue(
        createSyncResponse([createConversationSummary('conv-1', 'Test', 100)])
      );
      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // BUG: Mark as read with PAGINATED count (50) instead of total (100)
      syncManager.markConversationRead('conv-1', 50);

      // User sends a message, streaming begins
      syncManager.setConversationStreaming('conv-1', true);

      // Streaming completes correctly
      syncManager.incrementLocalMessageCount('conv-1', 2); // Now 52 local (WRONG baseline!)
      syncManager.setConversationStreaming('conv-1', false);

      // Sync happens - server reports 102 messages
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('conv-1', 'Test', 102)],
        server_time: '2024-01-01T12:00:00Z',
        is_full_sync: false,
      });

      await syncManager.incrementalSync();

      // BUG MANIFESTS: External update triggered because 102 > 52
      expect(callbacks.onCurrentConversationExternalUpdate).toHaveBeenCalledWith(102);

      const updated = useStore.getState().conversations.find((c: Conversation) => c.id === 'conv-1');
      expect(updated?.hasExternalUpdate).toBe(true);
    });
  });
});
