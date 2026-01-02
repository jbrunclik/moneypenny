/**
 * SyncManager handles real-time synchronization of conversation state
 * across multiple devices/tabs using timestamp-based polling.
 *
 * Key features:
 * - Incremental sync using server-provided timestamps
 * - Full sync on initial load and after long tab inactivity
 * - Delete detection via ID comparison during full sync
 * - Unread message count tracking per conversation
 * - Visibility-aware polling (pauses when tab hidden)
 */

import { conversations as conversationsApi } from '../api/client';
import { useStore } from '../state/store';
import { toast } from '../components/Toast';
import { createLogger } from '../utils/logger';
import {
  SYNC_POLL_INTERVAL_MS,
  SYNC_FULL_SYNC_THRESHOLD_MS,
} from '../config';
import type { ConversationSummary } from '../types/api';

const log = createLogger('sync');

/** Callbacks for SyncManager events */
export interface SyncManagerCallbacks {
  /** Called when conversations list should be re-rendered */
  onConversationsUpdated: () => void;
  /** Called when a conversation was deleted while user was viewing it */
  onCurrentConversationDeleted: () => void;
  /** Called when the current conversation has new messages from another device */
  onCurrentConversationExternalUpdate: (messageCount: number) => void;
}

/**
 * SyncManager class manages conversation synchronization with the server.
 * Should be initialized after authentication and stopped on logout.
 */
export class SyncManager {
  private lastSyncTime: string | null = null;
  private lastHiddenTime: number | null = null;
  private pollTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private isVisible: boolean = true;
  private callbacks: SyncManagerCallbacks;

  /**
   * Tracks the message count we last knew about for each conversation.
   * Used to calculate unread counts.
   */
  private localMessageCounts: Map<string, number> = new Map();

  /**
   * Lock to prevent concurrent sync operations.
   * Avoids race conditions when visibility change triggers sync while poll is running.
   */
  private isSyncing: boolean = false;

  /**
   * Set of conversation IDs that are currently streaming.
   * Sync updates for these conversations are deferred to avoid false unread counts.
   */
  private streamingConversations: Set<string> = new Set();

  constructor(callbacks: SyncManagerCallbacks) {
    this.callbacks = callbacks;
    this.handleVisibilityChange = this.handleVisibilityChange.bind(this);
  }

  /**
   * Start the sync manager - performs initial full sync and begins polling.
   */
  async start(): Promise<void> {
    log.info('Starting SyncManager');

    // Initialize local message counts from existing conversations
    const store = useStore.getState();
    for (const conv of store.conversations) {
      // For existing conversations, we don't know the exact message count yet
      // We'll get it from the first sync
      if (conv.messageCount !== undefined) {
        this.localMessageCounts.set(conv.id, conv.messageCount);
      }
    }

    // Perform initial full sync
    await this.fullSync();

    // Start polling
    this.schedulePoll();

    // Listen for visibility changes
    document.addEventListener('visibilitychange', this.handleVisibilityChange);

    log.debug('SyncManager started', { lastSyncTime: this.lastSyncTime });
  }

  /**
   * Stop the sync manager - clears timers and removes listeners.
   */
  stop(): void {
    log.info('Stopping SyncManager');

    if (this.pollTimeoutId) {
      clearTimeout(this.pollTimeoutId);
      this.pollTimeoutId = null;
    }

    document.removeEventListener('visibilitychange', this.handleVisibilityChange);

    this.lastSyncTime = null;
    this.lastHiddenTime = null;
    this.localMessageCounts.clear();
    this.streamingConversations.clear();
    this.isSyncing = false;
  }

  /**
   * Perform a full sync - fetches all conversations for delete detection.
   */
  async fullSync(): Promise<void> {
    // Prevent concurrent syncs
    if (this.isSyncing) {
      log.debug('Full sync skipped - another sync in progress');
      return;
    }

    this.isSyncing = true;
    log.debug('Performing full sync');

    try {
      const result = await conversationsApi.sync(null, true);
      this.lastSyncTime = result.server_time;
      this.applyFullSync(result.conversations);
      log.info('Full sync completed', {
        conversationCount: result.conversations.length,
        serverTime: result.server_time,
      });
    } catch (error) {
      log.warn('Full sync failed', { error });
      // Don't throw - syncing is best-effort
    } finally {
      this.isSyncing = false;
    }
  }

