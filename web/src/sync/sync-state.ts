/**
 * The state the sync modules share: per-conversation message-count
 * baselines, conversations whose own turn is running (and the summaries
 * deferred until it ends), read reports, and the ordering of local changes
 * against in-flight sync requests.
 */

import type { ConversationSummary } from '../types/api';

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
  /** Called when another device moved chats into or out of the archive / trash (reload those lists) */
  onArchiveOrTrashChanged?: (lists: { archive: boolean; trash: boolean }) => void;
}

/** User-facing notices. Passed in: sync never imports UI (F1). */
export interface SyncNotifier {
  info: (message: string) => void;
  warning: (message: string) => void;
}

export class SyncState {
  /**
   * Tracks when SyncManager first started (initial page load time).
   * Used to distinguish pagination-discovered conversations from actually new ones.
   */
  initialLoadTime: string | null = null;

  /**
   * Tracks the message count we last knew about for each conversation.
   * Used to calculate unread counts.
   */
  readonly localMessageCounts: Map<string, number> = new Map();

  /**
   * Set of conversation IDs that are currently streaming.
   * Sync updates for these conversations are deferred to avoid false unread counts.
   */
  readonly streamingConversations: Set<string> = new Set();

  /**
   * The latest server summary that arrived for a conversation while this
   * device's own turn was running there. It was skipped (our own messages
   * would read as unread), but the poll moved on past it - applied when the
   * turn ends so a rename or the other device's messages aren't lost.
   */
  readonly deferredUpdates: Map<string, ConversationSummary> = new Map();

  /** The read count last reported to the server per conversation (dedupe). */
  readonly reportedReadCounts: Map<string, number> = new Map();

  /** applyChanges told the open conversation about an external update. */
  notifiedCurrentUpdate = false;

  /**
   * Local changes (rename, pin, archive, trash, restore, anonymous) bump a
   * counter; a sync response requested BEFORE a conversation's latest local
   * change carries its older state and must not re-apply it (the old title
   * back, a trashed chat re-added) - the next poll brings the current one.
   */
  private localChangeSeq = 0;
  private localChangeAt: Map<string, number> = new Map();
  private syncRequestSeq = 0;

  constructor(
    readonly callbacks: SyncManagerCallbacks,
    readonly notify: SyncNotifier
  ) {}

  /** A local change to a conversation (see localChangeSeq). */
  noteLocalChange(convId: string): void {
    this.localChangeAt.set(convId, ++this.localChangeSeq);
  }

  /** A sync request is about to go out: later local changes outrank its answer. */
  markSyncRequest(): void {
    this.syncRequestSeq = this.localChangeSeq;
  }

  /** Changed here after the in-flight sync request was made: skip its state. */
  changedLocallySinceRequest(convId: string): boolean {
    return (this.localChangeAt.get(convId) ?? 0) > this.syncRequestSeq;
  }

  /** Forget everything tracked (stop / logout). */
  clear(): void {
    this.initialLoadTime = null;
    this.localMessageCounts.clear();
    this.streamingConversations.clear();
    this.deferredUpdates.clear();
    this.reportedReadCounts.clear();
    this.localChangeAt.clear();
  }
}
