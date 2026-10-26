/**
 * Merging server conversation summaries into the loaded list: unread counts
 * and external updates against the local message-count baselines, the
 * server's read state, renames, pins and anonymous mode - and the deferred
 * summary of a conversation whose own turn just ended.
 */

import { useStore, type AppState } from '../state/store';
import { createLogger } from '../utils/logger';
import { DEFAULT_CONVERSATION_TITLE, type Conversation, type ConversationSummary } from '../types/api';
import { isPaginationDiscovered } from './pagination-window';
import type { SyncState } from './sync-state';

const log = createLogger('sync');

interface UnreadState {
  unreadCount: number;
  hasExternalUpdate: boolean;
}

/**
 * Apply conversation changes from server.
 *
 * The store snapshot is taken once: a conversation added while merging is
 * not "existing" for a later summary of the same page.
 */
export function applyChanges(
  state: SyncState,
  serverConversations: ConversationSummary[],
  isFullSync: boolean
): void {
  const store = useStore.getState();

  for (const serverConv of serverConversations) {
    if (state.changedLocallySinceRequest(serverConv.id)) continue;
    if (deferWhileStreaming(state, serverConv)) continue;
    if (!applySummary(state, store, serverConv, isFullSync)) return;
  }
}

/**
 * Skip conversations that are currently streaming to avoid false unread
 * counts; the local message count is updated when streaming completes.
 */
function deferWhileStreaming(state: SyncState, serverConv: ConversationSummary): boolean {
  if (!state.streamingConversations.has(serverConv.id)) return false;
  log.debug('Deferring sync for streaming conversation', { conversationId: serverConv.id });
  state.deferredUpdates.set(serverConv.id, serverConv);
  return true;
}

/** Merge one summary; false stops the whole merge (see the full-sync guard). */
function applySummary(
  state: SyncState,
  store: AppState,
  serverConv: ConversationSummary,
  isFullSync: boolean
): boolean {
  const existing = store.conversations.find((c) => c.id === serverConv.id);
  const localCount = state.localMessageCounts.get(serverConv.id) || 0;
  const isCurrentConv = store.currentConversation?.id === serverConv.id;

  const unread = detectUnread(state, serverConv, localCount, isCurrentConv);
  adoptServerState(state, store, serverConv);
  // Server-side read state wins: shared by the user's devices, so a chat
  // read on the phone isn't unread here (the local count only drives the
  // open conversation's change detection)
  if (serverConv.read_count !== undefined && !isCurrentConv) {
    unread.unreadCount = Math.max(0, serverConv.message_count - serverConv.read_count);
  }

  if (existing) {
    updateExisting(state, store, serverConv, existing, isCurrentConv, unread);
  } else {
    if (isFullSync) {
      // Full sync should never add new conversations - they should come via pagination
      // This is a safety check in case applyFullSync() filtering fails
      log.warn('Full sync attempted to add new conversation (should not happen)', {
        conversationId: serverConv.id,
      });
      return false;
    }
    if (!addDiscovered(state, store, serverConv)) return true;
  }

  updateLocalBaseline(state, serverConv, existing !== undefined, isFullSync, isCurrentConv, unread.unreadCount);
  return true;
}

/**
 * New messages beyond the local baseline: unread when the user isn't
 * viewing the conversation, an external update (reported right away) when
 * they are.
 */
function detectUnread(
  state: SyncState,
  serverConv: ConversationSummary,
  localCount: number,
  isCurrentConv: boolean
): UnreadState {
  if (serverConv.message_count <= localCount) return { unreadCount: 0, hasExternalUpdate: false };
  if (!isCurrentConv) {
    return { unreadCount: serverConv.message_count - localCount, hasExternalUpdate: false };
  }
  log.info('External update detected for current conversation', {
    conversationId: serverConv.id,
    serverMessageCount: serverConv.message_count,
    localMessageCount: localCount,
    isStreaming: state.streamingConversations.has(serverConv.id),
  });
  state.notifiedCurrentUpdate = true;
  state.callbacks.onCurrentConversationExternalUpdate(serverConv.message_count);
  return { unreadCount: 0, hasExternalUpdate: true };
}

/** The server's read state and anonymous mode, whether or not the list holds the chat. */
function adoptServerState(state: SyncState, store: AppState, serverConv: ConversationSummary): void {
  // The server's read state is what our reports dedupe against (a device
  // that reported the same count, or a higher one, makes ours moot)
  if (serverConv.read_count !== undefined) {
    state.reportedReadCounts.set(serverConv.id, serverConv.read_count);
  }
  // Another device toggled anonymous mode: adopt it (the next send here
  // must not turn it back on)
  if (serverConv.anonymous_mode !== undefined) {
    store.setAnonymousMode(serverConv.id, serverConv.anonymous_mode);
  }
}