  /**
   * Perform an incremental sync - only fetches changed conversations.
   */
  async incrementalSync(): Promise<void> {
    // Prevent concurrent syncs
    if (this.isSyncing) {
      log.debug('Incremental sync skipped - another sync in progress');
      return;
    }

    if (!this.lastSyncTime) {
      // No previous sync time, do a full sync instead
      await this.fullSync();
      return;
    }

    this.isSyncing = true;
    log.debug('Performing incremental sync', { since: this.lastSyncTime });

    try {
      const result = await conversationsApi.sync(this.lastSyncTime, false);
      this.lastSyncTime = result.server_time;

      if (result.conversations.length > 0) {
        this.applyIncrementalSync(result.conversations);
        log.info('Incremental sync completed', {
          updatedCount: result.conversations.length,
          serverTime: result.server_time,
        });
      } else {
        log.debug('Incremental sync: no changes');
      }
    } catch (error) {
      log.warn('Incremental sync failed', { error });
      // Don't throw - syncing is best-effort
    } finally {
      this.isSyncing = false;
    }
  }

  /**
   * Apply full sync results - handles deletions and updates.
   */
  private applyFullSync(serverConversations: ConversationSummary[]): void {
    const store = useStore.getState();
    const serverIds = new Set(serverConversations.map((c) => c.id));

    // Detect deleted conversations (in local but not in server)
    // Skip temp conversations (not yet persisted)
    const deletedIds = store.conversations
      .filter((c) => !c.id.startsWith('temp-') && !serverIds.has(c.id))
      .map((c) => c.id);

    // Handle deletions
    for (const id of deletedIds) {
      log.info('Conversation deleted externally', { conversationId: id });

      if (store.currentConversation?.id === id) {
        toast.warning('This conversation was deleted.');
        this.callbacks.onCurrentConversationDeleted();
      }

      store.removeConversation(id);
      this.localMessageCounts.delete(id);
    }

    // Apply updates
    this.applyChanges(serverConversations, true);

    if (deletedIds.length > 0 || serverConversations.length > 0) {
      this.callbacks.onConversationsUpdated();
    }
  }

  /**
   * Apply incremental sync results - only updates changed conversations.
   */
  private applyIncrementalSync(serverConversations: ConversationSummary[]): void {
    this.applyChanges(serverConversations, false);

    if (serverConversations.length > 0) {
      this.callbacks.onConversationsUpdated();
    }
  }

  /**
   * Apply conversation changes from server.
   */
  private applyChanges(
    serverConversations: ConversationSummary[],
    isFullSync: boolean
  ): void {
    const store = useStore.getState();

    for (const serverConv of serverConversations) {
      // Skip conversations that are currently streaming to avoid false unread counts
      // The local message count will be updated when streaming completes
      if (this.streamingConversations.has(serverConv.id)) {
        log.debug('Skipping sync for streaming conversation', { conversationId: serverConv.id });
        continue;
      }

      const existing = store.conversations.find((c) => c.id === serverConv.id);
      const localCount = this.localMessageCounts.get(serverConv.id) || 0;
      const isCurrentConv = store.currentConversation?.id === serverConv.id;

      // Calculate unread count (only for conversations not currently viewed)
      let unreadCount = 0;
      let hasExternalUpdate = false;

      if (serverConv.message_count > localCount) {
        if (isCurrentConv) {
          // User is viewing this conversation - mark as external update
          hasExternalUpdate = true;
          log.info('External update detected for current conversation', {
            conversationId: serverConv.id,
            serverMessageCount: serverConv.message_count,
            localMessageCount: localCount,
            isStreaming: this.streamingConversations.has(serverConv.id),
          });
          this.callbacks.onCurrentConversationExternalUpdate(serverConv.message_count);
        } else {
          // User is not viewing - count as unread
          unreadCount = serverConv.message_count - localCount;
        }
      }

      if (existing) {
        // Update existing conversation
        store.updateConversation(serverConv.id, {
          title: serverConv.title,
          updated_at: serverConv.updated_at,
          messageCount: serverConv.message_count,
          unreadCount,
          hasExternalUpdate,
        });
      } else {
        // New conversation from another device
        log.info('New conversation from another device', {
          conversationId: serverConv.id,
        });
        store.addConversation({
          id: serverConv.id,
          title: serverConv.title,
          model: serverConv.model,
          created_at: serverConv.updated_at, // We don't have created_at in sync response
          updated_at: serverConv.updated_at,
          messageCount: serverConv.message_count,
          unreadCount,
          hasExternalUpdate: false,
        });
      }

      // Update local message count tracking
      // - On full sync: always update (establishing baseline)
      // - On incremental sync for current conv: don't update (user might have sent messages)
      // - On incremental sync for non-current conv with unread: don't update (preserve unread state)
      // - On incremental sync for non-current conv without unread: update (no state to preserve)
      const shouldUpdateLocalCount =
        isFullSync || (!isCurrentConv && unreadCount === 0);
      if (shouldUpdateLocalCount) {
        this.localMessageCounts.set(serverConv.id, serverConv.message_count);
      }
    }
  }

