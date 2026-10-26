/**
 * Applying a full sync: deletions (in the list, missing on the server),
 * updates to the loaded conversations, and conversations that belong in the
 * loaded part of the list but aren't in it (new, continued or restored on
 * another device).
 *
 * Note: The sync endpoint only returns regular conversations - planner and autonomous
 * agent conversations are filtered out at the backend (is_planning=0, is_agent=0).
 * They have separate sync mechanisms (PlannerSync, AgentConversationSync).
 */

import { useStore, type AppState } from '../state/store';
import { createLogger } from '../utils/logger';
import type { ConversationSummary } from '../types/api';
import { inLoadedWindow, isPaginationDiscovered } from './pagination-window';
import { applyChanges, listEntryFromSummary } from './summary-merge';
import type { SyncState } from './sync-state';

const log = createLogger('sync');

/**
 * Apply full sync results - handles deletions, updates, AND new conversations.
 *
 * Pagination-discovered conversations (below the loaded part of the list)
 * are NOT added, preserving the pagination behavior.
 *
 * @param knownBefore the list's conversation ids when the request was made
 */
export function applyFullSync(
  state: SyncState,
  serverConversations: ConversationSummary[],
  knownBefore: Set<string>
): void {
  const store = useStore.getState();
  const deletedIds = findDeleted(store, serverConversations, knownBefore);
  for (const id of deletedIds) removeDeleted(state, store, id);

  const { existing, added } = partitionByList(state, store, serverConversations);
  applyChanges(state, existing, true);
  for (const serverConv of added) addFromFullSync(state, store, serverConv);

  if (deletedIds.length > 0 || existing.length > 0 || added.length > 0) {
    state.callbacks.onConversationsUpdated();
  }
}

/**
 * Detect deleted conversations (in local but not in server).
 *
 * Only conversations known BEFORE the request can be "missing" from its
 * answer: one created, restored or unarchived here while it was in flight
 * is absent from the server's older snapshot. Temp conversations (not yet
 * persisted) are skipped, and archived ones too: sync intentionally
 * excludes them, so a deep-linked archived conversation would otherwise be
 * "deleted" and kicked out of view seconds after loading.
 */
function findDeleted(
  store: AppState,
  serverConversations: ConversationSummary[],
  knownBefore: Set<string>
): string[] {
  const serverIds = new Set(serverConversations.map((c) => c.id));
  return store.conversations
    .filter((c) => !c.id.startsWith('temp-') && !c.archived && knownBefore.has(c.id) && !serverIds.has(c.id))
    .map((c) => c.id);
}

function removeDeleted(state: SyncState, store: AppState, id: string): void {
  log.info('Conversation deleted externally', { conversationId: id });
  state.cancelRecovery(id);

  if (store.currentConversation?.id === id) {
    state.notify.warning('This conversation was deleted.');
    state.callbacks.onCurrentConversationDeleted();
  }

  store.removeConversation(id);
  state.localMessageCounts.delete(id);
}

/**
 * Separate existing conversations (for update) from new ones (for add).
 *
 * A conversation the list lacks belongs in the loaded part of the list
 * (new, continued or restored elsewhere) or only further down (pagination
 * brings it). By the list, not initialLoadTime: a conversation created on
 * another device while this page booted predates that time and was lost.
 * A pinned one always belongs (the pinned group is never paged).
 */
function partitionByList(
  state: SyncState,
  store: AppState,
  serverConversations: ConversationSummary[]
): { existing: ConversationSummary[]; added: ConversationSummary[] } {
  const localIds = new Set(store.conversations.map((c) => c.id));
  const existing: ConversationSummary[] = [];
  const added: ConversationSummary[] = [];

  for (const serverConv of serverConversations) {
    if (localIds.has(serverConv.id)) {
      existing.push(serverConv);
    } else if (state.changedLocallySinceRequest(serverConv.id)) {
      // Trashed / archived here after this snapshot was read: not back
      continue;
    } else if (serverConv.pinned || inLoadedWindow(serverConv.updated_at)) {
      added.push(serverConv);
    } else {
      // Pagination-discovered: just track the message count for when it's loaded via pagination
      state.localMessageCounts.set(serverConv.id, serverConv.message_count);
      log.debug('Full sync: skipping pagination-discovered conversation', {
        conversationId: serverConv.id,
        updated_at: serverConv.updated_at,
      });
    }
  }
  return { existing, added };
}

/**
 * Add a conversation from another device. Unread: the server's read state;
 * without it, all of a conversation created after this page loaded, or
 * beyond a count we already knew - an older one (continued, restored)
 * isn't wholly new.
 */
function addFromFullSync(state: SyncState, store: AppState, serverConv: ConversationSummary): void {
  log.info('Full sync: adding new conversation from another device', {
    conversationId: serverConv.id,
    updated_at: serverConv.updated_at,
    messageCount: serverConv.message_count,
  });

  const knownCount = state.localMessageCounts.get(serverConv.id);
  const createdBeforeLoad = isPaginationDiscovered(
    state.initialLoadTime,
    serverConv.created_at ?? serverConv.updated_at
  );
  const baseline = knownCount ?? (createdBeforeLoad ? serverConv.message_count : 0);
  state.localMessageCounts.set(serverConv.id, baseline);
  const unreadCount =
    serverConv.read_count !== undefined
      ? Math.max(0, serverConv.message_count - serverConv.read_count)
      : Math.max(0, serverConv.message_count - baseline);

  store.addConversation(listEntryFromSummary(serverConv, unreadCount));
}