function updateExisting(
  state: SyncState,
  store: AppState,
  serverConv: ConversationSummary,
  existing: Conversation,
  isCurrentConv: boolean,
  unread: UnreadState
): void {
  if (serverConv.pinned !== undefined && Boolean(existing.pinned) !== serverConv.pinned) {
    store.updateConversation(serverConv.id, { pinned: serverConv.pinned });
  }
  // The open chat's header shows the title too (the sidebar re-renders)
  if (isCurrentConv && existing.title !== serverConv.title) {
    state.callbacks.onCurrentConversationRenamed?.(serverConv.title);
  }
  store.updateConversation(serverConv.id, {
    title: serverConv.title,
    updated_at: serverConv.updated_at,
    messageCount: serverConv.message_count,
    last_message_preview: serverConv.last_message_preview,
    unreadCount: unread.unreadCount,
    hasExternalUpdate: unread.hasExternalUpdate,
  });
}

/**
 * A conversation the list doesn't hold, from an incremental sync. Returns
 * whether it was added.
 *
 * Pagination-discovered (older than the initial page load): not added -
 * it comes via pagination when the user scrolls - and no badge; only its
 * message count is tracked for then. Actually new (created/updated after
 * the page load, e.g. on another device): added with an unread badge. An
 * older conversation continued on another device has a count we already
 * know (full sync tracks unloaded ones): only the rest is new.
 */
function addDiscovered(state: SyncState, store: AppState, serverConv: ConversationSummary): boolean {
  if (isPaginationDiscovered(state.initialLoadTime, serverConv.updated_at)) {
    log.info('Pagination-discovered conversation (not unread, skipping add)', {
      conversationId: serverConv.id,
      updated_at: serverConv.updated_at,
    });
    state.localMessageCounts.set(serverConv.id, serverConv.message_count);
    return false;
  }

  const knownCount = state.localMessageCounts.get(serverConv.id);
  const unreadCount = Math.max(0, serverConv.message_count - (knownCount ?? 0));
  log.info('Actually new conversation discovered via sync (showing unread badge)', {
    conversationId: serverConv.id,
    updated_at: serverConv.updated_at,
    messageCount: serverConv.message_count,
    unreadCount,
  });
  // For actually new conversations, initialize to 0 so unread count is correct
  // (unreadCount = serverCount - localCount = serverCount - 0 = serverCount);
  // updateLocalBaseline preserves it until the user views the conversation
  if (knownCount === undefined) state.localMessageCounts.set(serverConv.id, 0);

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
  return true;
}

/**
 * Update local message count tracking:
 * - On full sync: always update (establishing baseline), EXCEPT for actually new conversations
 *   that were just initialized to 0 (we want to preserve 0 until user views it)
 * - On incremental sync for current conv: don't update (user might have sent messages)
 * - On incremental sync for non-current conv with unread: don't update (preserve unread state)
 * - On incremental sync for non-current conv without unread: update (no state to preserve)
 */
function updateLocalBaseline(
  state: SyncState,
  serverConv: ConversationSummary,
  existed: boolean,
  isFullSync: boolean,
  isCurrentConv: boolean,
  unreadCount: number
): void {
  const currentLocalCount = state.localMessageCounts.get(serverConv.id) ?? 0;
  const isActuallyNewConversation = !existed && currentLocalCount === 0 && serverConv.message_count > 0;
  const shouldUpdateLocalCount =
    (isFullSync && !isActuallyNewConversation) || (!isCurrentConv && unreadCount === 0);
  if (shouldUpdateLocalCount) {
    state.localMessageCounts.set(serverConv.id, serverConv.message_count);
  }
}

/** The list entry for a conversation that joins the list from another device. */
export function listEntryFromSummary(conv: ConversationSummary, unreadCount: number): Conversation {
  return {
    id: conv.id,
    title: conv.title,
    model: conv.model,
    created_at: conv.created_at ?? conv.updated_at,
    updated_at: conv.updated_at,
    messageCount: conv.message_count,
    last_message_preview: conv.last_message_preview,
    pinned: conv.pinned,
    unreadCount,
    hasExternalUpdate: false,
  };
}

/**
 * A deferred snapshot's non-count state, applied when this device's own
 * turn ends (see SyncManager.setConversationStreaming): a rename (never
 * back to the untitled default), a pin, anonymous mode, and the open chat
 * told it may hold the other device's messages.
 */
export function applyDeferredState(state: SyncState, summary: ConversationSummary): void {
  const store = useStore.getState();
  const local = store.conversations.find((c) => c.id === summary.id);
  if (!local) return;
  const updates: Partial<typeof local> = {};
  if (summary.title !== DEFAULT_CONVERSATION_TITLE && summary.title !== local.title) {
    updates.title = summary.title;
    if (store.currentConversation?.id === summary.id) {
      state.callbacks.onCurrentConversationRenamed?.(summary.title);
    }
  }
  if (summary.pinned !== undefined && Boolean(local.pinned) !== summary.pinned) {
    updates.pinned = summary.pinned;
  }
  if (Object.keys(updates).length > 0) {
    store.updateConversation(summary.id, updates);
    state.callbacks.onConversationsUpdated();
  }
  if (summary.anonymous_mode !== undefined) store.setAnonymousMode(summary.id, summary.anonymous_mode);
  // The open chat may have the other device's messages in it too
  if (store.currentConversation?.id === summary.id) {
    state.callbacks.onCurrentConversationExternalUpdate(summary.message_count);
  }
}
