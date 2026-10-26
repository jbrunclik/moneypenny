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

import { conversations as conversationsApi } from '../api/conversations';
import { useStore } from '../state/store';
import { toast } from '../components/Toast';
import { createLogger } from '../utils/logger';
import {
  SYNC_POLL_INTERVAL_MS,
  SYNC_FULL_SYNC_THRESHOLD_MS,
  SYNC_MAX_CHANGE_PAGES,
} from '../config';
import { hasPendingRecovery, attemptRecovery, cancelRecovery } from '../core/stream-recovery';
import type { ConversationSummary, SyncResponse } from '../types/api';
import { SyncState, type SyncManagerCallbacks } from './sync-state';
import { inLoadedWindow, isPaginationDiscovered } from './pagination-window';
import { PlannerSync } from './planner-sync';
import { AgentConversationSync } from './agent-conversation-sync';
import { syncCommandCenter } from './command-center-sync';
import { applyChanges, applyDeferredState } from './summary-merge';

const log = createLogger('sync');

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

  constructor(callbacks: SyncManagerCallbacks) {
    this.callbacks = callbacks;
    this.state = new SyncState(callbacks, toast);
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

      this.applyFullSync(result.conversations, knownBefore);
      log.info('Full sync completed', {
        conversationCount: result.conversations.length,
        serverTime: result.server_time,
      });

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

  /** Fetch and apply every change after the cursor (paging while has_more). */
  private async syncChangeLog(): Promise<void> {
    for (let page = 0; page < SYNC_MAX_CHANGE_PAGES && this.changeCursor !== null; page++) {
      this.state.markSyncRequest();
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
    // Before the removals below change the main list
    const lists = this.archiveOrTrashTouched(result);
    if (lists.archive || lists.trash) this.callbacks.onArchiveOrTrashChanged?.(lists);

    let changed = false;
    for (const id of result.removed_ids ?? []) {
      if (this.state.changedLocallySinceRequest(id)) continue;
      changed = this.removeExternally(id, 'deleted') || changed;
    }

    const store = useStore.getState();
    const openConv = store.currentConversation;
    const existing: ConversationSummary[] = [];
    for (const conv of result.conversations) {
      if (this.state.changedLocallySinceRequest(conv.id)) continue;
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

    this.state.notifiedCurrentUpdate = false;
    if (existing.length > 0) {
      applyChanges(this.state, existing, false);
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
      !this.state.notifiedCurrentUpdate &&
      !this.state.streamingConversations.has(open.id) &&
      (!changedOpen.archived || open.archived)
    ) {
      this.callbacks.onCurrentConversationExternalUpdate(changedOpen.message_count);
    }
  }

  /**
   * Which of the archive / trash lists a change-log page disagrees with: a
   * chat archived or trashed there that the list lacks, or one the list
   * still holds that left it (unarchived, restored, deleted for good). Both
   * lists are loaded at startup (their counts badge the user menu), so a
   * mismatch is a change made elsewhere; this device's own changes already
   * moved the rows and echo back as a match.
   */
  private archiveOrTrashTouched(result: SyncResponse): { archive: boolean; trash: boolean } {
    const { archivedConversations, trashedConversations } = useStore.getState();
    const archived = new Set(archivedConversations.map((c) => c.id));
    const trashed = new Set(trashedConversations.map((c) => c.id));
    const lists = { archive: false, trash: false };
    for (const id of result.removed_ids ?? []) {
      if (this.state.changedLocallySinceRequest(id)) continue;
      lists.archive ||= archived.has(id);
      lists.trash ||= trashed.has(id);
    }
    for (const conv of result.conversations) {
      if (this.state.changedLocallySinceRequest(conv.id)) continue;
      const inArchive = Boolean(conv.archived) && !conv.trashed;
      lists.archive ||= inArchive !== archived.has(conv.id);
      lists.trash ||= Boolean(conv.trashed) !== trashed.has(conv.id);
    }
    return lists;
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
    this.state.deferredUpdates.delete(id);
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
    if (!conv.pinned && !inLoadedWindow(conv.updated_at)) {
      this.state.localMessageCounts.set(conv.id, conv.message_count);
      return false;
    }
    const known = this.state.localMessageCounts.get(conv.id);
    const isNew = conv.created_at ? !isPaginationDiscovered(this.state.initialLoadTime, conv.created_at) : known === undefined;
    const baseline = known ?? (isNew ? 0 : conv.message_count);
    this.state.localMessageCounts.set(conv.id, baseline);
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
   * They have separate sync mechanisms (PlannerSync, AgentConversationSync).
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
      this.state.localMessageCounts.delete(id);
    }

    // Separate existing conversations (for update) from new conversations (for add)
    const existingServerConvs: ConversationSummary[] = [];
    const newServerConvs: ConversationSummary[] = [];

    for (const serverConv of serverConversations) {
      if (localIds.has(serverConv.id)) {
        existingServerConvs.push(serverConv);
      } else if (this.state.changedLocallySinceRequest(serverConv.id)) {
        // Trashed / archived here after this snapshot was read: not back
        continue;
      } else {
        // Belongs in the loaded part of the list (new, continued or restored
        // elsewhere) or only further down (pagination brings it). By the
        // list, not initialLoadTime: a conversation created on another
        // device while this page booted predates that time and was lost.
        // A pinned one always belongs (the pinned group is never paged)
        if (serverConv.pinned || inLoadedWindow(serverConv.updated_at)) {
          newServerConvs.push(serverConv);
        } else {
          // Pagination-discovered: just track the message count for when it's loaded via pagination
          this.state.localMessageCounts.set(serverConv.id, serverConv.message_count);
          log.debug('Full sync: skipping pagination-discovered conversation', {
            conversationId: serverConv.id,
            updated_at: serverConv.updated_at,
          });
        }
      }
    }

    // Apply updates to existing conversations
    applyChanges(this.state, existingServerConvs, true);

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
      const knownCount = this.state.localMessageCounts.get(serverConv.id);
      const createdBeforeLoad = isPaginationDiscovered(this.state.initialLoadTime, serverConv.created_at ?? serverConv.updated_at);
      const baseline = knownCount ?? (createdBeforeLoad ? serverConv.message_count : 0);
      this.state.localMessageCounts.set(serverConv.id, baseline);
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
    if (!this.state.localMessageCounts.has(convId)) {
      this.state.localMessageCounts.set(convId, messageCount);
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
    if (this.state.reportedReadCounts.get(convId) === count) return;
    this.state.reportedReadCounts.set(convId, count);
    conversationsApi.markRead(convId, count).catch((error: unknown) => {
      this.state.reportedReadCounts.delete(convId);
      log.debug('Reporting read state failed', { conversationId: convId, error });
    });
  }

  /**
   * Our own message was saved: it is read (we wrote it) - reported right
   * away, or other devices badged our in-progress turn until it ended.
   * The reply placeholder still counts as one unread there: a reply coming.
   */
  noteOwnMessageSaved(convId: string): void {
    const known = this.state.localMessageCounts.get(convId);
    if (known !== undefined) this.reportRead(convId, known + 1);
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
    this.reportRead(convId, isCurrent ? count : count - 1);
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
