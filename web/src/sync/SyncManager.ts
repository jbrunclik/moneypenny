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

import { agents as agentsApi } from '../api/agents';
import { conversations as conversationsApi } from '../api/conversations';
import { planner as plannerApi } from '../api/planner';
import { useStore } from '../state/store';
import { toast } from '../components/Toast';
import { createLogger } from '../utils/logger';
import {
  SYNC_POLL_INTERVAL_MS,
  SYNC_FULL_SYNC_THRESHOLD_MS,
  SYNC_MAX_CHANGE_PAGES,
} from '../config';
import { hasPendingRecovery, attemptRecovery, cancelRecovery } from '../core/stream-recovery';
import { DEFAULT_CONVERSATION_TITLE, type ConversationSummary, type SyncResponse } from '../types/api';

const log = createLogger('sync');

/** Callbacks for SyncManager events */
export interface SyncManagerCallbacks {
  /** Called when conversations list should be re-rendered */
  onConversationsUpdated: () => void;
  /** Called when a conversation was deleted while user was viewing it */
  onCurrentConversationDeleted: () => void;
  /** Called when the current conversation has new messages from another device */
  onCurrentConversationExternalUpdate: (messageCount: number) => void;
  /** Called when the current conversation was renamed on another device */
  onCurrentConversationRenamed?: (title: string) => void;
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
/** Why a conversation left this device's list from another device. */
type ExternalRemoval = 'deleted' | 'trashed' | 'archived';

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
   * The latest server summary that arrived for a conversation while this
   * device's own turn was running there. It was skipped (our own messages
   * would read as unread), but the poll moved on past it - applied when the
   * turn ends so a rename or the other device's messages aren't lost.
   */
  private deferredUpdates: Map<string, ConversationSummary> = new Map();

  /** A full sync was requested while another sync held the lock. */
  private fullSyncQueued = false;

  /** An incremental sync was requested while another sync held the lock. */
  private incrementalSyncQueued = false;

  /**
   * Local changes (rename, pin, archive, trash, restore, anonymous) bump a
   * counter; a sync response requested BEFORE a conversation's latest local
   * change carries its older state and must not re-apply it (the old title
   * back, a trashed chat re-added) - the next poll brings the current one.
   */
  private localChangeSeq = 0;
  private localChangeAt: Map<string, number> = new Map();
  private syncRequestSeq = 0;

  /** Stopped (logout) - a start still awaiting its first sync must not go on. */
  private stopped = false;

  /** The read count last reported to the server per conversation (dedupe). */
  private reportedReadCounts: Map<string, number> = new Map();

  /** applyChanges told the open conversation about an external update. */
  private notifiedCurrentUpdate = false;

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
          this.localMessageCounts.set(conv.id, conv.messageCount);
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
    window.removeEventListener('pageshow', this.handlePageShow);
    window.removeEventListener('online', this.handleOnline);

    this.lastSyncTime = null;
    this.changeCursor = null;
    this.lastHiddenTime = null;
    this.initialLoadTime = null;
    this.localMessageCounts.clear();
    this.streamingConversations.clear();
    this.deferredUpdates.clear();
    this.reportedReadCounts.clear();
    this.localChangeAt.clear();
    this.fullSyncQueued = false;
    this.incrementalSyncQueued = false;
    this.stopped = true;
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
      // Don't drop it: a full sync is how deletions are noticed (a frozen
      // iOS poll timer firing on resume used to swallow the resume's one)
      log.debug('Full sync queued - another sync in progress');
      this.fullSyncQueued = true;
      return;
    }

    this.isSyncing = true;
    log.debug('Performing full sync');

    try {
      // Prune stale entries before syncing
      this.pruneLocalMessageCounts();

      // Only conversations known BEFORE the request can be "missing" from
      // its answer: one created, restored or unarchived here while it was
      // in flight is absent from the server's older snapshot - it was
      // removed (open: "This conversation was deleted.") until the change
      // log re-added it a minute later
      const knownBefore = new Set(useStore.getState().conversations.map((c) => c.id));
      this.syncRequestSeq = this.localChangeSeq;
      const result = await conversationsApi.sync(null, true);
      this.lastSyncTime = result.server_time;
      // Taken before the server's query: changes during it re-arrive next time
      if (typeof result.cursor === 'number') this.changeCursor = result.cursor;

      // Set initialLoadTime on first full sync (before applying results)
      // This allows us to distinguish pagination-discovered vs actually new conversations
      if (!this.initialLoadTime) {
        this.initialLoadTime = result.server_time;
        log.debug('Initial load time established', { initialLoadTime: this.initialLoadTime });
      }

      this.applyFullSync(result.conversations, knownBefore);
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
      this.runQueuedFullSync();
    }
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

  /** A local change to a conversation (see localChangeSeq). */
  noteLocalChange(convId: string): void {
    this.localChangeAt.set(convId, ++this.localChangeSeq);
  }

  /** Changed here after the in-flight sync request was made: skip its state. */
  private changedLocallySinceRequest(convId: string): boolean {
    return (this.localChangeAt.get(convId) ?? 0) > this.syncRequestSeq;
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

    if (!this.lastSyncTime) {
      // No previous sync time, do a full sync instead
      await this.fullSync();
      return;
    }

    this.isSyncing = true;
    log.debug('Performing incremental sync', { since: this.lastSyncTime, cursor: this.changeCursor });

    try {
      if (this.changeCursor !== null) {
        await this.syncChangeLog();
      } else {
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
      this.runQueuedFullSync();
    }
  }

  /** Fetch and apply every change after the cursor (paging while has_more). */
  private async syncChangeLog(): Promise<void> {
    for (let page = 0; page < SYNC_MAX_CHANGE_PAGES && this.changeCursor !== null; page++) {
      this.syncRequestSeq = this.localChangeSeq;
      const result = await conversationsApi.syncChanges(this.changeCursor);
      this.lastSyncTime = result.server_time;
      this.applyChangeLog(result);
      if (typeof result.cursor === 'number') this.changeCursor = result.cursor;
      if (!result.has_more) return;
    }
  }

  /**
   * Apply one change-log page: removals (deleted / trashed / archived on
   * another device) leave the list right away - the timestamp sync only
   * noticed them on a full sync, which a visible tab never ran - then
   * updates, pins and conversations that (re)appeared.
   */
  private applyChangeLog(result: SyncResponse): void {
    let changed = false;
    for (const id of result.removed_ids ?? []) {
      if (this.changedLocallySinceRequest(id)) continue;
      changed = this.removeExternally(id, 'deleted') || changed;
    }

    const store = useStore.getState();
    const openConv = store.currentConversation;
    const existing: ConversationSummary[] = [];
    for (const conv of result.conversations) {
      if (this.changedLocallySinceRequest(conv.id)) continue;
      // An archived chat that is OPEN here (archive view, search, deep link):
      // its changes - our own read echo included - are just changes to the
      // open chat, not "archived on another device"
      if (conv.archived && !conv.trashed && openConv?.id === conv.id && openConv.archived) {
        continue;
      }
      if (conv.trashed || conv.archived) {
        changed = this.removeExternally(conv.id, conv.trashed ? 'trashed' : 'archived') || changed;
      } else if (store.conversations.some((c) => c.id === conv.id)) {
        existing.push(conv);
      } else {
        changed = this.addFromChangeLog(conv) || changed;
      }
    }

    this.notifiedCurrentUpdate = false;
    if (existing.length > 0) {
      this.applyChanges(existing, false);
      changed = true;
    }
    if (changed) this.callbacks.onConversationsUpdated();

    // Any change to the open conversation - not only a higher count (a
    // delete, a regenerate or another device's finished stream keep it the
    // same), and also when it isn't in the loaded sidebar list (opened from
    // search or a deep link). The merge diffs against what is rendered, so
    // our own changes are a no-op.
    const open = useStore.getState().currentConversation;
    const changedOpen = result.conversations.find((c) => c.id === open?.id && !c.trashed);
    if (
      open &&
      changedOpen &&
      !this.notifiedCurrentUpdate &&
      !this.streamingConversations.has(open.id) &&
      (!changedOpen.archived || open.archived)
    ) {
      this.callbacks.onCurrentConversationExternalUpdate(changedOpen.message_count);
    }
  }

  /**
   * A conversation removed on another device. An archived one that is open
   * here stays open (it's still readable); trashed or deleted closes.
   * Returns whether anything changed on this device.
   */
  private removeExternally(id: string, reason: ExternalRemoval): boolean {
    const store = useStore.getState();
    const inList = store.conversations.some((c) => c.id === id);
    const current = store.currentConversation?.id === id ? store.currentConversation : null;
    // Gone here too: a recovery of its interrupted reply ends silently
    if (reason !== 'archived') cancelRecovery(id);
    // The known count stays (pruned on the next full sync): a restore or
    // unarchive then compares against it instead of counting it all unread
    this.deferredUpdates.delete(id);
    if (!inList && !current) return false;
    log.info('Conversation removed on another device', { conversationId: id, reason });

    if (reason === 'archived') {
      if (inList) store.removeConversation(id);
      if (current) {
        store.setCurrentConversation({ ...current, archived: true });
        toast.info('This conversation was archived on another device.');
      }
      return true;
    }

    if (inList) store.removeConversation(id);
    if (current) {
      toast.warning(
        reason === 'trashed'
          ? 'This conversation was moved to the trash on another device.'
          : 'This conversation was deleted on another device.'
      );
      this.callbacks.onCurrentConversationDeleted();
    }
    return true;
  }

  /**
   * A live conversation the list doesn't hold: new on another device,
   * continued there, or restored/unarchived there. Added when it belongs in
   * the loaded part of the list (older ones arrive with pagination). Only a
   * conversation created after this page loaded counts as wholly unread; a
   * restored or unarchived one is old content.
   */
  private addFromChangeLog(conv: ConversationSummary): boolean {
    const store = useStore.getState();
    if (!conv.pinned && !this.inLoadedWindow(conv.updated_at)) {
      this.localMessageCounts.set(conv.id, conv.message_count);
      return false;
    }
    const known = this.localMessageCounts.get(conv.id);
    const isNew = conv.created_at ? !this.isPaginationDiscovered(conv.created_at) : known === undefined;
    const baseline = known ?? (isNew ? 0 : conv.message_count);
    this.localMessageCounts.set(conv.id, baseline);
    const unread =
      conv.read_count !== undefined
        ? Math.max(0, conv.message_count - conv.read_count)
        : Math.max(0, conv.message_count - baseline);
    log.info('Conversation appeared from another device', { conversationId: conv.id, isNew });

    store.addConversation({
      id: conv.id,
      title: conv.title,
      model: conv.model,
      created_at: conv.created_at ?? conv.updated_at,
      updated_at: conv.updated_at,
      messageCount: conv.message_count,
      last_message_preview: conv.last_message_preview,
      pinned: conv.pinned,
      unreadCount: unread,
      hasExternalUpdate: false,
    });
    return true;
  }

  /** Whether `updatedAt` falls inside the part of the list already loaded. */
  private inLoadedWindow(updatedAt: string): boolean {
    const store = useStore.getState();
    if (!store.conversationsPagination.hasMore) return true;
    const unpinned = store.conversations.filter((c) => !c.pinned);
    const oldest = unpinned[unpinned.length - 1];
    if (!oldest) return true;
    return new Date(updatedAt).getTime() >= new Date(oldest.updated_at).getTime();
  }

  /**
   * Apply full sync results - handles deletions, updates, AND new conversations.
   *
   * Full sync:
   * 1. Updates existing conversations (message counts, titles, etc.)
   * 2. Detects deletions (conversations in store but not on server)
   * 3. Adds NEW conversations created on other devices (after initialLoadTime)
   *
   * Note: Pagination-discovered conversations (older than initialLoadTime) are NOT added,
   * preserving the pagination behavior. Only genuinely new conversations are added.
   *
   * Note: The sync endpoint only returns regular conversations - planner and autonomous
   * agent conversations are filtered out at the backend (is_planning=0, is_agent=0).
   * They have separate sync mechanisms (syncPlanner, syncAgentConversation).
   */
  private applyFullSync(serverConversations: ConversationSummary[], knownBefore: Set<string>): void {
    const store = useStore.getState();
    const serverIds = new Set(serverConversations.map((c) => c.id));
    const localIds = new Set(store.conversations.map((c) => c.id));

    // Detect deleted conversations (in local but not in server)
    // Skip temp conversations (not yet persisted)
    // Skip archived conversations too: sync intentionally excludes them, so
    // a deep-linked archived conversation would otherwise be "deleted" and
    // kicked out of view seconds after loading
    const deletedIds = store.conversations
      .filter(
        (c) => !c.id.startsWith('temp-') && !c.archived && knownBefore.has(c.id) && !serverIds.has(c.id)
      )
      .map((c) => c.id);

    // Handle deletions
    for (const id of deletedIds) {
      log.info('Conversation deleted externally', { conversationId: id });
      cancelRecovery(id);

      if (store.currentConversation?.id === id) {
        toast.warning('This conversation was deleted.');
        this.callbacks.onCurrentConversationDeleted();
      }

      store.removeConversation(id);
      this.localMessageCounts.delete(id);
    }

    // Separate existing conversations (for update) from new conversations (for add)
    const existingServerConvs: ConversationSummary[] = [];
    const newServerConvs: ConversationSummary[] = [];

    for (const serverConv of serverConversations) {
      if (localIds.has(serverConv.id)) {
        existingServerConvs.push(serverConv);
      } else if (this.changedLocallySinceRequest(serverConv.id)) {
        // Trashed / archived here after this snapshot was read: not back
        continue;
      } else {
        // Belongs in the loaded part of the list (new, continued or restored
        // elsewhere) or only further down (pagination brings it). By the
        // list, not initialLoadTime: a conversation created on another
        // device while this page booted predates that time and was lost.
        // A pinned one always belongs (the pinned group is never paged)
        if (serverConv.pinned || this.inLoadedWindow(serverConv.updated_at)) {
          newServerConvs.push(serverConv);
        } else {
          // Pagination-discovered: just track the message count for when it's loaded via pagination
          this.localMessageCounts.set(serverConv.id, serverConv.message_count);
          log.debug('Full sync: skipping pagination-discovered conversation', {
            conversationId: serverConv.id,
            updated_at: serverConv.updated_at,
          });
        }
      }
    }

    // Apply updates to existing conversations
    this.applyChanges(existingServerConvs, true);

    // Add genuinely new conversations (created on other devices after initialLoadTime)
    for (const serverConv of newServerConvs) {
      log.info('Full sync: adding new conversation from another device', {
        conversationId: serverConv.id,
        updated_at: serverConv.updated_at,
        messageCount: serverConv.message_count,
      });

      // Unread: the server's read state; without it, all of a conversation
      // created after this page loaded, or beyond a count we already knew -
      // an older one (continued, restored) isn't wholly new
      const knownCount = this.localMessageCounts.get(serverConv.id);
      const createdBeforeLoad = this.isPaginationDiscovered(serverConv.created_at ?? serverConv.updated_at);
      const baseline = knownCount ?? (createdBeforeLoad ? serverConv.message_count : 0);
      this.localMessageCounts.set(serverConv.id, baseline);
      const unreadCount =
        serverConv.read_count !== undefined
          ? Math.max(0, serverConv.message_count - serverConv.read_count)
          : Math.max(0, serverConv.message_count - baseline);

      store.addConversation({
        id: serverConv.id,
        title: serverConv.title,
        model: serverConv.model,
        created_at: serverConv.created_at ?? serverConv.updated_at,
        updated_at: serverConv.updated_at,
        messageCount: serverConv.message_count,
        last_message_preview: serverConv.last_message_preview,
        pinned: serverConv.pinned,
        unreadCount,
        hasExternalUpdate: false,
      });
    }

    if (deletedIds.length > 0 || existingServerConvs.length > 0 || newServerConvs.length > 0) {
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
      if (this.changedLocallySinceRequest(serverConv.id)) continue;
      // Skip conversations that are currently streaming to avoid false unread counts
      // The local message count will be updated when streaming completes
      if (this.streamingConversations.has(serverConv.id)) {
        log.debug('Deferring sync for streaming conversation', { conversationId: serverConv.id });
        this.deferredUpdates.set(serverConv.id, serverConv);
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
          this.notifiedCurrentUpdate = true;
          this.callbacks.onCurrentConversationExternalUpdate(serverConv.message_count);
        } else {
          // User is not viewing - count as unread
          unreadCount = serverConv.message_count - localCount;
        }
      }
      // The server's read state is what our reports dedupe against (a device
      // that reported the same count, or a higher one, makes ours moot)
      if (serverConv.read_count !== undefined) {
        this.reportedReadCounts.set(serverConv.id, serverConv.read_count);
      }
      // Another device toggled anonymous mode: adopt it (the next send here
      // must not turn it back on)
      if (serverConv.anonymous_mode !== undefined) {
        store.setAnonymousMode(serverConv.id, serverConv.anonymous_mode);
      }
      // Server-side read state wins: shared by the user's devices, so a chat
      // read on the phone isn't unread here (the local count only drives the
      // open conversation's change detection)
      if (serverConv.read_count !== undefined && !isCurrentConv) {
        unreadCount = Math.max(0, serverConv.message_count - serverConv.read_count);
      }

      if (existing && serverConv.pinned !== undefined && Boolean(existing.pinned) !== serverConv.pinned) {
        store.updateConversation(serverConv.id, { pinned: serverConv.pinned });
      }
      if (existing) {
        // The open chat's header shows the title too (the sidebar re-renders)
        if (isCurrentConv && existing.title !== serverConv.title) {
          this.callbacks.onCurrentConversationRenamed?.(serverConv.title);
        }
        // Update existing conversation
        store.updateConversation(serverConv.id, {
          title: serverConv.title,
          updated_at: serverConv.updated_at,
          messageCount: serverConv.message_count,
          last_message_preview: serverConv.last_message_preview,
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
        // For pagination-discovered, no badge (user just hasn't scrolled to see it yet).
        // An older conversation continued on another device has a count we
        // already know (full sync tracks unloaded ones): only the rest is new.
        const knownCount = this.localMessageCounts.get(serverConv.id);
        const unreadCount = isPaginationDiscovered
          ? 0
          : Math.max(0, serverConv.message_count - (knownCount ?? 0));

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
        // the baseline until the user views the conversation
        if (knownCount === undefined) this.localMessageCounts.set(serverConv.id, 0);

        store.addConversation({
          id: serverConv.id,
          title: serverConv.title,
          model: serverConv.model,
          created_at: serverConv.updated_at, // We don't have created_at in sync response
          updated_at: serverConv.updated_at,
          messageCount: serverConv.message_count,
          last_message_preview: serverConv.last_message_preview,
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

    // Also moves the planner/agent view baselines when that view is open
    this.applyLocalCount(convId, messageCount);
    this.reportRead(convId, messageCount);
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
   * Record on the server that this device has shown `count` messages - the
   * read state behind every device's unread badge. Deduplicated; a failed
   * report is retried with the next one.
   */
  private reportRead(convId: string, count: number): void {
    if (convId.startsWith('temp-') || count < 0) return;
    if (this.reportedReadCounts.get(convId) === count) return;
    this.reportedReadCounts.set(convId, count);
    conversationsApi.markRead(convId, count).catch((error: unknown) => {
      this.reportedReadCounts.delete(convId);
      log.debug('Reporting read state failed', { conversationId: convId, error });
    });
  }

  /**
   * Our own message was saved: it is read (we wrote it) - reported right
   * away, or other devices badged our in-progress turn until it ended.
   * The reply placeholder still counts as one unread there: a reply coming.
   */
  noteOwnMessageSaved(convId: string): void {
    const known = this.localMessageCounts.get(convId);
    if (known !== undefined) this.reportRead(convId, known + 1);
  }

  /**
   * Update local message count after sending a message.
   * Prefer setLocalMessageCount with the server's count when a turn reports it.
   */
  incrementLocalMessageCount(convId: string, increment: number = 1): void {
    const currentCount = this.localMessageCounts.get(convId) || 0;
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
    this.reportRead(convId, isCurrent ? count : count - 1);
  }

  /** The local baseline (+ planner/agent view baselines), no read report. */
  private applyLocalCount(convId: string, count: number): void {
    this.localMessageCounts.set(convId, count);
    const store = useStore.getState();
    store.updateConversation(convId, { messageCount: count });

    if (store.currentConversation?.id !== convId) return;
    if (store.isPlannerView && this.plannerMessageCount !== null) {
      this.plannerMessageCount = count;
    }
    if (this.viewedAgentId && this.agentConversationMessageCount !== null) {
      this.agentConversationMessageCount = count;
    }
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
      const deferred = this.deferredUpdates.get(convId);
      if (deferred) {
        this.deferredUpdates.delete(convId);
        if (this.changeCursor !== null) {
          // The summary is a snapshot from DURING our turn. Its counts are
          // moot (the turn set the exact one), and its untitled "New
          // Conversation" must not revert the title the turn just set - but
          // the other device's changes in it (a rename, a pin) must not be
          // lost either: a poll that landed after our final save already
          // moved the cursor past it, so nothing re-sends them.
          this.applyDeferredState(deferred);
          void this.incrementalSync();
        } else {
          // Legacy timestamp sync never re-sends it. Callers set the turn's
          // count first, so only the other device's changes remain.
          this.applyChanges([deferred], false);
          this.callbacks.onConversationsUpdated();
        }
      }
    }
  }

  /** A deferred snapshot's non-count state (see setConversationStreaming). */
  private applyDeferredState(summary: ConversationSummary): void {
    const store = useStore.getState();
    const local = store.conversations.find((c) => c.id === summary.id);
    if (!local) return;
    const updates: Partial<typeof local> = {};
    if (summary.title !== DEFAULT_CONVERSATION_TITLE && summary.title !== local.title) {
      updates.title = summary.title;
      if (store.currentConversation?.id === summary.id) {
        this.callbacks.onCurrentConversationRenamed?.(summary.title);
      }
    }
    if (summary.pinned !== undefined && Boolean(local.pinned) !== summary.pinned) {
      updates.pinned = summary.pinned;
    }
    if (Object.keys(updates).length > 0) {
      store.updateConversation(summary.id, updates);
      this.callbacks.onConversationsUpdated();
    }
    if (summary.anonymous_mode !== undefined) store.setAnonymousMode(summary.id, summary.anonymous_mode);
    // The open chat may have the other device's messages in it too
    if (store.currentConversation?.id === summary.id) {
      this.callbacks.onCurrentConversationExternalUpdate(summary.message_count);
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
  private async handleVisibilityChange(): Promise<void> {
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
        this.fullSync();
      } else {
        // Quick incremental sync on tab refocus
        this.incrementalSync();
      }
    }
  }

  /**
   * Handle bfcache restores - iOS can restore a page from the back/forward
   * cache without firing visibilitychange (R14), leaving a pending stream
   * recovery unattempted until the next poll.
   */
  private async handlePageShow(event: PageTransitionEvent): Promise<void> {
    if (!event.persisted) return;
    log.info('Page restored from bfcache');
    // iOS can restore without a visibilitychange to "visible" after the
    // "hidden" one - polling stayed paused until the next visibility event
    this.isVisible = document.visibilityState === 'visible';
    void this.attemptPendingStreamRecovery(0);
    this.incrementalSync();
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
    if (!streamingConvId || !hasPendingRecovery(streamingConvId)) return;

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
    await attemptRecovery(streamingConvId);
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
   * Baseline for the planner view's new-message check, set when it loads.
   * Left to the first poll, a change made in the minute after opening the
   * planner set the baseline instead of being noticed. (A baseline that is
   * off by a filtered placeholder only causes a no-op merge.)
   */
  setPlannerBaseline(messageCount: number): void {
    this.plannerMessageCount = messageCount;
    // Re-baseline the reset marker too: this device just loaded (possibly
    // auto-reset) or reset the planner itself - the next poll's new
    // last_reset is ours, not "reset in another tab" (whose reload would
    // re-render over the running analysis)
    this.plannerLastReset = null;
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
