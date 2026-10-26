/**
 * SyncManager handles real-time synchronization of conversation state
 * across multiple devices/tabs by polling.
 *
 * It owns when to sync: the initial full sync, the poll loop (paused while
 * the tab is hidden), the sync lock and queue, foregrounding (visibility,
 * bfcache, back online) and this device's own message counts. What a sync
 * response changes lives in the modules beside it:
 * - change-log-merge / full-sync-merge / summary-merge - applying responses
 * - planner-sync, agent-conversation-sync, command-center-sync - side views
 * - sync-state - the shared per-conversation state; read-reporting
 */

import { conversations as conversationsApi } from '../api/conversations';
import { useStore } from '../state/store';
import { toast } from '../components/Toast';
import { createLogger } from '../utils/logger';
import {
  SYNC_POLL_INTERVAL_MS,
  SYNC_FULL_SYNC_THRESHOLD_MS,
  SYNC_MAX_CHANGE_PAGES,
} from '../config';
import type { ConversationSummary } from '../types/api';
import { type StreamRecoveryHooks, SyncState, type SyncManagerCallbacks } from './sync-state';
import { PlannerSync } from './planner-sync';
import { AgentConversationSync } from './agent-conversation-sync';
import { syncCommandCenter } from './command-center-sync';
import { applyChanges, applyDeferredState } from './summary-merge';
import { applyFullSync } from './full-sync-merge';
import { applyChangeLog } from './change-log-merge';
import { reportRead } from './read-reporting';

const log = createLogger('sync');

/**
 * SyncManager class manages conversation synchronization with the server.
 * Should be initialized after authentication and stopped on logout.
 */
export class SyncManager {
  private lastSyncTime: string | null = null;

  /**
   * Change-log cursor (server seq) - incremental syncs ask for everything
   * changed after it, archive/trash/pin/delete included. Null until a full
   * sync returns one (a server without the change log keeps the legacy
   * timestamp sync).
   */
  private changeCursor: number | null = null;
  private lastHiddenTime: number | null = null;
  private pollTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private isVisible: boolean = true;
  private callbacks: SyncManagerCallbacks;
  private readonly recovery: StreamRecoveryHooks;
  private readonly state: SyncState;
  private readonly planner: PlannerSync;
  private readonly agentConversation: AgentConversationSync;

  /**
   * Lock to prevent concurrent sync operations.
   * Avoids race conditions when visibility change triggers sync while poll is running.
   */
  private isSyncing: boolean = false;

  /** A full sync was requested while another sync held the lock. */
  private fullSyncQueued = false;

  /** An incremental sync was requested while another sync held the lock. */
  private incrementalSyncQueued = false;

  /** Stopped (logout) - a start still awaiting its first sync must not go on. */
  private stopped = false;

  constructor(callbacks: SyncManagerCallbacks, recovery: StreamRecoveryHooks) {
    this.callbacks = callbacks;
    this.recovery = recovery;
    this.state = new SyncState(callbacks, toast, recovery.cancel);
    this.planner = new PlannerSync(callbacks);
    this.agentConversation = new AgentConversationSync(this.state);
    this.handleVisibilityChange = this.handleVisibilityChange.bind(this);
    this.handlePageShow = this.handlePageShow.bind(this);
    this.handleOnline = this.handleOnline.bind(this);
  }

