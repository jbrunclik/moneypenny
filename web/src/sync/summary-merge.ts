/**
 * Merging server conversation summaries into the loaded list: unread counts
 * and external updates against the local message-count baselines, the
 * server's read state, renames, pins and anonymous mode - and the deferred
 * summary of a conversation whose own turn just ended.
 */

import { useStore, type AppState } from '../state/store';
import { createLogger } from '../utils/logger';
import { DEFAULT_CONVERSATION_TITLE, type Conversation, type ConversationSummary } from '../types/api';
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
  if (!isCurrentConv) {
    unread.unreadCount = Math.max(0, serverConv.message_count - serverConv.read_count);
  }

  // Callers pass only conversations the list holds (the full sync and the
  // change log add the others themselves)
  if (!existing) return true;
  updateExisting(state, store, serverConv, existing, isCurrentConv, unread);
  updateLocalBaseline(state, serverConv, isFullSync, isCurrentConv, unread.unreadCount);
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
  state.reportedReadCounts.set(serverConv.id, serverConv.read_count);
  // Another device toggled anonymous mode: adopt it (the next send here
  // must not turn it back on)
  store.setAnonymousMode(serverConv.id, serverConv.anonymous_mode);
}

function updateExisting(
  state: SyncState,
  store: AppState,
  serverConv: ConversationSummary,
  existing: Conversation,
  isCurrentConv: boolean,
  unread: UnreadState
): void {
  if (Boolean(existing.pinned) !== serverConv.pinned) {
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
 * Update local message count tracking:
 * - On full sync: always update (establishing baseline)
 * - On incremental sync for current conv: don't update (user might have sent messages)
 * - On incremental sync for non-current conv with unread: don't update (preserve unread state)
 * - On incremental sync for non-current conv without unread: update (no state to preserve)
 */
function updateLocalBaseline(
  state: SyncState,
  serverConv: ConversationSummary,
  isFullSync: boolean,
  isCurrentConv: boolean,
  unreadCount: number
): void {
  const shouldUpdateLocalCount = isFullSync || (!isCurrentConv && unreadCount === 0);
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
    created_at: conv.created_at,
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
  if (Boolean(local.pinned) !== summary.pinned) {
    updates.pinned = summary.pinned;
  }
  if (Object.keys(updates).length > 0) {
    store.updateConversation(summary.id, updates);
    state.callbacks.onConversationsUpdated();
  }
  store.setAnonymousMode(summary.id, summary.anonymous_mode);
  // The open chat may have the other device's messages in it too
  if (store.currentConversation?.id === summary.id) {
    state.callbacks.onCurrentConversationExternalUpdate(summary.message_count);
  }
}
