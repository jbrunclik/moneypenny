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

import { conversations as conversationsApi, planner as plannerApi, agents as agentsApi } from '../api/client';
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
  /** Called when the planner conversation was deleted in another tab */
  onPlannerDeleted?: () => void;
  /** Called when the planner conversation was reset in another tab */
  onPlannerReset?: () => void;
  /** Called when the planner has new messages from another tab/device */
  onPlannerExternalUpdate?: (messageCount: number) => void;
  /** Called when an agent conversation has new messages from another tab/device */
  onAgentConversationExternalUpdate?: (messageCount: number) => void;
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
   * Tracks when SyncManager first started (initial page load time).
   * Used to distinguish pagination-discovered conversations from actually new ones.
   */
  private initialLoadTime: string | null = null;

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

  /**
   * Tracks planner conversation message count for sync.
   */
  private plannerMessageCount: number | null = null;

  /**
   * Tracks planner last reset timestamp for reset detection.
   */
  private plannerLastReset: string | null = null;

  /**
   * Tracks the agent ID being viewed (for agent conversation sync).
   */
  private viewedAgentId: string | null = null;

  /**
   * Tracks agent conversation message count for sync.
   */
  private agentConversationMessageCount: number | null = null;

  constructor(callbacks: SyncManagerCallbacks) {
    this.callbacks = callbacks;
    this.handleVisibilityChange = this.handleVisibilityChange.bind(this);
  }

  /**
   * Start the sync manager - performs initial full sync and begins polling.
   *
   * Note: Full sync on startup is safe because applyFullSync() only updates
   * existing conversations and detects deletions - it does NOT add new conversations.
   * This preserves pagination while still allowing us to:
   * 1. Update message counts for conversations already loaded
   * 2. Detect deletions
   * 3. Establish initialLoadTime for pagination-discovered distinction
   */
  async start(): Promise<void> {
    log.info('Starting SyncManager');

    // Initialize local message counts from existing conversations (loaded via pagination)
    const store = useStore.getState();
    for (const conv of store.conversations) {
      if (conv.messageCount !== undefined) {
        this.localMessageCounts.set(conv.id, conv.messageCount);
      }
    }

    // Perform initial full sync
    // Note: applyFullSync() only updates existing conversations and detects deletions
    // It does NOT add new conversations, preserving pagination
    // Note: initialLoadTime is set during fullSync() before applying results
    await this.fullSync();

    // Start polling
    this.schedulePoll();

    // Listen for visibility changes
    document.addEventListener('visibilitychange', this.handleVisibilityChange);

    log.debug('SyncManager started', {
      lastSyncTime: this.lastSyncTime,
      initialLoadTime: this.initialLoadTime,
    });
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
    this.initialLoadTime = null;
    this.localMessageCounts.clear();
    this.streamingConversations.clear();
    this.isSyncing = false;
    this.plannerMessageCount = null;
    this.plannerLastReset = null;
    this.viewedAgentId = null;
    this.agentConversationMessageCount = null;
  }

  /**
   * Prune localMessageCounts to remove entries for conversations no longer in the store.
   * This prevents memory leaks when conversations are deleted locally.
   */
  private pruneLocalMessageCounts(): void {
    const store = useStore.getState();
    const existingIds = new Set(store.conversations.map((c) => c.id));
    let pruned = 0;

    for (const id of this.localMessageCounts.keys()) {
      if (!existingIds.has(id)) {
        this.localMessageCounts.delete(id);
        pruned++;
      }
    }

    if (pruned > 0) {
      log.debug('Pruned stale localMessageCounts entries', { pruned });
    }
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
      // Prune stale entries before syncing
      this.pruneLocalMessageCounts();

      const result = await conversationsApi.sync(null, true);
      this.lastSyncTime = result.server_time;

      // Set initialLoadTime on first full sync (before applying results)
      // This allows us to distinguish pagination-discovered vs actually new conversations
      if (!this.initialLoadTime) {
        this.initialLoadTime = result.server_time;
        log.debug('Initial load time established', { initialLoadTime: this.initialLoadTime });
      }

      this.applyFullSync(result.conversations);
      log.info('Full sync completed', {
        conversationCount: result.conversations.length,
        serverTime: result.server_time,
      });

      // Also sync command center to show badges immediately
      await this.syncCommandCenter();
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

      // Additionally sync planner if user has integrations
      await this.syncPlanner();

      // Sync agent conversation if viewing one
      await this.syncAgentConversation();

      // Sync command center to keep badges updated
      await this.syncCommandCenter();
    } catch (error) {
      log.warn('Incremental sync failed', { error });
      // Don't throw - syncing is best-effort
    } finally {
      this.isSyncing = false;
    }
  }

  /**
   * Apply full sync results - handles deletions and updates ONLY.
   *
   * IMPORTANT: Full sync does NOT add new conversations to the store.
   * It only:
   * 1. Updates existing conversations (message counts, titles, etc.)
   * 2. Detects deletions (conversations in store but not on server)
   *
   * This preserves pagination - conversations are only added via:
   * - Initial pagination load (loadInitialData)
   * - User scrolling to load more (pagination)
   * - Incremental sync adding genuinely new conversations (created on another device)
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

    // Apply updates to EXISTING conversations only (don't add new ones)
    // Filter to only conversations that are already in the store
    const existingServerConvs = serverConversations.filter((serverConv) =>
      store.conversations.some((localConv) => localConv.id === serverConv.id)
    );

    this.applyChanges(existingServerConvs, true);

    if (deletedIds.length > 0 || existingServerConvs.length > 0) {
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
        // New conversation discovered via sync
        // Only incremental sync should add new conversations (full sync doesn't add)
        if (isFullSync) {
          // Full sync should never add new conversations - they should come via pagination
          // This is a safety check in case applyFullSync() filtering fails
          log.warn('Full sync attempted to add new conversation (should not happen)', {
            conversationId: serverConv.id,
          });
          return;
        }

        // Incremental sync: Distinguish between:
        // 1. Pagination-discovered: Older conversations that weren't in initial page load
        // 2. Actually new: Created/updated after initial page load (e.g., on another device)
        const isPaginationDiscovered = this.isPaginationDiscovered(serverConv.updated_at);

        // For actually new conversations, show unread badge with message count
        // For pagination-discovered, no badge (user just hasn't scrolled to see it yet)
        const unreadCount = isPaginationDiscovered ? 0 : serverConv.message_count;

        if (isPaginationDiscovered) {
          log.info('Pagination-discovered conversation (not unread, skipping add)', {
            conversationId: serverConv.id,
            updated_at: serverConv.updated_at,
          });
          // Don't add pagination-discovered conversations - they'll come via pagination when user scrolls
          // Just track the message count for when they do get loaded
          this.localMessageCounts.set(serverConv.id, serverConv.message_count);
          continue; // Skip to next conversation in loop
        }

        // Actually new conversation - add it to the store
        log.info('Actually new conversation discovered via sync (showing unread badge)', {
          conversationId: serverConv.id,
          updated_at: serverConv.updated_at,
          messageCount: serverConv.message_count,
          unreadCount,
        });
        // For actually new conversations, initialize to 0 so unread count is correct
        // (unreadCount = serverCount - localCount = serverCount - 0 = serverCount)
        // Don't update this in the shouldUpdateLocalCount block below - we want to preserve
        // the 0 value until the user views the conversation
        this.localMessageCounts.set(serverConv.id, 0);

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
      // - On full sync: always update (establishing baseline), EXCEPT for actually new conversations
      //   that were just initialized to 0 (we want to preserve 0 until user views it)
      // - On incremental sync for current conv: don't update (user might have sent messages)
      // - On incremental sync for non-current conv with unread: don't update (preserve unread state)
      // - On incremental sync for non-current conv without unread: update (no state to preserve)
      const currentLocalCount = this.localMessageCounts.get(serverConv.id) ?? 0;
      const isActuallyNewConversation = !existing && currentLocalCount === 0 && serverConv.message_count > 0;
      const shouldUpdateLocalCount =
        (isFullSync && !isActuallyNewConversation) || (!isCurrentConv && unreadCount === 0);
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
   * Initialize local message count for a conversation discovered via pagination.
   * Only sets the count if we don't already have a baseline for this conversation.
   * Call this after loading more conversations via pagination.
   */
  initializeLocalMessageCount(convId: string, messageCount: number): void {
    if (!this.localMessageCounts.has(convId)) {
      this.localMessageCounts.set(convId, messageCount);
      log.debug('Initialized local message count for paginated conversation', {
        convId,
        messageCount,
      });
    }
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

  /**
   * Determine if a conversation was discovered via pagination (not actually new).
   *
   * Compares updated_at (server time) to initialLoadTime (server time from first sync).
   * If older than initialLoadTime minus a buffer, it's pagination discovery.
   *
   * Note: This is only called for incremental sync now, since full sync no longer adds
   * new conversations. Incremental syncs only return conversations updated since lastSyncTime,
   * so most will be actually new. But we still check the timestamp to handle edge cases
   * (invalid timestamps or conversations updated but still older than initialLoadTime).
   *
   * @param updatedAt ISO timestamp of when conversation was last updated (server time)
   * @returns true if conversation is pagination-discovered, false if actually new
   */
  private isPaginationDiscovered(updatedAt: string): boolean {
    // We need initialLoadTime (server time) to compare
    if (!this.initialLoadTime) {
      // If we don't have initialLoadTime yet (first sync), we can't distinguish.
      // Default to treating as pagination-discovered to be safe (no false unread badges).
      // This handles the case where conversations are discovered during the initial full sync
      // before we've established the baseline timestamp.
      return true;
    }

    // Compare server timestamps: if updated_at is older than initialLoadTime,
    // it's pagination discovery (existed before initial page load)
    // Both timestamps are server time, so no clock skew issues
    try {
      const updatedDate = new Date(updatedAt);
      const initialDate = new Date(this.initialLoadTime);

      // Check for invalid dates (new Date() doesn't throw, returns Invalid Date)
      if (isNaN(updatedDate.getTime()) || isNaN(initialDate.getTime())) {
        log.warn('Invalid timestamp for pagination detection', {
          updatedAt,
          initialLoadTime: this.initialLoadTime,
        });
        return true; // Default to pagination-discovered to be safe
      }

      // If updated_at is older than initial load time, it's pagination discovery
      // Add a small buffer (5 seconds) to account for timing differences between
      // when the conversation was last updated and when the initial page load happened
      // Both timestamps are server time, so minimal buffer needed
      const bufferMs = 5 * 1000; // 5 seconds
      return updatedDate.getTime() < (initialDate.getTime() - bufferMs);
    } catch (error) {
      // If timestamp parsing fails, default to pagination-discovered to be safe
      log.warn('Failed to parse timestamp for pagination detection', {
        updatedAt,
        initialLoadTime: this.initialLoadTime,
        error,
      });
      return true;
    }
  }

  /**
   * Sync planner conversation state to detect external updates, resets, or deletion.
   * This runs separately from normal conversation sync since planner is excluded
   * from regular sync (has is_planning=1 flag).
   */
  private async syncPlanner(): Promise<void> {
    try {
      const response = await plannerApi.sync();

      if (!response.conversation) {
        // Planner doesn't exist yet or was deleted
        if (this.plannerMessageCount !== null) {
          // Was deleted - planner existed before but doesn't now
          const store = useStore.getState();
          if (store.isPlannerView) {
            log.info('Planner conversation was deleted externally');
            this.callbacks.onPlannerDeleted?.();
          }
          this.plannerMessageCount = null;
          this.plannerLastReset = null;
        }
        return;
      }

      const { message_count, last_reset } = response.conversation;

      // Check for reset (last_reset timestamp changed)
      if (this.plannerLastReset && last_reset !== this.plannerLastReset) {
        // Planner was reset in another tab
        const store = useStore.getState();
        if (store.isPlannerView) {
          log.info('Planner conversation was reset externally');
          this.callbacks.onPlannerReset?.();
        }
      }

      // Check for new messages (message count increased)
      if (this.plannerMessageCount !== null && message_count > this.plannerMessageCount) {
        // New messages added in another tab/device
        const store = useStore.getState();
        if (store.isPlannerView) {
          log.info('Planner conversation has new messages', {
            previousCount: this.plannerMessageCount,
            newCount: message_count,
          });
          this.callbacks.onPlannerExternalUpdate?.(message_count);
        }
      }

      // Update tracking state
      this.plannerMessageCount = message_count;
      this.plannerLastReset = last_reset;
    } catch (error) {
      log.warn('Planner sync failed', { error });
      // Don't throw - syncing is best-effort
    }
  }

  /**
   * Sync agent conversation state to detect external updates.
   * This runs separately from normal conversation sync since agent conversations
   * are excluded from regular sync (have is_agent=1 flag).
   */
  private async syncAgentConversation(): Promise<void> {
    // Skip if not viewing an agent conversation
    if (!this.viewedAgentId) {
      return;
    }

    // Skip if the agent conversation is currently streaming
    const store = useStore.getState();
    const currentConv = store.currentConversation;
    if (currentConv && this.streamingConversations.has(currentConv.id)) {
      log.debug('Skipping agent sync - conversation is streaming');
      return;
    }

    try {
      const response = await agentsApi.syncConversation(this.viewedAgentId);

      if (!response.conversation) {
        // Agent conversation doesn't exist
        log.debug('Agent conversation not found', { agentId: this.viewedAgentId });
        return;
      }

      const { message_count } = response.conversation;

      // Check for new messages (message count increased)
      if (this.agentConversationMessageCount !== null && message_count > this.agentConversationMessageCount) {
        // New messages added in another tab/device
        log.info('Agent conversation has new messages', {
          agentId: this.viewedAgentId,
          previousCount: this.agentConversationMessageCount,
          newCount: message_count,
        });
        this.callbacks.onAgentConversationExternalUpdate?.(message_count);
      }

      // Update tracking state
      this.agentConversationMessageCount = message_count;
    } catch (error) {
      log.warn('Agent conversation sync failed', { error, agentId: this.viewedAgentId });
      // Don't throw - syncing is best-effort
    }
  }

  /**
   * Set the agent being viewed for sync tracking.
   * Call this when entering/leaving an agent conversation.
   *
   * @param agentId The agent ID being viewed, or null when leaving
   * @param messageCount The current message count (to establish baseline)
   */
  setViewedAgent(agentId: string | null, messageCount?: number): void {
    if (agentId) {
      this.viewedAgentId = agentId;
      this.agentConversationMessageCount = messageCount ?? null;
      log.debug('Set viewed agent', { agentId, messageCount });
    } else {
      this.viewedAgentId = null;
      this.agentConversationMessageCount = null;
      log.debug('Cleared viewed agent');
    }
  }

  /**
   * Sync command center data to keep sidebar badges updated.
   * This fetches the latest command center summary and updates the store.
   */
  private async syncCommandCenter(): Promise<void> {
    try {
      const data = await agentsApi.getCommandCenter();
      const store = useStore.getState();

      // Only update if values changed (to avoid unnecessary re-renders)
      const currentData = store.commandCenterData;
      if (!currentData ||
          currentData.total_unread !== data.total_unread ||
          currentData.agents_waiting !== data.agents_waiting ||
          currentData.agents_with_errors !== data.agents_with_errors) {
        store.setCommandCenterData(data);
        log.debug('Command center sync updated', {
          totalUnread: data.total_unread,
          agentsWaiting: data.agents_waiting,
          agentsWithErrors: data.agents_with_errors,
        });
      }
    } catch (error) {
      log.warn('Command center sync failed', { error });
      // Don't throw - syncing is best-effort
    }
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