  /**
   * Start the sync manager - performs initial full sync and begins polling.
   *
   * Full sync on startup:
   * 1. Updates message counts for conversations already loaded
   * 2. Detects deletions (conversations removed on other devices)
   * 3. Establishes initialLoadTime for pagination vs genuinely-new distinction
   * 4. Adds genuinely new conversations (created after initialLoadTime on other devices)
   *
   * Pagination-discovered conversations (older than initialLoadTime) are NOT added,
   * preserving the pagination behavior.
   */
  async start(): Promise<void> {
    log.info('Starting SyncManager');

    // The initial sync is best-effort: a failure here must NOT prevent the
    // polling below from starting (it would silently disable sync for the
    // whole session) - the poll loop self-heals once connectivity returns
    try {
      // Initialize local message counts from existing conversations (loaded via pagination)
      const store = useStore.getState();
      for (const conv of store.conversations) {
        if (conv.messageCount !== undefined) {
          this.state.localMessageCounts.set(conv.id, conv.messageCount);
        }
      }

      // Perform initial full sync
      // Note: initialLoadTime is set during fullSync() before applying results
      // applyFullSync() updates existing conversations, detects deletions, and adds
      // genuinely new conversations (created after initialLoadTime on other devices)
      await this.fullSync();
    } catch (error) {
      log.warn('SyncManager initial sync failed - continuing with polling', { error });
    }
    // stop() (logout) during the initial sync: no zombie poller / listeners
    if (this.stopped) return;

    // Start polling
    this.schedulePoll();

    // Listen for visibility changes
    document.addEventListener('visibilitychange', this.handleVisibilityChange);
    // iOS bfcache restores can skip visibilitychange entirely (R14)
    window.addEventListener('pageshow', this.handlePageShow);
    // Back online after an outage: polls failed meanwhile (and deletions only
    // show up in a full sync)
    window.addEventListener('online', this.handleOnline);

    log.debug('SyncManager started', {
      lastSyncTime: this.lastSyncTime,
      initialLoadTime: this.state.initialLoadTime,
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
    window.removeEventListener('pageshow', this.handlePageShow);
    window.removeEventListener('online', this.handleOnline);

    this.lastSyncTime = null;
    this.changeCursor = null;
    this.lastHiddenTime = null;
    this.state.clear();
    this.fullSyncQueued = false;
    this.incrementalSyncQueued = false;
    this.stopped = true;
    this.isSyncing = false;
    this.planner.clear();
    this.agentConversation.clear();
  }

  /**
   * Prune localMessageCounts to remove entries for conversations no longer in the store.
   * This prevents memory leaks when conversations are deleted locally.
   */
  private pruneLocalMessageCounts(): void {
    const store = useStore.getState();
    const existingIds = new Set(store.conversations.map((c) => c.id));
    let pruned = 0;

    for (const id of this.state.localMessageCounts.keys()) {
      if (!existingIds.has(id)) {
        this.state.localMessageCounts.delete(id);
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
      // Don't drop it: a full sync is how deletions are noticed (a frozen
      // iOS poll timer firing on resume used to swallow the resume's one)
      log.debug('Full sync queued - another sync in progress');
      this.fullSyncQueued = true;
      return;
    }

    this.isSyncing = true;
    log.debug('Performing full sync');

    try {
      await this.fetchFullSync();
      // Also sync command center to show badges immediately
      await syncCommandCenter();
    } catch (error) {
      log.warn('Full sync failed', { error });
      // Don't throw - syncing is best-effort
    } finally {
      this.isSyncing = false;
      this.runQueuedFullSync();
    }
  }

  /** Fetch every conversation and apply the answer (deletions, updates, additions). */
  private async fetchFullSync(): Promise<void> {
    // Prune stale entries before syncing
    this.pruneLocalMessageCounts();

    // Only conversations known BEFORE the request can be "missing" from
    // its answer: one created, restored or unarchived here while it was
    // in flight is absent from the server's older snapshot - it was
    // removed (open: "This conversation was deleted.") until the change
    // log re-added it a minute later
    const knownBefore = new Set(useStore.getState().conversations.map((c) => c.id));
    this.state.markSyncRequest();
    const result = await conversationsApi.sync(null, true);
    this.lastSyncTime = result.server_time;
    // Taken before the server's query: changes during it re-arrive next time
    if (typeof result.cursor === 'number') this.changeCursor = result.cursor;

    // Set initialLoadTime on first full sync (before applying results)
    // This allows us to distinguish pagination-discovered vs actually new conversations
    if (!this.state.initialLoadTime) {
      this.state.initialLoadTime = result.server_time;
      log.debug('Initial load time established', { initialLoadTime: this.state.initialLoadTime });
    }

    applyFullSync(this.state, result.conversations, knownBefore);
    log.info('Full sync completed', {
      conversationCount: result.conversations.length,
      serverTime: result.server_time,
    });
  }

  private runQueuedFullSync(): void {
    if (this.fullSyncQueued) {
      this.fullSyncQueued = false;
      this.incrementalSyncQueued = false; // the full sync covers it
      void this.fullSync();
    } else if (this.incrementalSyncQueued) {
      this.incrementalSyncQueued = false;
      void this.incrementalSync();
    }
  }

  /** A local change to a conversation (see SyncState.noteLocalChange). */
  noteLocalChange(convId: string): void {
    this.state.noteLocalChange(convId);
  }

  /**
   * Perform an incremental sync - only fetches changed conversations.
   */
  async incrementalSync(): Promise<void> {
    // Prevent concurrent syncs
    if (this.isSyncing) {
      // Queued, not dropped: the "a turn just ended, fetch its state" sync
      // was lost whenever it collided with a poll
      log.debug('Incremental sync queued - another sync in progress');
      this.incrementalSyncQueued = true;
      return;
    }

    const since = this.lastSyncTime;
    if (!since) {
      // No previous sync time, do a full sync instead
      await this.fullSync();
      return;
    }

    this.isSyncing = true;
    log.debug('Performing incremental sync', { since, cursor: this.changeCursor });

    try {
      if (this.changeCursor !== null) {
        await this.syncChangeLog();
      } else {
        await this.syncSince(since);
      }

      // Additionally sync planner if user has integrations
      await this.planner.sync();

      // Sync agent conversation if viewing one
      await this.agentConversation.sync();

      // Sync command center to keep badges updated
      await syncCommandCenter();
    } catch (error) {
      log.warn('Incremental sync failed', { error });
      // Don't throw - syncing is best-effort
    } finally {
      this.isSyncing = false;
      this.runQueuedFullSync();
    }
  }

  /** Legacy timestamp sync (a server without the change log): what changed since `since`. */
  private async syncSince(since: string): Promise<void> {
    const result = await conversationsApi.sync(since, false);
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
  }

  /** Fetch and apply every change after the cursor (paging while has_more). */
  private async syncChangeLog(): Promise<void> {
    for (let page = 0; page < SYNC_MAX_CHANGE_PAGES && this.changeCursor !== null; page++) {
      this.state.markSyncRequest();
      const result = await conversationsApi.syncChanges(this.changeCursor);
      this.lastSyncTime = result.server_time;
      applyChangeLog(this.state, result);
      if (typeof result.cursor === 'number') this.changeCursor = result.cursor;
      if (!result.has_more) return;
    }
  }

  /**
   * Apply incremental sync results - only updates changed conversations.
   */
  private applyIncrementalSync(serverConversations: ConversationSummary[]): void {
    applyChanges(this.state, serverConversations, false);

    if (serverConversations.length > 0) {
      this.callbacks.onConversationsUpdated();
    }
  }

  /**
   * Mark a conversation as read - clears unread count and updates local tracking.
   * Call this when user views a conversation.
   */
  markConversationRead(convId: string, messageCount: number): void {
    log.debug('Marking conversation as read', { convId, messageCount });

    // Also moves the planner/agent view baselines when that view is open
    this.applyLocalCount(convId, messageCount);
    reportRead(this.state, convId, messageCount);
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
    if (!this.state.localMessageCounts.has(convId)) {
      this.state.localMessageCounts.set(convId, messageCount);
      log.debug('Initialized local message count for paginated conversation', {
        convId,
        messageCount,
      });
    }
  }

  /**
   * Our own message was saved: it is read (we wrote it) - reported right
   * away, or other devices badged our in-progress turn until it ended.
   * The reply placeholder still counts as one unread there: a reply coming.
   */
  noteOwnMessageSaved(convId: string): void {
    const known = this.state.localMessageCounts.get(convId);
    if (known !== undefined) reportRead(this.state, convId, known + 1);
  }

  /**
   * Update local message count after sending a message.
   * Prefer setLocalMessageCount with the server's count when a turn reports it.
   */
  incrementLocalMessageCount(convId: string, increment: number = 1): void {
    const currentCount = this.state.localMessageCounts.get(convId) || 0;
    this.setLocalMessageCount(convId, currentCount + increment);
  }

  /**
   * Take the server's exact message count after this device's own turn as
   * the baseline. Guessing +2 drifted (regenerate/continue change the count
   * by 0/+1), and the inflated baseline hid the other device's next messages.
   * The planner and agent views track their own baselines - bump those too,
   * or this device's own messages there read as "new from another device".
   */
  setLocalMessageCount(convId: string, count: number): void {
    this.applyLocalCount(convId, count);
    // Our own turn: shown if the chat is open; switched away, only our own
    // message counts as read - the reply stays unread on every device
    const isCurrent = useStore.getState().currentConversation?.id === convId;
    reportRead(this.state, convId, isCurrent ? count : count - 1);
  }

  /** The local baseline (+ planner/agent view baselines), no read report. */
  private applyLocalCount(convId: string, count: number): void {
    this.state.localMessageCounts.set(convId, count);
    const store = useStore.getState();
    store.updateConversation(convId, { messageCount: count });

    if (store.currentConversation?.id !== convId) return;
    if (store.isPlannerView) this.planner.noteOwnCount(count);
    this.agentConversation.noteOwnCount(count);
  }

  /**
   * Mark a conversation as currently streaming.
   * Sync updates for this conversation will be deferred until streaming completes.
   * This prevents false unread counts during active message generation.
   */
  setConversationStreaming(convId: string, isStreaming: boolean): void {
    if (isStreaming) {
      this.state.streamingConversations.add(convId);
      log.debug('Conversation marked as streaming', {
        conversationId: convId,
        allStreaming: Array.from(this.state.streamingConversations),
      });
    } else {
      this.state.streamingConversations.delete(convId);
      log.debug('Conversation streaming completed', {
        conversationId: convId,
        allStreaming: Array.from(this.state.streamingConversations),
      });
      const deferred = this.state.deferredUpdates.get(convId);
      if (deferred) {
        this.state.deferredUpdates.delete(convId);
        if (this.changeCursor !== null) {
          // The summary is a snapshot from DURING our turn. Its counts are
          // moot (the turn set the exact one), and its untitled "New
          // Conversation" must not revert the title the turn just set - but
          // the other device's changes in it (a rename, a pin) must not be
          // lost either: a poll that landed after our final save already
          // moved the cursor past it, so nothing re-sends them.
          applyDeferredState(this.state, deferred);
          void this.incrementalSync();
        } else {
          // Legacy timestamp sync never re-sends it. Callers set the turn's
          // count first, so only the other device's changes remain.
          applyChanges(this.state, [deferred], false);
          this.callbacks.onConversationsUpdated();
        }
      }
    }
  }

  /** Back online: catch up with a full sync (deletions only show up there). */
  private handleOnline(): void {
    log.info('Back online, performing full sync');
    void this.fullSync();
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

      // Pending stream recovery starts first so the recovered message shows
      // up promptly - but NOT awaited: it retries a missing message for
      // seconds, and a sync waiting behind it noticed a conversation deleted
      // on another device only after "Response may be incomplete" (two
      // contradictory toasts). The sync cancels the recovery of a removed one.
      void this.attemptPendingStreamRecovery(hiddenDuration);

      // Full sync if hidden for >5 minutes (for delete detection)
      if (hiddenDuration > SYNC_FULL_SYNC_THRESHOLD_MS) {
        log.info('Long tab inactivity, performing full sync');
        void this.fullSync();
      } else {
        // Quick incremental sync on tab refocus
        void this.incrementalSync();
      }
    }
  }

  /**
   * Handle bfcache restores - iOS can restore a page from the back/forward
   * cache without firing visibilitychange (R14), leaving a pending stream
   * recovery unattempted until the next poll.
   */
  private handlePageShow(event: PageTransitionEvent): void {
    if (!event.persisted) return;
    log.info('Page restored from bfcache');
    // iOS can restore without a visibilitychange to "visible" after the
    // "hidden" one - polling stayed paused until the next visibility event
    this.isVisible = document.visibilityState === 'visible';
    void this.attemptPendingStreamRecovery(0);
    void this.incrementalSync();
  }

  /**
   * Attempt poll-based recovery for a pending interrupted stream.
   *
   * Skipped while the conversation still has a LIVE stream request (R13):
   * its lifecycle listener owns foreground handling (abort + journal
   * resume), and racing it with poll recovery here could finalize the
   * message element while the resume reader is still replaying into it.
   */
  private async attemptPendingStreamRecovery(hiddenDuration: number): Promise<void> {
    const store = useStore.getState();
    const streamingConvId = store.streamingConversationId;
    if (!streamingConvId || !this.recovery.hasPending(streamingConvId)) return;

    if (store.getActiveRequest(streamingConvId)) {
      log.debug('Skipping poll recovery - live stream request owns foregrounding', {
        conversationId: streamingConvId,
      });
      return;
    }

    log.info('Attempting stream recovery on foreground', {
      conversationId: streamingConvId,
      hiddenDuration,
    });
    await this.recovery.attempt(streamingConvId);
  }

  /**
   * Schedule the next poll.
   */
  private schedulePoll(): void {
    this.pollTimeoutId = setTimeout(() => {
      if (this.isVisible) {
        void this.incrementalSync();
      }
      this.schedulePoll();
    }, SYNC_POLL_INTERVAL_MS);
  }

  /** Baseline for the planner view's new-message check (see PlannerSync.setBaseline). */
  setPlannerBaseline(messageCount: number): void {
    this.planner.setBaseline(messageCount);
  }

  /**
   * Set the agent being viewed for sync tracking.
   * Call this when entering/leaving an agent conversation.
   */
  setViewedAgent(agentId: string | null, messageCount?: number): void {
    this.agentConversation.setViewedAgent(agentId, messageCount);
  }
}

// Singleton instance
let syncManagerInstance: SyncManager | null = null;

/**
 * Initialize the global SyncManager instance.
 */
export function initSyncManager(callbacks: SyncManagerCallbacks, recovery: StreamRecoveryHooks): SyncManager {
  if (syncManagerInstance) {
    syncManagerInstance.stop();
  }
  syncManagerInstance = new SyncManager(callbacks, recovery);
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
