/**
 * Unit tests for SyncManager
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import type { AgentStatsBlock, Conversation, ConversationSummary, SyncResponse } from '@/types/api';

// Mock the API client
vi.mock('@/api/conversations', () => ({
  conversations: {
    sync: vi.fn(),
    syncChanges: vi.fn(),
    markRead: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock('@/api/planner', () => ({
  planner: {
    sync: vi.fn(),
  },
}));

vi.mock('@/api/agents', () => ({
  agents: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    syncConversation: vi.fn(),
    getCommandCenter: vi.fn().mockResolvedValue({
      agents: [],
      pending_approvals: [],
      recent_executions: [],
      total_unread: 0,
      agents_waiting: 0,
      agents_with_errors: 0,
    }),
  },
  aiAssist: {
    parseSchedule: vi.fn(),
    enhancePrompt: vi.fn(),
  },
}));

// Import after mocks are set up
import { SyncManager } from '@/sync/SyncManager';
import type { StreamRecoveryHooks, SyncManagerCallbacks, SyncNotifier } from '@/sync/sync-state';
import { conversations as conversationsApi } from '@/api/conversations';
import { planner as plannerApi } from '@/api/planner';
import { agents as agentsApi } from '@/api/agents';
import { attemptRecovery, cancelRecovery, hasPendingRecovery, markStreamForRecovery } from '@/core/stream-recovery';

// The notifier core/startup passes in (the UI's toast)
const toast = { info: vi.fn(), warning: vi.fn() } satisfies SyncNotifier;

const RECOVERY: StreamRecoveryHooks = {
  hasPending: hasPendingRecovery,
  attempt: attemptRecovery,
  cancel: cancelRecovery,
};

function at<T>(items: ArrayLike<T>, i: number): T {
  const item = items[i];
  if (item === undefined) throw new Error(`no item at index ${i}`);
  return item;
}

const EMPTY_AGENT_STATS: AgentStatsBlock = {
  days: 7,
  total_runs: 0,
  total_completed: 0,
  total_failed: 0,
  total_cost_usd: 0,
  total_cost_display: '$0.00',
  per_agent: [],
};

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
      maxVideoFileSize: 100 * 1024 * 1024,
      maxFilesPerMessage: 10,
      allowedFileTypes: [],
    },
    appVersion: null,
    newVersionAvailable: false,
    versionBannerDismissed: false,
    notifications: [],
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
    ...(messageCount !== undefined && { messageCount }),
  };
}

// Helper to create a mock conversation summary (from sync API): every field
// the server sends; read on some device up to `readCount` (default: all read)
function createConversationSummary(
  id: string,
  title: string,
  messageCount: number,
  readCount: number = messageCount
): ConversationSummary {
  return {
    id,
    title,
    model: 'gemini-3-flash-preview',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    message_count: messageCount,
    read_count: readCount,
    last_message_preview: null,
    last_message_id: null,
    archived: false,
    trashed: false,
    pinned: false,
    anonymous_mode: false,
  };
}

// Helper to create a mock full sync response (with the change-log cursor)
function createSyncResponse(conversations: ConversationSummary[]): SyncResponse {
  return {
    conversations,
    server_time: '2024-01-01T00:00:00Z',
    cursor: 1,
    removed_ids: [],
    has_more: false,
  };
}

// Helper to create a change-log page (an incremental sync after the cursor)
function changePage(conversations: ConversationSummary[], extra: Partial<SyncResponse> = {}): SyncResponse {
  return {
    conversations,
    server_time: '2024-01-01T12:00:00Z',
    cursor: 2,
    removed_ids: [],
    has_more: false,
    ...extra,
  };
}

describe('SyncManager', () => {
  let syncManager: SyncManager;
  let callbacks: SyncManagerCallbacks;
  const mockSync = conversationsApi.sync as ReturnType<typeof vi.fn>;
  const mockSyncChanges = conversationsApi.syncChanges as ReturnType<typeof vi.fn>;
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

    // Default mock implementation: an empty full sync, then no changes
    mockSync.mockResolvedValue(createSyncResponse([]));
    mockSyncChanges.mockResolvedValue(changePage([]));
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

      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      expect(mockSync).toHaveBeenCalledWith();
    });

    it('updates existing conversations from server (full sync does not add new ones)', async () => {
      // With the new architecture, full sync only updates existing conversations
      // It does NOT add new conversations - they come via pagination or incremental sync
      const existingConv = createConversation('conv-1', 'Original', 3);
      useStore.getState().addConversation(existingConv);

      const serverConvs = [createConversationSummary('conv-1', 'Updated', 5)];
      mockSync.mockResolvedValue(createSyncResponse(serverConvs));

      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      // Conversation should be updated, not added
      expect(useStore.getState().conversations).toHaveLength(1);
      expect(useStore.getState().conversations[0]?.id).toBe('conv-1');
      expect(useStore.getState().conversations[0]?.title).toBe('Updated');
      expect(useStore.getState().conversations[0]?.messageCount).toBe(5);
      expect(callbacks.onConversationsUpdated).toHaveBeenCalled();
    });

    it('schedules polling after start', async () => {
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      // Advance timer past poll interval
      mockSyncChanges.mockClear();
      vi.advanceTimersByTime(60000); // 1 minute
      await vi.runOnlyPendingTimersAsync();

      // Should have called incremental sync (the change log after the cursor)
      expect(mockSyncChanges).toHaveBeenCalled();
    });
  });

  describe('stop', () => {
    it('clears poll timer', async () => {
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
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

      syncManager = new SyncManager(callbacks, RECOVERY, toast);
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

      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.fullSync();

      expect(toast.warning).toHaveBeenCalledWith('This conversation was deleted.');
      expect(callbacks.onCurrentConversationDeleted).toHaveBeenCalled();
    });

    it('does not delete temp conversations', async () => {
      const tempConv = createConversation('temp-123', 'Temp Conv');
      useStore.getState().addConversation(tempConv);

      // Server returns empty list
      mockSync.mockResolvedValue(createSyncResponse([]));

      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.fullSync();

      // Temp conversation should not be removed
      expect(useStore.getState().conversations).toHaveLength(1);
      expect(useStore.getState().conversations[0]?.id).toBe('temp-123');
    });
  });

  describe('incrementalSync', () => {
    it('performs a full sync while there is no cursor yet', async () => {
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      // Not started: no full sync has returned a cursor yet
      await syncManager.incrementalSync();

      // Should perform full sync
      expect(mockSync).toHaveBeenCalledWith();
    });

    it('asks for the changes after the cursor the full sync returned', async () => {
      mockSync.mockResolvedValue({ ...createSyncResponse([]), cursor: 41 });
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      mockSync.mockClear();
      await syncManager.incrementalSync();

      expect(mockSyncChanges).toHaveBeenCalledWith(41);
      expect(mockSync).not.toHaveBeenCalled();
    });

    it('updates existing conversations', async () => {
      // Set up initial conversation
      const conv = createConversation('conv-1', 'Original', 5);
      useStore.getState().addConversation(conv);

      mockSync.mockResolvedValue(createSyncResponse([]));
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      // Incremental sync returns updated conversation
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'Updated Title', 10)], { server_time: '2024-01-01T12:00:00Z' }))

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
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();
      syncManager.markConversationRead('conv-1', 5);

      // Incremental sync shows 8 messages now
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'Test', 8, 5)], { server_time: '2024-01-01T12:00:00Z' }))

      await syncManager.incrementalSync();

      const updated = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated?.unreadCount).toBe(3); // 8 - 5 = 3
    });

    it('does not show unread count for current conversation', async () => {
      const conv = createConversation('conv-1', 'Test', 5);
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      mockSync.mockResolvedValue(createSyncResponse([createConversationSummary('conv-1', 'Test', 5)]));
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();
      syncManager.markConversationRead('conv-1', 5);

      // Incremental sync shows 8 messages now
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'Test', 8, 5)], { server_time: '2024-01-01T12:00:00Z' }))

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
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();
      syncManager.markConversationRead('conv-1', 5);

      // First incremental sync shows 8 messages (3 unread)
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'Test', 8, 5)], { server_time: '2024-01-01T12:00:00Z' }))

      await syncManager.incrementalSync();

      let updated = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated?.unreadCount).toBe(3);

      // Second incremental sync - count should still be 3 (not reset to 0)
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'Test', 8, 5)], { server_time: '2024-01-01T12:01:00Z' }))

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
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();
      syncManager.markConversationRead('conv-1', 5);

      // First incremental sync shows 8 messages (3 unread)
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'Test', 8, 5)], { server_time: '2024-01-01T12:00:00Z' }))

      await syncManager.incrementalSync();

      let updated = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated?.unreadCount).toBe(3);

      // Third incremental sync - even MORE messages arrive (3 more)
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'Test', 11, 5)], { server_time: '2024-01-01T12:02:00Z' }))

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
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
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
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      syncManager.incrementLocalMessageCount('conv-1', 2);

      const updated = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(updated?.messageCount).toBe(7); // 5 + 2
    });
  });

  describe('visibility change handling', () => {
    it('performs full sync after long inactivity', async () => {
      mockSync.mockResolvedValue(createSyncResponse([]));
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
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
      expect(mockSync).toHaveBeenCalledWith();
    });

    it('performs incremental sync after short inactivity', async () => {
      const serverTime = '2024-01-01T00:00:00Z';
      mockSync.mockResolvedValue({ ...createSyncResponse([]), server_time: serverTime })
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      mockSyncChanges.mockClear();
      mockSyncChanges.mockResolvedValue(changePage([]));

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

      // Should have performed incremental sync (the changes after the cursor)
      expect(mockSyncChanges).toHaveBeenCalledWith(1);
    });
  });

  describe('error handling', () => {
    it('continues on sync failure', async () => {
      mockSync.mockRejectedValue(new Error('Network error'));

      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      // Should not throw
      await expect(syncManager.fullSync()).resolves.not.toThrow();
    });

    it('does not update state on sync failure', async () => {
      const conv = createConversation('conv-1', 'Test');
      useStore.getState().addConversation(conv);

      mockSync.mockRejectedValue(new Error('Network error'));

      syncManager = new SyncManager(callbacks, RECOVERY, toast);
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

      syncManager = new SyncManager(callbacks, RECOVERY, toast);

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

      syncManager = new SyncManager(callbacks, RECOVERY, toast);
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
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      mockSync.mockClear();

      // Mark conversation as streaming
      syncManager.setConversationStreaming('conv-1', true);

      // Sync should skip updates for this conversation
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'Another Update', 15)]));
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
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      // Mark as streaming then clear it
      syncManager.setConversationStreaming('conv-1', true);
      syncManager.setConversationStreaming('conv-1', false);

      // Sync should now update the conversation
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'New Title', 10)]));
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
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      // Mark only conv-1 as streaming
      syncManager.setConversationStreaming('conv-1', true);

      // Sync with updates for both
      mockSyncChanges.mockResolvedValue(changePage([
          createConversationSummary('conv-1', 'Updated 1', 10),
          createConversationSummary('conv-2', 'Updated 2', 8),
        ]));
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
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();
      syncManager.markConversationRead('conv-1', 5);

      // Mark conversation as streaming (simulates user sent a message, streaming response)
      syncManager.setConversationStreaming('conv-1', true);

      // Server reports increased message count (user message was saved to DB)
      // This is the exact scenario that was causing false "new messages" banners
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'Test', 6)], { server_time: '2024-01-01T12:00:00Z' }))

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
      mockSync.mockResolvedValue({ ...createSyncResponse([createConversationSummary('conv-1', 'Test', 5)]), server_time: serverTime })
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();
      syncManager.markConversationRead('conv-1', 5);

      // Mark conversation as streaming
      syncManager.setConversationStreaming('conv-1', true);

      mockSync.mockClear();
      vi.mocked(callbacks.onCurrentConversationExternalUpdate).mockClear();

      // Simulate visibility change (short duration = incremental sync)
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'Test', 6)], { server_time: '2024-01-01T12:00:00Z' }))

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
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
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
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'Test', 7)], { server_time: '2024-01-01T12:00:00Z' }))

      await syncManager.incrementalSync();

      // The change log hands the open chat the server's count, which matches
      // what it shows (7): no "new messages" state
      expect(callbacks.onCurrentConversationExternalUpdate).toHaveBeenCalledWith(7);

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
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();
      syncManager.markConversationRead('conv-1', 5);

      // Mark conversation as streaming (user sent message)
      syncManager.setConversationStreaming('conv-1', true);

      // BUG SCENARIO: Clear streaming flag FIRST (wrong order!)
      syncManager.setConversationStreaming('conv-1', false);

      // Sync happens BEFORE incrementLocalMessageCount gets called
      // Server reports 7 messages but local count is still 5
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'Test', 7)], { server_time: '2024-01-01T12:00:00Z' }))

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
      at(summaries, 0).updated_at = '2024-01-01T00:00:00Z';

      const syncResponse: SyncResponse = {
        conversations: summaries,
        server_time: '2024-01-01T00:02:00Z',
        cursor: 1,
        removed_ids: [],
        has_more: false,
      };

      mockSync.mockResolvedValue(syncResponse);

      syncManager = new SyncManager(callbacks, RECOVERY, toast);
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

      syncManager = new SyncManager(callbacks, RECOVERY, toast);
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

    it('full sync does NOT add conversations older than the loaded part of the list', async () => {
      // Older ones come via pagination; only those inside the loaded window
      // (new / continued / restored elsewhere) are added

      // Initial store has one conversation, and the list has more pages
      const conv1 = createConversation('conv-1', 'Conv 1', 3);
      conv1.updated_at = '2024-01-15T00:00:00Z';
      useStore.getState().addConversation(conv1);
      useStore.setState({
        conversationsPagination: { ...useStore.getState().conversationsPagination, hasMore: true },
      });

      // Server returns multiple conversations, but full sync only updates existing ones
      const summaries = [
        { ...createConversationSummary('conv-1', 'Conv 1', 5), updated_at: '2024-01-15T00:00:00Z' }, // Updated count
        { ...createConversationSummary('conv-2', 'Conv 2', 10), updated_at: '2024-01-12T00:00:00Z' }, // New (not added)
        { ...createConversationSummary('conv-3', 'Conv 3', 5), updated_at: '2024-01-05T00:00:00Z' }, // New (not added)
      ];

      const syncResponse: SyncResponse = {
        conversations: summaries,
        server_time: '2024-01-16T00:02:00Z',
        cursor: 1,
        removed_ids: [],
        has_more: false,
      };

      mockSync.mockResolvedValue(syncResponse);

      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      // Verify only existing conversation exists (others not added by full sync)
      const convs = useStore.getState().conversations;
      expect(convs).toHaveLength(1);
      expect(convs[0]?.id).toBe('conv-1');
      expect(convs[0]?.messageCount).toBe(5); // Updated count from server
    });

    it('preserves initialLoadTime across multiple full syncs', async () => {
      // initialLoadTime should only be set once (on first full sync)
      // Subsequent full syncs should not change it

      const serverTime1 = '2024-01-10T12:00:00Z';
      const serverTime2 = '2024-01-10T13:00:00Z'; // 1 hour later

      // First full sync
      mockSync.mockResolvedValue({ ...createSyncResponse([]), server_time: serverTime1 })

      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      // Verify initialLoadTime is set
      const firstSyncTime = (syncManager as unknown as { state: { initialLoadTime: string } }).state.initialLoadTime;
      expect(firstSyncTime).toBe(serverTime1);

      // Second full sync (e.g., after tab hidden >5 minutes)
      mockSync.mockResolvedValue({ ...createSyncResponse([]), server_time: serverTime2 })

      await syncManager.fullSync();

      // initialLoadTime should still be the original value
      const secondSyncTime = (syncManager as unknown as { state: { initialLoadTime: string } }).state.initialLoadTime;
      expect(secondSyncTime).toBe(serverTime1); // Still the first sync time, not the second
    });

    it('handles timestamp parsing errors gracefully', async () => {
      // If timestamp parsing fails, should default to pagination-discovered (safe default)
      // Note: With new architecture, full sync doesn't add conversations, so we test via incremental sync

      const existingConv = createConversation('existing-conv', 'Existing', 5);
      useStore.getState().addConversation(existingConv);

      // Initial full sync
      const serverTime1 = '2024-01-10T12:05:00Z';
      mockSync.mockResolvedValue({ ...createSyncResponse([createConversationSummary('existing-conv', 'Existing', 5)]), server_time: serverTime1 })

      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      // Incremental sync: Conversation with invalid timestamp
      const invalidConvSummary = createConversationSummary('invalid-conv', 'Invalid Timestamp', 10);
      invalidConvSummary.updated_at = 'invalid-timestamp'; // Invalid format

      mockSyncChanges.mockResolvedValue(changePage([invalidConvSummary], { server_time: '2024-01-10T12:10:00Z' }))

      await syncManager.incrementalSync();

      // Should default to pagination-discovered (safe default, no false unread badge)
      // And should NOT be added (pagination-discovered conversations come via pagination)
      const invalidConv = useStore.getState().conversations.find((c) => c.id === 'invalid-conv');
      expect(invalidConv).toBeUndefined(); // Not added (pagination-discovered, comes via pagination)
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
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
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
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'Test', 102)], { server_time: '2024-01-01T12:00:00Z' }))

      await syncManager.incrementalSync();

      // The open chat is handed the total (102), which matches what it shows
      expect(callbacks.onCurrentConversationExternalUpdate).toHaveBeenCalledWith(102);

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
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      // BUG: Mark as read with PAGINATED count (50) instead of total (100)
      syncManager.markConversationRead('conv-1', 50);

      // User sends a message, streaming begins
      syncManager.setConversationStreaming('conv-1', true);

      // Streaming completes correctly
      syncManager.incrementLocalMessageCount('conv-1', 2); // Now 52 local (WRONG baseline!)
      syncManager.setConversationStreaming('conv-1', false);

      // Sync happens - server reports 102 messages
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'Test', 102)], { server_time: '2024-01-01T12:00:00Z' }))

      await syncManager.incrementalSync();

      // BUG MANIFESTS: External update triggered because 102 > 52
      expect(callbacks.onCurrentConversationExternalUpdate).toHaveBeenCalledWith(102);

      const updated = useStore.getState().conversations.find((c: Conversation) => c.id === 'conv-1');
      expect(updated?.hasExternalUpdate).toBe(true);
    });
  });

  describe('multi-device glitches (Oct 2026)', () => {
    it('a conversation continued on another device shows only its new messages as unread', async () => {
      // Known from the full sync (not loaded in the sidebar page), 10 messages
      const old = createConversationSummary('old-conv', 'Yesterday', 10);
      old.updated_at = '2024-01-09T08:00:00Z';
      mockSync.mockResolvedValue({ ...createSyncResponse([old]), server_time: '2024-01-10T12:00:00Z' })
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      // ...then continued elsewhere: +2 messages no device has shown yet (a
      // scheduled agent's reply), now updated
      const continued = createConversationSummary('old-conv', 'Yesterday', 12, 10);
      continued.updated_at = '2024-01-10T12:01:00Z';
      mockSyncChanges.mockResolvedValue(changePage([continued], { server_time: '2024-01-10T12:02:00Z' }))
      await syncManager.incrementalSync();

      const conv = useStore.getState().conversations.find((c) => c.id === 'old-conv');
      expect(conv?.unreadCount).toBe(2);
    });

    it('applies a change that arrived during this device\'s own turn once the turn ends', async () => {
      useStore.getState().addConversation(createConversation('conv-1', 'Test', 4));
      mockSync.mockResolvedValue(createSyncResponse([createConversationSummary('conv-1', 'Test', 4)]));
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      syncManager.setConversationStreaming('conv-1', true);
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'Renamed elsewhere', 6)]));
      await syncManager.incrementalSync();
      // The poll's cursor has moved past the change; nothing re-sends it
      mockSyncChanges.mockResolvedValue(changePage([]));

      syncManager.setLocalMessageCount('conv-1', 6);
      syncManager.setConversationStreaming('conv-1', false);

      const conv = useStore.getState().conversations.find((c) => c.id === 'conv-1');
      expect(conv?.title).toBe('Renamed elsewhere');
      expect(conv?.unreadCount ?? 0).toBe(0);
    });

    it('takes the server\'s exact count after its own turn (no +2 drift on regenerate)', async () => {
      useStore.getState().addConversation(createConversation('conv-1', 'Test', 6));
      mockSync.mockResolvedValue(createSyncResponse([createConversationSummary('conv-1', 'Test', 6)]));
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      // A regenerate replaced the last reply: the server count stays 6
      syncManager.setLocalMessageCount('conv-1', 6);
      // The other device then adds a turn nobody has read yet
      mockSyncChanges.mockResolvedValue(changePage([createConversationSummary('conv-1', 'Test', 8, 6)]));
      await syncManager.incrementalSync();

      expect(useStore.getState().conversations.find((c) => c.id === 'conv-1')?.unreadCount).toBe(2);
    });

    it('runs a full sync requested while another sync holds the lock', async () => {
      let release: (value: SyncResponse) => void;
      mockSync.mockReturnValueOnce(new Promise<SyncResponse>((resolve) => (release = resolve)));
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      const first = syncManager.fullSync();

      mockSync.mockResolvedValue(createSyncResponse([]));
      const queued = syncManager.fullSync();
      release!(createSyncResponse([]));
      await first;
      await queued;
      await vi.runOnlyPendingTimersAsync();

      expect(mockSync).toHaveBeenCalledTimes(2);
    });

    it('syncs when the device comes back online', async () => {
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();
      mockSync.mockClear();

      window.dispatchEvent(new Event('online'));
      // Not the regular poll: no timer advance beyond the current tick
      await vi.advanceTimersByTimeAsync(0);

      expect(mockSync).toHaveBeenCalled();
    });

    it('does not report this device\'s own planner messages as external', async () => {
      useStore.setState({ isPlannerView: true, currentConversation: { ...createConversation('planner-1', 'Planner', 2) } });
      mockPlannerSync.mockResolvedValue({
        conversation: { id: 'planner-1', message_count: 2, last_reset: null },
        server_time: new Date().toISOString(),
      });
      callbacks.onPlannerExternalUpdate = vi.fn();
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();
      await syncManager.incrementalSync(); // baseline 2

      // Own turn in the planner: server now has 4
      syncManager.setLocalMessageCount('planner-1', 4);
      mockPlannerSync.mockResolvedValue({
        conversation: { id: 'planner-1', message_count: 4, last_reset: null },
        server_time: new Date().toISOString(),
      });
      await syncManager.incrementalSync();

      expect(callbacks.onPlannerExternalUpdate).not.toHaveBeenCalled();
    });
  });

  describe('change-log (cursor) sync', () => {
    const mockSyncChanges = (): ReturnType<typeof vi.fn> =>
      conversationsApi.syncChanges as unknown as ReturnType<typeof vi.fn>;

    function changes(
      conversations: ConversationSummary[],
      extra: Partial<SyncResponse> = {}
    ): SyncResponse {
      return { conversations, server_time: '2024-01-10T12:10:00Z', cursor: 20, removed_ids: [], has_more: false, ...extra };
    }

    async function startWithCursor(convs: Conversation[]): Promise<void> {
      for (const c of convs) useStore.getState().addConversation(c);
      mockSync.mockResolvedValue({ ...createSyncResponse(convs.map((c) => createConversationSummary(c.id, c.title, c.messageCount ?? 0))), server_time: '2024-01-10T12:00:00Z', cursor: 10 })
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();
    }

    it('asks for the changes after the full sync\'s cursor, then after the returned one', async () => {
      await startWithCursor([createConversation('a', 'A', 2)]);
      mockSyncChanges().mockResolvedValue(changes([]));

      await syncManager.incrementalSync();
      await syncManager.incrementalSync();

      expect(mockSyncChanges().mock.calls.map(([c]) => c)).toEqual([10, 20]);
    });

    it('removes a conversation archived or trashed on another device without a full sync', async () => {
      await startWithCursor([createConversation('a', 'A', 2), createConversation('t', 'T', 2)]);
      mockSyncChanges().mockResolvedValue(
        changes([
          { ...createConversationSummary('a', 'A', 2), archived: true },
          { ...createConversationSummary('t', 'T', 2), trashed: true },
        ])
      );

      await syncManager.incrementalSync();

      expect(useStore.getState().conversations).toHaveLength(0);
      expect(callbacks.onConversationsUpdated).toHaveBeenCalled();
    });

    it('closes the open conversation when it is deleted elsewhere, keeps it open when archived', async () => {
      const open = createConversation('open', 'Open', 2);
      await startWithCursor([open, createConversation('other', 'Other', 2)]);
      useStore.getState().setCurrentConversation(open);

      mockSyncChanges().mockResolvedValue(changes([{ ...createConversationSummary('open', 'Open', 2), archived: true }]));
      await syncManager.incrementalSync();
      expect(useStore.getState().currentConversation?.archived).toBe(true);
      expect(callbacks.onCurrentConversationDeleted).not.toHaveBeenCalled();

      useStore.getState().setCurrentConversation(at(useStore.getState().conversations, 0));
      mockSyncChanges().mockResolvedValue(changes([], { removed_ids: ['other'] }));
      await syncManager.incrementalSync();
      expect(callbacks.onCurrentConversationDeleted).toHaveBeenCalled();
      expect(toast.warning).toHaveBeenCalledWith('This conversation was deleted on another device.');
    });

    describe('archive and trash lists', () => {
      const pagination = { total_count: 1, has_more: false, next_cursor: null };

      beforeEach(() => {
        callbacks.onArchiveOrTrashChanged = vi.fn();
      });

      it('refreshes the archive when a chat is archived elsewhere, the trash when trashed', async () => {
        await startWithCursor([createConversation('a', 'A', 2), createConversation('t', 'T', 2)]);
        mockSyncChanges().mockResolvedValue(
          changes([{ ...createConversationSummary('a', 'A', 2), archived: true }])
        );
        await syncManager.incrementalSync();
        expect(callbacks.onArchiveOrTrashChanged).toHaveBeenLastCalledWith({ archive: true, trash: false });

        mockSyncChanges().mockResolvedValue(changes([{ ...createConversationSummary('t', 'T', 2), trashed: true }]));
        await syncManager.incrementalSync();
        expect(callbacks.onArchiveOrTrashChanged).toHaveBeenLastCalledWith({ archive: false, trash: true });
      });

      it('refreshes the list a chat left: unarchived, restored or deleted for good elsewhere', async () => {
        await startWithCursor([]);
        useStore.getState().setArchivedConversations([createConversation('arch', 'Arch', 2)], pagination);
        useStore.getState().setTrashedConversations([createConversation('tr', 'Tr', 2), createConversation('gone', 'Gone', 2)], { ...pagination, total_count: 2 });

        mockSyncChanges().mockResolvedValue(changes([createConversationSummary('arch', 'Arch', 2)]));
        await syncManager.incrementalSync();
        expect(callbacks.onArchiveOrTrashChanged).toHaveBeenLastCalledWith({ archive: true, trash: false });

        mockSyncChanges().mockResolvedValue(changes([createConversationSummary('tr', 'Tr', 2)]));
        await syncManager.incrementalSync();
        expect(callbacks.onArchiveOrTrashChanged).toHaveBeenLastCalledWith({ archive: false, trash: true });

        mockSyncChanges().mockResolvedValue(changes([], { removed_ids: ['gone'] }));
        await syncManager.incrementalSync();
        expect(callbacks.onArchiveOrTrashChanged).toHaveBeenLastCalledWith({ archive: false, trash: true });
      });

      it("leaves the lists alone when they already agree (this device's own change echoing back)", async () => {
        await startWithCursor([createConversation('a', 'A', 2)]);
        useStore.getState().setArchivedConversations([createConversation('arch', 'Arch', 2)], pagination);
        useStore.getState().setTrashedConversations([createConversation('tr', 'Tr', 2)], pagination);
        mockSyncChanges().mockResolvedValue(
          changes([
            { ...createConversationSummary('arch', 'Arch', 2), archived: true },
            { ...createConversationSummary('tr', 'Tr', 2), trashed: true },
            createConversationSummary('a', 'A', 3),
          ])
        );

        await syncManager.incrementalSync();

        expect(callbacks.onArchiveOrTrashChanged).not.toHaveBeenCalled();
      });

      it('skips a chat changed on this device while the poll was in flight', async () => {
        await startWithCursor([]);
        useStore.getState().setArchivedConversations([createConversation('arch', 'Arch', 2)], pagination);
        // The unarchive here is in flight: the poll's stale "archived" is ours to ignore
        mockSyncChanges().mockImplementation(async () => {
          syncManager.noteLocalChange('x');
          return changes([{ ...createConversationSummary('x', 'X', 2), archived: true }]);
        });

        await syncManager.incrementalSync();

        expect(callbacks.onArchiveOrTrashChanged).not.toHaveBeenCalled();
      });
    });

    it('adds a restored conversation back without an unread badge', async () => {
      await startWithCursor([createConversation('a', 'A', 2)]);
      const restored = { ...createConversationSummary('r', 'Restored', 8), created_at: '2023-12-01T00:00:00Z' };
      mockSyncChanges().mockResolvedValue(changes([restored]));

      await syncManager.incrementalSync();

      const conv = useStore.getState().conversations.find((c) => c.id === 'r');
      expect(conv).toBeDefined();
      expect(conv?.unreadCount).toBe(0);
    });

    it('a change to a chat older than the loaded list is tracked, not added', async () => {
      const loaded = { ...createConversation('a', 'A', 2), updated_at: '2024-01-10T11:00:00Z' };
      await startWithCursor([loaded]);
      useStore.setState({
        conversationsPagination: { ...useStore.getState().conversationsPagination, hasMore: true },
      });
      // Changed elsewhere, but older than the oldest loaded row: pagination brings it
      const older = { ...createConversationSummary('old', 'Old', 7, 5), updated_at: '2023-12-01T08:00:00Z' };
      mockSyncChanges().mockResolvedValue(changes([older]));

      await syncManager.incrementalSync();

      expect(useStore.getState().conversations.map((c) => c.id)).toEqual(['a']);
    });

    it('a changed chat inside the loaded list joins it with the server unread count', async () => {
      const loaded = { ...createConversation('a', 'A', 2), updated_at: '2024-01-10T11:00:00Z' };
      await startWithCursor([loaded]);
      useStore.setState({
        conversationsPagination: { ...useStore.getState().conversationsPagination, hasMore: true },
      });
      const recent = { ...createConversationSummary('r', 'Recent', 7, 5), updated_at: '2024-01-10T12:05:00Z' };
      mockSyncChanges().mockResolvedValue(changes([recent]));

      await syncManager.incrementalSync();

      expect(useStore.getState().conversations.find((c) => c.id === 'r')?.unreadCount).toBe(2);
    });

    it('a pinned chat joins the list even when it is older than the loaded part', async () => {
      const loaded = { ...createConversation('a', 'A', 2), updated_at: '2024-01-10T11:00:00Z' };
      await startWithCursor([loaded]);
      useStore.setState({
        conversationsPagination: { ...useStore.getState().conversationsPagination, hasMore: true },
      });
      const pinned = { ...createConversationSummary('p', 'Pinned', 3), pinned: true, updated_at: '2024-01-01T00:00:00Z' };
      mockSyncChanges().mockResolvedValue(changes([pinned]));

      await syncManager.incrementalSync();

      expect(useStore.getState().conversations.some((c) => c.id === 'p')).toBe(true);
    });

    it('a conversation created on another device is all unread', async () => {
      await startWithCursor([createConversation('a', 'A', 2)]);
      // Nobody has read it yet (e.g. an agent's first run)
      const created = { ...createConversationSummary('n', 'New', 2, 0), created_at: '2024-01-10T12:05:00Z', updated_at: '2024-01-10T12:05:00Z' };
      mockSyncChanges().mockResolvedValue(changes([created]));

      await syncManager.incrementalSync();

      expect(useStore.getState().conversations.find((c) => c.id === 'n')?.unreadCount).toBe(2);
    });

    it('applies a pin from another device', async () => {
      await startWithCursor([createConversation('a', 'A', 2)]);
      mockSyncChanges().mockResolvedValue(changes([{ ...createConversationSummary('a', 'A', 2), pinned: true }]));

      await syncManager.incrementalSync();

      expect(useStore.getState().conversations.find((c) => c.id === 'a')?.pinned).toBe(true);
    });

    it('a conversation deleted on another device cancels its pending stream recovery', async () => {
      await startWithCursor([createConversation('a', 'A', 2)]);
      markStreamForRecovery('a', 'msg-1', 'partial', 'network');
      mockSyncChanges().mockResolvedValue(changes([], { removed_ids: ['a'] }));

      await syncManager.incrementalSync();

      expect(hasPendingRecovery('a')).toBe(false);
    });

    it('unread badges follow the server read state shared by all devices', async () => {
      await startWithCursor([createConversation('a', 'A', 2)]);
      // 4 messages, all already shown on the phone: not unread here
      mockSyncChanges().mockResolvedValue(changes([{ ...createConversationSummary('a', 'A', 4), read_count: 4 }]));
      await syncManager.incrementalSync();
      expect(useStore.getState().conversations.find((c) => c.id === 'a')?.unreadCount ?? 0).toBe(0);

      mockSyncChanges().mockResolvedValue(changes([{ ...createConversationSummary('a', 'A', 6), read_count: 4 }]));
      await syncManager.incrementalSync();
      expect(useStore.getState().conversations.find((c) => c.id === 'a')?.unreadCount).toBe(2);
    });

    it('viewing a conversation reports it read to the server (once per count)', async () => {
      const markRead = conversationsApi.markRead as unknown as ReturnType<typeof vi.fn>;
      await startWithCursor([createConversation('a', 'A', 2)]);
      markRead.mockClear();

      syncManager.markConversationRead('a', 6);
      syncManager.markConversationRead('a', 6);

      expect(markRead.mock.calls).toEqual([['a', 6]]);
    });

    it('our own turn finishing while switched away leaves the reply unread', async () => {
      const markRead = conversationsApi.markRead as unknown as ReturnType<typeof vi.fn>;
      await startWithCursor([createConversation('a', 'A', 2), createConversation('b', 'B', 2)]);
      useStore.getState().setCurrentConversation(useStore.getState().conversations.find((c) => c.id === 'b')!);
      markRead.mockClear();

      syncManager.setLocalMessageCount('a', 4);

      expect(markRead).toHaveBeenCalledWith('a', 3);
    });

    it('a snapshot from during our own turn never overwrites what the turn set', async () => {
      await startWithCursor([createConversation('a', 'New Conversation', 0)]);
      syncManager.setConversationStreaming('a', true);
      mockSyncChanges().mockResolvedValueOnce(changes([createConversationSummary('a', 'New Conversation', 2)]));
      await syncManager.incrementalSync();

      // The turn's done event names it; the turn ends
      useStore.getState().updateConversation('a', { title: 'Cinema trip' });
      mockSyncChanges().mockResolvedValueOnce(changes([createConversationSummary('a', 'Cinema trip', 2)]));
      syncManager.setLocalMessageCount('a', 2);
      syncManager.setConversationStreaming('a', false);
      await vi.advanceTimersByTimeAsync(0);

      expect(useStore.getState().conversations.find((c) => c.id === 'a')?.title).toBe('Cinema trip');
      expect(mockSyncChanges()).toHaveBeenCalledTimes(2);
    });

    it('a full sync never "deletes" a conversation created while it was in flight', async () => {
      await startWithCursor([createConversation('a', 'A', 2)]);
      let respond!: (r: SyncResponse) => void;
      mockSync.mockReturnValueOnce(new Promise<SyncResponse>((resolve) => (respond = resolve)));
      const full = syncManager.fullSync();

      // Meanwhile this device creates (or restores/unarchives) one
      const created = createConversation('new', 'Just created', 2);
      useStore.getState().addConversation(created);
      useStore.getState().setCurrentConversation(created);
      respond({ ...createSyncResponse([createConversationSummary('a', 'A', 2)]), server_time: '2024-01-10T12:00:00Z', cursor: 10 });
      await full;

      expect(useStore.getState().conversations.some((c) => c.id === 'new')).toBe(true);
      expect(callbacks.onCurrentConversationDeleted).not.toHaveBeenCalled();
    });

    it('an open archived chat merges its changes and never toasts "archived on another device"', async () => {
      await startWithCursor([createConversation('a', 'A', 2)]);
      const archived = { ...createConversation('arch', 'Old', 2), archived: true };
      useStore.getState().setCurrentConversation(archived);
      mockSyncChanges().mockResolvedValue(changes([{ ...createConversationSummary('arch', 'Old', 4), archived: true }]));

      await syncManager.incrementalSync();

      expect(toast.info).not.toHaveBeenCalled();
      expect(callbacks.onCurrentConversationExternalUpdate).toHaveBeenCalledWith(4);
    });

    it('an open chat outside the loaded sidebar list still merges remote changes', async () => {
      await startWithCursor([createConversation('a', 'A', 2)]);
      useStore.getState().setCurrentConversation(createConversation('deep', 'From search', 2));
      mockSyncChanges().mockResolvedValue(changes([{ ...createConversationSummary('deep', 'From search', 4), created_at: '2023-01-01T00:00:00Z' }]));

      await syncManager.incrementalSync();

      expect(callbacks.onCurrentConversationExternalUpdate).toHaveBeenCalled();
    });

    it('a bfcache restore that skipped visibilitychange resumes polling', async () => {
      await startWithCursor([createConversation('a', 'A', 2)]);
      const visible = (): boolean => (syncManager as unknown as { isVisible: boolean }).isVisible;
      Object.defineProperty(document, 'visibilityState', { value: 'hidden', writable: true });
      document.dispatchEvent(new Event('visibilitychange'));
      expect(visible()).toBe(false); // polls are skipped while hidden

      // Restored without a visibilitychange back to "visible"
      Object.defineProperty(document, 'visibilityState', { value: 'visible', writable: true });
      window.dispatchEvent(Object.assign(new Event('pageshow'), { persisted: true }));

      expect(visible()).toBe(true);
    });


    it('a poll requested before a local rename never re-applies the old title', async () => {
      await startWithCursor([createConversation('a', 'Old title', 2)]);
      let respond!: (r: SyncResponse) => void;
      mockSyncChanges().mockReturnValueOnce(new Promise<SyncResponse>((resolve) => (respond = resolve)));
      const poll = syncManager.incrementalSync();

      // Renamed here while that poll is in flight
      syncManager.noteLocalChange('a');
      useStore.getState().updateConversation('a', { title: 'Mine' });
      respond(changes([createConversationSummary('a', 'Old title', 2)]));
      await poll;

      expect(useStore.getState().conversations.find((c) => c.id === 'a')?.title).toBe('Mine');
    });

    it('an incremental sync requested during another one is queued, not dropped', async () => {
      await startWithCursor([createConversation('a', 'A', 2)]);
      let respond!: (r: SyncResponse) => void;
      mockSyncChanges().mockReturnValueOnce(new Promise<SyncResponse>((resolve) => (respond = resolve)));
      const first = syncManager.incrementalSync();
      mockSyncChanges().mockResolvedValue(changes([]));
      await syncManager.incrementalSync(); // e.g. "a turn just ended - fetch its state"
      respond(changes([]));
      await first;
      await vi.advanceTimersByTimeAsync(0);

      expect(mockSyncChanges()).toHaveBeenCalledTimes(2);
    });

    it("another device's rename during our own turn survives the turn's end", async () => {
      await startWithCursor([createConversation('a', 'Chat', 2)]);
      syncManager.setConversationStreaming('a', true);
      // Polled after our final save: the cursor moves past this change
      mockSyncChanges().mockResolvedValueOnce(changes([createConversationSummary('a', 'Renamed on the phone', 4)]));
      await syncManager.incrementalSync();
      mockSyncChanges().mockResolvedValue(changes([]));

      syncManager.setLocalMessageCount('a', 4);
      syncManager.setConversationStreaming('a', false);
      await vi.advanceTimersByTimeAsync(0);

      expect(useStore.getState().conversations.find((c) => c.id === 'a')?.title).toBe('Renamed on the phone');
    });

    it('pages on while the server has more changes', async () => {
      await startWithCursor([createConversation('a', 'A', 2)]);
      mockSyncChanges()
        .mockResolvedValueOnce(changes([], { cursor: 15, has_more: true }))
        .mockResolvedValueOnce(changes([], { cursor: 20, has_more: false }));

      await syncManager.incrementalSync();

      expect(mockSyncChanges().mock.calls.map(([c]) => c)).toEqual([10, 15]);
    });
  });

  describe('planner sync', () => {
    function plannerAt(count: number, lastReset: string | null): void {
      mockPlannerSync.mockResolvedValue({
        conversation: { id: 'planner-1', message_count: count, last_reset: lastReset },
        server_time: new Date().toISOString(),
      });
    }

    beforeEach(async () => {
      useStore.setState({ isPlannerView: true });
      callbacks.onPlannerDeleted = vi.fn();
      callbacks.onPlannerReset = vi.fn();
      callbacks.onPlannerExternalUpdate = vi.fn();
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();
    });

    afterEach(() => {
      useStore.setState({ isPlannerView: false });
    });

    it('reports new messages beyond the baseline while the planner is shown', async () => {
      syncManager.setPlannerBaseline(2);
      plannerAt(5, null);

      await syncManager.incrementalSync();

      expect(callbacks.onPlannerExternalUpdate).toHaveBeenCalledWith(5);
    });

    it('stays quiet about new messages when the planner view is closed', async () => {
      useStore.setState({ isPlannerView: false });
      syncManager.setPlannerBaseline(2);
      plannerAt(5, null);

      await syncManager.incrementalSync();

      expect(callbacks.onPlannerExternalUpdate).not.toHaveBeenCalled();
    });

    it('reports a reset made in another tab', async () => {
      plannerAt(2, 'reset-1');
      await syncManager.incrementalSync();
      plannerAt(2, 'reset-2');

      await syncManager.incrementalSync();

      expect(callbacks.onPlannerReset).toHaveBeenCalledTimes(1);
    });

    it('a re-baseline makes the next reset marker this device\'s own', async () => {
      plannerAt(2, 'reset-1');
      await syncManager.incrementalSync();
      syncManager.setPlannerBaseline(0);
      plannerAt(0, 'reset-2');

      await syncManager.incrementalSync();

      expect(callbacks.onPlannerReset).not.toHaveBeenCalled();
    });

    it('reports a planner deleted elsewhere once', async () => {
      plannerAt(2, null);
      await syncManager.incrementalSync();
      mockPlannerSync.mockResolvedValue({ conversation: null, server_time: new Date().toISOString() });

      await syncManager.incrementalSync();
      await syncManager.incrementalSync();

      expect(callbacks.onPlannerDeleted).toHaveBeenCalledTimes(1);
    });
  });

  describe('agent conversation sync', () => {
    const mockAgentSync = (): ReturnType<typeof vi.fn> =>
      agentsApi.syncConversation as unknown as ReturnType<typeof vi.fn>;

    function agentAt(count: number): void {
      mockAgentSync().mockResolvedValue({
        conversation: { id: 'agent-conv', message_count: count },
        server_time: new Date().toISOString(),
      });
    }

    beforeEach(async () => {
      callbacks.onAgentConversationExternalUpdate = vi.fn();
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();
    });

    it('does not poll without a viewed agent', async () => {
      await syncManager.incrementalSync();

      expect(mockAgentSync()).not.toHaveBeenCalled();
    });

    it('reports new messages beyond the baseline, then moves the baseline', async () => {
      syncManager.setViewedAgent('agent-1', 3);
      agentAt(5);

      await syncManager.incrementalSync();
      await syncManager.incrementalSync();

      expect(mockAgentSync()).toHaveBeenCalledWith('agent-1');
      expect(callbacks.onAgentConversationExternalUpdate).toHaveBeenCalledTimes(1);
      expect(callbacks.onAgentConversationExternalUpdate).toHaveBeenCalledWith(5);
    });

    it('takes the first poll as the baseline when none was given', async () => {
      syncManager.setViewedAgent('agent-1');
      agentAt(5);

      await syncManager.incrementalSync();

      expect(callbacks.onAgentConversationExternalUpdate).not.toHaveBeenCalled();
    });

    it('skips the poll while the open conversation streams', async () => {
      useStore.setState({ currentConversation: createConversation('agent-conv', 'Agent', 3) });
      syncManager.setViewedAgent('agent-1', 3);
      syncManager.setConversationStreaming('agent-conv', true);
      agentAt(5);

      await syncManager.incrementalSync();

      expect(mockAgentSync()).not.toHaveBeenCalled();
    });

    it("this device's own turn moves the agent baseline", async () => {
      useStore.setState({ currentConversation: createConversation('agent-conv', 'Agent', 3) });
      syncManager.setViewedAgent('agent-1', 3);
      syncManager.setLocalMessageCount('agent-conv', 5);
      agentAt(5);

      await syncManager.incrementalSync();

      expect(callbacks.onAgentConversationExternalUpdate).not.toHaveBeenCalled();
    });

    it('stops polling once the agent view is left', async () => {
      syncManager.setViewedAgent('agent-1', 3);
      syncManager.setViewedAgent(null);
      agentAt(5);

      await syncManager.incrementalSync();

      expect(mockAgentSync()).not.toHaveBeenCalled();
    });
  });

  describe('read reporting', () => {
    const mockMarkRead = (): ReturnType<typeof vi.fn> =>
      conversationsApi.markRead as unknown as ReturnType<typeof vi.fn>;

    beforeEach(async () => {
      useStore.getState().addConversation(createConversation('a', 'A', 2));
      mockSync.mockResolvedValue(createSyncResponse([createConversationSummary('a', 'A', 2)]));
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();
      mockMarkRead().mockClear();
    });

    it('reports each read count once', () => {
      syncManager.markConversationRead('a', 4);
      syncManager.markConversationRead('a', 4);

      expect(mockMarkRead().mock.calls).toEqual([['a', 4]]);
    });

    it('never reports a temp conversation', () => {
      syncManager.markConversationRead('temp-1', 2);

      expect(mockMarkRead()).not.toHaveBeenCalled();
    });

    it('retries a report that failed', async () => {
      mockMarkRead().mockRejectedValueOnce(new Error('offline'));
      syncManager.markConversationRead('a', 4);
      await vi.advanceTimersByTimeAsync(0);

      syncManager.markConversationRead('a', 4);

      expect(mockMarkRead()).toHaveBeenCalledTimes(2);
    });

    it('reports our own saved message as read', () => {
      syncManager.noteOwnMessageSaved('a');

      expect(mockMarkRead()).toHaveBeenCalledWith('a', 3);
    });

    it('our own turn in a chat we left leaves the reply unread', () => {
      syncManager.setLocalMessageCount('a', 4);

      expect(mockMarkRead()).toHaveBeenCalledWith('a', 3);
    });

    it('our own turn in the open chat is all read', () => {
      useStore.setState({ currentConversation: createConversation('a', 'A', 2) });

      syncManager.setLocalMessageCount('a', 4);

      expect(mockMarkRead()).toHaveBeenCalledWith('a', 4);
      expect(useStore.getState().conversations.find((c) => c.id === 'a')?.messageCount).toBe(4);
    });

    it('does not report a count the server already has', async () => {
      mockSync.mockResolvedValue({ ...createSyncResponse([{ ...createConversationSummary('a', 'A', 4), read_count: 4 }]), server_time: '2024-01-01T00:01:00Z' })
      await syncManager.fullSync();

      syncManager.markConversationRead('a', 4);

      expect(mockMarkRead()).not.toHaveBeenCalled();
    });
  });

  describe('local message count baselines', () => {
    it('a paginated conversation keeps a baseline it already has', async () => {
      useStore.getState().addConversation(createConversation('a', 'A', 2));
      mockSync.mockResolvedValue(createSyncResponse([createConversationSummary('a', 'A', 2)]));
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();

      syncManager.initializeLocalMessageCount('a', 9);
      syncManager.initializeLocalMessageCount('b', 9);
      const counts = (syncManager as unknown as { state: { localMessageCounts: Map<string, number> } }).state.localMessageCounts;

      expect(counts.get('a')).toBe(2);
      expect(counts.get('b')).toBe(9);
    });
  });

  describe('summary merge', () => {
    beforeEach(async () => {
      useStore.getState().addConversation(createConversation('a', 'Old title', 2));
      useStore.setState({ currentConversation: createConversation('a', 'Old title', 2) });
      callbacks.onCurrentConversationRenamed = vi.fn();
      mockSync.mockResolvedValue(createSyncResponse([createConversationSummary('a', 'Old title', 2)]));
      syncManager = new SyncManager(callbacks, RECOVERY, toast);
      await syncManager.start();
    });

    function nextSummary(extra: Partial<ConversationSummary>): void {
      mockSyncChanges.mockResolvedValue(changePage([{ ...createConversationSummary('a', 'Old title', 2), ...extra }], { server_time: '2024-01-01T00:01:00Z' }))
    }

    it('tells the open chat about a rename', async () => {
      nextSummary({ title: 'New title' });

      await syncManager.incrementalSync();

      expect(callbacks.onCurrentConversationRenamed).toHaveBeenCalledWith('New title');
      expect(useStore.getState().conversations.find((c) => c.id === 'a')?.title).toBe('New title');
    });

    it("adopts another device's anonymous mode and pin", async () => {
      nextSummary({ anonymous_mode: true, pinned: true });

      await syncManager.incrementalSync();

      expect(useStore.getState().anonymousModeByConversation.get('a')).toBe(true);
      expect(useStore.getState().conversations.find((c) => c.id === 'a')?.pinned).toBe(true);
    });
  });

  describe('command center sync', () => {
    it('stores the latest command center summary', async () => {
      const mockCommandCenter = agentsApi.getCommandCenter as unknown as ReturnType<typeof vi.fn>;
      mockCommandCenter.mockResolvedValueOnce({
        agents: [],
        pending_approvals: [],
        recent_executions: [],
        total_unread: 3,
        agents_waiting: 1,
        agents_with_errors: 0,
      });
      syncManager = new SyncManager(callbacks, RECOVERY, toast);

      await syncManager.start();

      expect(useStore.getState().commandCenterData?.total_unread).toBe(3);
    });
  });
});

describe('Agent State Management', () => {
  beforeEach(() => {
    resetStore();
    vi.clearAllMocks();
  });

  describe('clearAgentsState', () => {
    it('resets commandCenterData to null on logout', () => {
      // Set some command center data
      useStore.getState().setCommandCenterData({
        agents: [
          {
            id: 'agent-1',
            name: 'Test Agent',
            description: 'A test agent',
            schedule: '0 9 * * *',
            timezone: 'UTC',
            enabled: true,
            model: 'gemini-3-flash-preview',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            conversation_id: 'conv-1',
            unread_count: 5,
            has_pending_approval: false,
            has_error: false,
            fresh_context: false,
            daily_spending: 0,
            system_prompt: null,
            tool_permissions: null,
            last_run_at: null,
            next_run_at: null,
            budget_limit: null,
            system_type: null,
            effective_system_prompt: null,
            last_execution_status: null,
          },
        ],
        pending_approvals: [],
        recent_executions: [],
        total_unread: 5,
        agents_waiting: 0,
        agents_with_errors: 0,
        stats: EMPTY_AGENT_STATS,
      });

      // Verify data is set
      expect(useStore.getState().commandCenterData).not.toBeNull();
      expect(useStore.getState().commandCenterData?.total_unread).toBe(5);

      // Clear agents state (simulates logout)
      useStore.getState().clearAgentsState();

      // Verify commandCenterData is cleared
      expect(useStore.getState().commandCenterData).toBeNull();
    });

    it('clears commandCenterLastFetch timestamp on logout', () => {
      // Set command center data (also sets lastFetch)
      useStore.getState().setCommandCenterData({
        agents: [],
        pending_approvals: [],
        recent_executions: [],
        total_unread: 0,
        agents_waiting: 0,
        agents_with_errors: 0,
        stats: EMPTY_AGENT_STATS,
      });

      // Verify lastFetch is set
      expect(useStore.getState().commandCenterLastFetch).not.toBeNull();

      // Clear agents state
      useStore.getState().clearAgentsState();

      // Verify lastFetch is also cleared
      expect(useStore.getState().commandCenterLastFetch).toBeNull();
    });
  });

  describe('setCommandCenterData', () => {
    it('updates commandCenterData with new data', () => {
      const data = {
        agents: [
          {
            id: 'agent-1',
            name: 'My Agent',
            description: '',
            schedule: '0 8 * * *',
            timezone: 'America/New_York',
            enabled: true,
            model: 'gemini-3-flash-preview',
            created_at: '2024-01-01T00:00:00Z',
            updated_at: '2024-01-01T00:00:00Z',
            conversation_id: 'conv-1',
            unread_count: 3,
            has_pending_approval: true,
            has_error: false,
            fresh_context: false,
            daily_spending: 0,
            system_prompt: null,
            tool_permissions: null,
            last_run_at: null,
            next_run_at: null,
            budget_limit: null,
            system_type: null,
            effective_system_prompt: null,
            last_execution_status: null,
          },
        ],
        pending_approvals: [
          {
            id: 'approval-1',
            agent_id: 'agent-1',
            agent_name: 'My Agent',
            description: 'Send email?',
            tool_name: 'send_email',
            status: 'pending' as const,
            created_at: '2024-01-01T00:00:00Z',
            tool_args: null,
            resolved_at: null,
          },
        ],
        recent_executions: [],
        total_unread: 3,
        agents_waiting: 1,
        agents_with_errors: 0,
        stats: EMPTY_AGENT_STATS,
      };

      useStore.getState().setCommandCenterData(data);

      const state = useStore.getState();
      expect(state.commandCenterData).toEqual(data);
      expect(state.commandCenterData?.total_unread).toBe(3);
      expect(state.commandCenterData?.agents_waiting).toBe(1);
      expect(state.commandCenterData?.agents.length).toBe(1);
      expect(state.commandCenterData?.pending_approvals.length).toBe(1);
    });

    it('updates timestamp when data is set', () => {
      const before = Date.now();

      useStore.getState().setCommandCenterData({
        agents: [],
        pending_approvals: [],
        recent_executions: [],
        total_unread: 0,
        agents_waiting: 0,
        agents_with_errors: 0,
        stats: EMPTY_AGENT_STATS,
      });

      const after = Date.now();
      const lastFetch = useStore.getState().commandCenterLastFetch;

      expect(lastFetch).not.toBeNull();
      expect(lastFetch).toBeGreaterThanOrEqual(before);
      expect(lastFetch).toBeLessThanOrEqual(after);
    });

    it('sets timestamp to null when data is null', () => {
      // First set some data
      useStore.getState().setCommandCenterData({
        agents: [],
        pending_approvals: [],
        recent_executions: [],
        total_unread: 0,
        agents_waiting: 0,
        agents_with_errors: 0,
        stats: EMPTY_AGENT_STATS,
      });

      // Verify it's set
      expect(useStore.getState().commandCenterLastFetch).not.toBeNull();

      // Set to null
      useStore.getState().setCommandCenterData(null);

      // Both should be null
      expect(useStore.getState().commandCenterData).toBeNull();
      expect(useStore.getState().commandCenterLastFetch).toBeNull();
    });
  });

  describe('agent badge counts from commandCenterData', () => {
    it('provides unread count from total_unread', () => {
      useStore.getState().setCommandCenterData({
        agents: [],
        pending_approvals: [],
        recent_executions: [],
        total_unread: 10,
        agents_waiting: 0,
        agents_with_errors: 0,
        stats: EMPTY_AGENT_STATS,
      });

      expect(useStore.getState().commandCenterData?.total_unread).toBe(10);
    });

    it('provides waiting count from agents_waiting', () => {
      useStore.getState().setCommandCenterData({
        agents: [],
        pending_approvals: [],
        recent_executions: [],
        total_unread: 0,
        agents_waiting: 2,
        agents_with_errors: 0,
        stats: EMPTY_AGENT_STATS,
      });

      expect(useStore.getState().commandCenterData?.agents_waiting).toBe(2);
    });

    it('provides error count from agents_with_errors', () => {
      useStore.getState().setCommandCenterData({
        agents: [],
        pending_approvals: [],
        recent_executions: [],
        total_unread: 0,
        agents_waiting: 0,
        agents_with_errors: 1,
        stats: EMPTY_AGENT_STATS,
      });

      expect(useStore.getState().commandCenterData?.agents_with_errors).toBe(1);
    });
  });
});
