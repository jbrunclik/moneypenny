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
  planner: {
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
import { conversations as conversationsApi, planner as plannerApi } from '@/api/client';
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
  const mockPlannerSync = plannerApi.sync as ReturnType<typeof vi.fn>;

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
    // Planner sync returns null by default (no planner conversation exists)
    mockPlannerSync.mockResolvedValue({
      conversation: null,
      server_time: new Date().toISOString(),
    });
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

    it('updates existing conversations from server (full sync does not add new ones)', async () => {
      // With the new architecture, full sync only updates existing conversations
      // It does NOT add new conversations - they come via pagination or incremental sync
      const existingConv = createConversation('conv-1', 'Original', 3);
      useStore.getState().addConversation(existingConv);

      const serverConvs = [createConversationSummary('conv-1', 'Updated', 5)];
      mockSync.mockResolvedValue(createSyncResponse(serverConvs));

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Conversation should be updated, not added
      expect(useStore.getState().conversations).toHaveLength(1);
      expect(useStore.getState().conversations[0].id).toBe('conv-1');
      expect(useStore.getState().conversations[0].title).toBe('Updated');
      expect(useStore.getState().conversations[0].messageCount).toBe(5);
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
      // With the new architecture, full sync does NOT add new conversations.
      // It only updates existing conversations and detects deletions.
      // This test verifies that full sync correctly updates existing conversations
      // without adding new ones (which would come via pagination or incremental sync).

      // Initial store has some conversations (simulates paginated load)
      const existingConv = createConversation('existing-conv', 'Existing', 5);
      useStore.getState().addConversation(existingConv);

      // Server returns the existing conversation with updated message count
      const summaries = [
        createConversationSummary('existing-conv', 'Existing', 7), // Updated from 5 to 7
      ];
      summaries[0].updated_at = '2024-01-01T00:00:00Z';

      const syncResponse: SyncResponse = {
        conversations: summaries,
        server_time: '2024-01-01T00:02:00Z',
        is_full_sync: true,
      };

      mockSync.mockResolvedValue(syncResponse);

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // The existing conversation should be updated, not added
      const updatedConv = useStore.getState().conversations.find((c: Conversation) => c.id === 'existing-conv');
      expect(updatedConv).toBeDefined();
      expect(updatedConv?.messageCount).toBe(7); // Updated count
      expect(useStore.getState().conversations).toHaveLength(1); // No new conversations added
    });

    it('updates existing conversations from fullSync without adding new ones', async () => {
      // With the new architecture, full sync does NOT add new conversations.
      // It only updates existing conversations and detects deletions.
      // This test verifies that full sync correctly updates existing conversations
      // without adding new ones (which would come via pagination or incremental sync).

      // Initial store has conversations (simulates paginated load)
      const recentConv = createConversation('recent-conv', 'Recent', 5);
      recentConv.updated_at = '2024-01-10T00:00:00Z';
      useStore.getState().addConversation(recentConv);

      const oldConv = createConversation('old-conv', 'Old', 10);
      oldConv.updated_at = '2024-01-01T00:00:00Z';
      useStore.getState().addConversation(oldConv);

      // Server returns both conversations with updated counts
      const recentSummary = createConversationSummary('recent-conv', 'Recent', 7);
      recentSummary.updated_at = '2024-01-10T00:00:00Z';

      const oldSummary = createConversationSummary('old-conv', 'Old', 12);
      oldSummary.updated_at = '2024-01-01T00:00:00Z';

      mockSync.mockResolvedValue(createSyncResponse([recentSummary, oldSummary]));

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Verify both conversations are updated, not duplicated
      const convs = useStore.getState().conversations;
      expect(convs).toHaveLength(2);

      // Both should be updated with new message counts
      const updatedRecent = convs.find((c) => c.id === 'recent-conv');
      const updatedOld = convs.find((c) => c.id === 'old-conv');
      expect(updatedRecent?.messageCount).toBe(7);
      expect(updatedOld?.messageCount).toBe(12);
    });

    it('full sync does NOT add new conversations (only updates existing ones)', async () => {
      // With the new architecture, full sync only updates existing conversations and detects deletions.
      // It does NOT add new conversations - they come via pagination or incremental sync.

      // Initial store has one conversation
      const conv1 = createConversation('conv-1', 'Conv 1', 3);
      conv1.updated_at = '2024-01-15T00:00:00Z';
      useStore.getState().addConversation(conv1);

      // Server returns multiple conversations, but full sync only updates existing ones
      const summaries = [
        { ...createConversationSummary('conv-1', 'Conv 1', 5), updated_at: '2024-01-15T00:00:00Z' }, // Updated count
        { ...createConversationSummary('conv-2', 'Conv 2', 10), updated_at: '2024-01-12T00:00:00Z' }, // New (not added)
        { ...createConversationSummary('conv-3', 'Conv 3', 5), updated_at: '2024-01-05T00:00:00Z' }, // New (not added)
      ];

      const syncResponse: SyncResponse = {
        conversations: summaries,
        server_time: '2024-01-16T00:02:00Z',
        is_full_sync: true,
      };

      mockSync.mockResolvedValue(syncResponse);

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Verify only existing conversation exists (others not added by full sync)
      const convs = useStore.getState().conversations;
      expect(convs).toHaveLength(1);
      expect(convs[0].id).toBe('conv-1');
      expect(convs[0].messageCount).toBe(5); // Updated count from server
    });

    it('distinguishes pagination-discovered from actually new conversations', async () => {
      // This tests the distinction between:
      // 1. Pagination-discovered: Older conversations that existed before initial page load
      // 2. Actually new: Conversations created/updated after initial page load (e.g., on another device)
      //
      // With the new architecture:
      // - Full sync only updates existing conversations (doesn't add new ones)
      // - Incremental sync adds actually new conversations (not pagination-discovered)
      // - Pagination-discovered conversations come via pagination, not sync
      //
      // The distinction is made by comparing updated_at to initialLoadTime:
      // - If updated_at < initialLoadTime: Pagination-discovered (not added via sync)
      // - If updated_at >= initialLoadTime: Actually new (added via incremental sync)

      // Initial store has one conversation (simulates initial page load)
      const existingConv = createConversation('existing-conv', 'Existing', 5);
      existingConv.updated_at = '2024-01-10T12:00:00Z';
      useStore.getState().addConversation(existingConv);

      // Server time from first full sync (this becomes initialLoadTime)
      const serverTime = '2024-01-10T12:05:00Z'; // 5 minutes after existing conv

      // Full sync only returns existing conversation (doesn't add new ones)
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('existing-conv', 'Existing', 5)],
        server_time: serverTime,
        is_full_sync: true,
      });

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Verify only existing conversation exists after full sync
      expect(useStore.getState().conversations).toHaveLength(1);

      // Incremental sync returns:
      // 1. Pagination-discovered: Older conversation (updated before server time) - NOT added
      // 2. Actually new: Recent conversation (updated after server time) - added
      const paginationConvSummary = createConversationSummary('pagination-conv', 'Pagination Discovered', 10);
      paginationConvSummary.updated_at = '2024-01-10T12:03:00Z'; // Older than server time (pagination-discovered)

      const newConvSummary = createConversationSummary('new-conv', 'Actually New', 15);
      newConvSummary.updated_at = '2024-01-10T12:07:00Z'; // Newer than server time (actually new)

      mockSync.mockResolvedValue({
        conversations: [paginationConvSummary, newConvSummary],
        server_time: '2024-01-10T12:10:00Z',
        is_full_sync: false, // Incremental sync
      });

      await syncManager.incrementalSync();

      // Verify conversations
      const convs = useStore.getState().conversations;
      expect(convs).toHaveLength(2); // existing + actually new (pagination-discovered not added)

      const paginationConv = convs.find((c) => c.id === 'pagination-conv');
      const newConv = convs.find((c) => c.id === 'new-conv');

      // Pagination-discovered should NOT be added (comes via pagination)
      expect(paginationConv).toBeUndefined();

      // Actually new should be added and show unread badge with message count
      expect(newConv).toBeDefined();
      expect(newConv?.unreadCount).toBe(15); // Shows badge with message count
      expect(newConv?.messageCount).toBe(15);
    });

    it('handles boundary case: conversation updated exactly at initialLoadTime - 5 second buffer', async () => {
      // Test the boundary case where updated_at is exactly at the buffer threshold
      // updated_at = initialLoadTime - 5 seconds should be treated as actually new (not <)
      // updated_at = initialLoadTime - 5 seconds - 1 second should be pagination-discovered (<)
      // Note: With new architecture, we test via incremental sync (full sync doesn't add conversations)

      const existingConv = createConversation('existing-conv', 'Existing', 5);
      existingConv.updated_at = '2024-01-10T12:00:00Z';
      useStore.getState().addConversation(existingConv);

      // Initial full sync
      const serverTime = '2024-01-10T12:05:00Z'; // This becomes initialLoadTime
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('existing-conv', 'Existing', 5)],
        server_time: serverTime,
        is_full_sync: true,
      });

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Test case 1: updated_at exactly at buffer boundary (initialLoadTime - 5 seconds)
      // Should be actually new (>= initialLoadTime - buffer) and added via incremental sync
      const boundaryConv1 = createConversationSummary('boundary-conv-1', 'Boundary 1', 10);
      boundaryConv1.updated_at = '2024-01-10T12:04:55Z'; // Exactly 5 seconds before server time

      mockSync.mockResolvedValue({
        conversations: [boundaryConv1],
        server_time: '2024-01-10T12:10:00Z',
        is_full_sync: false, // Incremental sync
      });

      await syncManager.incrementalSync();

      const conv1 = useStore.getState().conversations.find((c) => c.id === 'boundary-conv-1');
      expect(conv1).toBeDefined();
      expect(conv1?.unreadCount).toBe(10); // Actually new (shows badge)

      // Test case 2: updated_at just before buffer boundary (initialLoadTime - 5 seconds - 1 second)
      // Should be pagination-discovered (< initialLoadTime - buffer) and NOT added
      const boundaryConv2 = createConversationSummary('boundary-conv-2', 'Boundary 2', 10);
      boundaryConv2.updated_at = '2024-01-10T12:04:54Z'; // 6 seconds before server time

      mockSync.mockResolvedValue({
        conversations: [boundaryConv2],
        server_time: '2024-01-10T12:15:00Z',
        is_full_sync: false, // Incremental sync
      });

      await syncManager.incrementalSync();

      const conv2 = useStore.getState().conversations.find((c) => c.id === 'boundary-conv-2');
      expect(conv2).toBeUndefined(); // Pagination-discovered (not added, comes via pagination)
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

    it('does NOT add pagination-discovered conversations via incremental sync', async () => {
      // With the new architecture, pagination-discovered conversations (older than initialLoadTime)
      // should NOT be added via sync - they come via pagination when user scrolls.
      // Only actually new conversations (updated after initialLoadTime) are added via incremental sync.

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
      // This should be treated as pagination-discovered and NOT added
      const oldConvSummary = createConversationSummary('old-conv', 'Old Conversation', 10);
      oldConvSummary.updated_at = '2024-01-10T12:03:00Z'; // Before initialLoadTime (12:05)

      mockSync.mockResolvedValue({
        conversations: [oldConvSummary],
        server_time: '2024-01-10T12:10:00Z',
        is_full_sync: false, // Incremental sync
      });

      await syncManager.incrementalSync();

      // Should NOT be added (pagination-discovered, comes via pagination)
      const oldConv = useStore.getState().conversations.find((c) => c.id === 'old-conv');
      expect(oldConv).toBeUndefined();

      // But message count should be tracked for when it does get loaded via pagination
      const trackedCount = (syncManager as any).localMessageCounts.get('old-conv');
      expect(trackedCount).toBe(10);
    });

    it('handles timestamp parsing errors gracefully', async () => {
      // If timestamp parsing fails, should default to pagination-discovered (safe default)
      // Note: With new architecture, full sync doesn't add conversations, so we test via incremental sync

      const existingConv = createConversation('existing-conv', 'Existing', 5);
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

      // Incremental sync: Conversation with invalid timestamp
      const invalidConvSummary = createConversationSummary('invalid-conv', 'Invalid Timestamp', 10);
      invalidConvSummary.updated_at = 'invalid-timestamp'; // Invalid format

      mockSync.mockResolvedValue({
        conversations: [invalidConvSummary],
        server_time: '2024-01-10T12:10:00Z',
        is_full_sync: false, // Incremental sync
      });

      await syncManager.incrementalSync();

      // Should default to pagination-discovered (safe default, no false unread badge)
      // And should NOT be added (pagination-discovered conversations come via pagination)
      const invalidConv = useStore.getState().conversations.find((c) => c.id === 'invalid-conv');
      expect(invalidConv).toBeUndefined(); // Not added (pagination-discovered, comes via pagination)
    });

    it('correctly updates unread count for actually new conversation when more messages arrive', async () => {
      // Race condition: Actually new conversation discovered, then more messages arrive before user views it
      // The unread count should correctly reflect the total message count

      const existingConv = createConversation('existing-conv', 'Existing', 5);
      existingConv.updated_at = '2024-01-10T12:00:00Z';
      useStore.getState().addConversation(existingConv);

      // Initial full sync: Only updates existing conversations (doesn't add new ones)
      const serverTime1 = '2024-01-10T12:05:00Z';
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('existing-conv', 'Existing', 5)],
        server_time: serverTime1,
        is_full_sync: true,
      });

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Incremental sync: Discover actually new conversation with 10 messages
      const newConvSummary1 = createConversationSummary('new-conv', 'New Conversation', 10);
      newConvSummary1.updated_at = '2024-01-10T12:07:00Z'; // After initialLoadTime

      mockSync.mockResolvedValue({
        conversations: [newConvSummary1],
        server_time: '2024-01-10T12:08:00Z',
        is_full_sync: false, // Incremental sync
      });

      await syncManager.incrementalSync();

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
      // Note: With new architecture, pagination-discovered conversations are NOT added via sync
      // They come via pagination when user scrolls. This test verifies that when they DO get
      // loaded via pagination, subsequent syncs correctly update their unread counts.

      const existingConv = createConversation('existing-conv', 'Existing', 5);
      existingConv.updated_at = '2024-01-10T12:00:00Z';
      useStore.getState().addConversation(existingConv);

      // Initial full sync: Only updates existing conversations
      const serverTime1 = '2024-01-10T12:05:00Z';
      mockSync.mockResolvedValue({
        conversations: [createConversationSummary('existing-conv', 'Existing', 5)],
        server_time: serverTime1,
        is_full_sync: true,
      });

      syncManager = new SyncManager(callbacks);
      await syncManager.start();

      // Simulate user scrolling and loading old conversation via pagination
      // (In real app, this would be via appendConversations from pagination)
      const oldConv = createConversation('old-conv', 'Old Conversation', 10);
      oldConv.updated_at = '2024-01-10T12:03:00Z'; // Before initialLoadTime
      useStore.getState().addConversation(oldConv);
      syncManager.markConversationRead('old-conv', 10); // User views it, marks as read

      // Verify it's in the store (loaded via pagination)
      const oldConv1 = useStore.getState().conversations.find((c) => c.id === 'old-conv');
      expect(oldConv1).toBeDefined();
      expect(oldConv1?.messageCount).toBe(10);

      // Incremental sync: More messages arrive (now 15 total)
      const oldConvSummary2 = createConversationSummary('old-conv', 'Old Conversation', 15);
      oldConvSummary2.updated_at = '2024-01-10T12:08:00Z'; // Updated

      mockSync.mockResolvedValue({
        conversations: [oldConvSummary2],
        server_time: '2024-01-10T12:10:00Z',
        is_full_sync: false, // Incremental sync
      });

      await syncManager.incrementalSync();

      // Unread count should show new messages (15 - 10 = 5)
      // localMessageCount was set to 10 when user marked it as read
      const oldConv2 = useStore.getState().conversations.find((c) => c.id === 'old-conv');
      expect(oldConv2?.unreadCount).toBe(5); // New messages since last read
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