  /**
   * Mark a conversation as read - clears unread count and updates local tracking.
   * Call this when user views a conversation.
   */
  markConversationRead(convId: string, messageCount: number): void {
    log.debug('Marking conversation as read', { convId, messageCount });

    this.localMessageCounts.set(convId, messageCount);
    useStore.getState().updateConversation(convId, {
      unreadCount: 0,
      hasExternalUpdate: false,
      messageCount,
    });
  }

  /**
   * Update local message count after sending a message.
   * Call this after successfully sending a message.
   */
  incrementLocalMessageCount(convId: string, increment: number = 1): void {
    const currentCount = this.localMessageCounts.get(convId) || 0;
    const newCount = currentCount + increment;
    this.localMessageCounts.set(convId, newCount);

    // Also update the store
    useStore.getState().updateConversation(convId, {
      messageCount: newCount,
    });
  }

  /**
   * Mark a conversation as currently streaming.
   * Sync updates for this conversation will be deferred until streaming completes.
   * This prevents false unread counts during active message generation.
   */
  setConversationStreaming(convId: string, isStreaming: boolean): void {
    if (isStreaming) {
      this.streamingConversations.add(convId);
      log.debug('Conversation marked as streaming', {
        conversationId: convId,
        allStreaming: Array.from(this.streamingConversations),
      });
    } else {
      this.streamingConversations.delete(convId);
      log.debug('Conversation streaming completed', {
        conversationId: convId,
        allStreaming: Array.from(this.streamingConversations),
      });
    }
  }

  /**
   * Handle tab visibility changes.
   */
  private handleVisibilityChange(): void {
    const wasHidden = !this.isVisible;
    this.isVisible = document.visibilityState === 'visible';

    if (!this.isVisible) {
      // Tab became hidden - record the time
      this.lastHiddenTime = Date.now();
      log.debug('Tab hidden');
    } else if (wasHidden) {
      // Coming back from hidden
      const hiddenDuration = this.lastHiddenTime
        ? Date.now() - this.lastHiddenTime
        : 0;

      log.debug('Tab visible', { hiddenDurationMs: hiddenDuration });

      // Full sync if hidden for >5 minutes (for delete detection)
      if (hiddenDuration > SYNC_FULL_SYNC_THRESHOLD_MS) {
        log.info('Long tab inactivity, performing full sync');
        this.fullSync();
      } else {
        // Quick incremental sync on tab refocus
        this.incrementalSync();
      }
    }
  }

  /**
   * Schedule the next poll.
   */
  private schedulePoll(): void {
    this.pollTimeoutId = setTimeout(() => {
      if (this.isVisible) {
        this.incrementalSync();
      }
      this.schedulePoll();
    }, SYNC_POLL_INTERVAL_MS);
  }
}

// Singleton instance
let syncManagerInstance: SyncManager | null = null;

/**
 * Initialize the global SyncManager instance.
 */
export function initSyncManager(callbacks: SyncManagerCallbacks): SyncManager {
  if (syncManagerInstance) {
    syncManagerInstance.stop();
  }
  syncManagerInstance = new SyncManager(callbacks);
  return syncManagerInstance;
}

/**
 * Get the current SyncManager instance.
 */
export function getSyncManager(): SyncManager | null {
  return syncManagerInstance;
}

/**
 * Stop and clear the global SyncManager instance.
 */
export function stopSyncManager(): void {
  if (syncManagerInstance) {
    syncManagerInstance.stop();
    syncManagerInstance = null;
  }
}
