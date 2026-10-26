/**
 * Applying a change-log page (cursor sync): removals (deleted / trashed /
 * archived on another device) leave the list right away - the timestamp
 * sync only noticed them on a full sync, which a visible tab never ran -
 * then updates, pins and conversations that (re)appeared.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import type { ConversationSummary, SyncResponse } from '../types/api';
import { inLoadedWindow, isPaginationDiscovered } from './pagination-window';
import { applyChanges, listEntryFromSummary } from './summary-merge';
import type { SyncState } from './sync-state';

const log = createLogger('sync');

/** Why a conversation left this device's list from another device. */
type ExternalRemoval = 'deleted' | 'trashed' | 'archived';

/** Apply one change-log page. */
export function applyChangeLog(state: SyncState, result: SyncResponse): void {
  // Before the removals below change the main list
  const lists = archiveOrTrashTouched(state, result);
  if (lists.archive || lists.trash) state.callbacks.onArchiveOrTrashChanged?.(lists);

  let changed = false;
  for (const id of result.removed_ids ?? []) {
    if (state.changedLocallySinceRequest(id)) continue;
    changed = removeExternally(state, id, 'deleted') || changed;
  }

  const { existing, listChanged } = applyListMoves(state, result.conversations);
  changed = listChanged || changed;

  state.notifiedCurrentUpdate = false;
  if (existing.length > 0) {
    applyChanges(state, existing, false);
    changed = true;
  }
  if (changed) state.callbacks.onConversationsUpdated();

  notifyOpenConversation(state, result.conversations);
}

/**
 * Remove the conversations archived or trashed elsewhere and add the ones
 * that (re)appeared; the rest, already in the list, are returned for the
 * summary merge.
 */
function applyListMoves(
  state: SyncState,
  conversations: ConversationSummary[]
): { existing: ConversationSummary[]; listChanged: boolean } {
  const store = useStore.getState();
  const openConv = store.currentConversation;
  const existing: ConversationSummary[] = [];
  let listChanged = false;
  for (const conv of conversations) {
    if (state.changedLocallySinceRequest(conv.id)) continue;
    // An archived chat that is OPEN here (archive view, search, deep link):
    // its changes - our own read echo included - are just changes to the
    // open chat, not "archived on another device"
    if (conv.archived && !conv.trashed && openConv?.id === conv.id && openConv.archived) {
      continue;
    }
    if (conv.trashed || conv.archived) {
      listChanged = removeExternally(state, conv.id, conv.trashed ? 'trashed' : 'archived') || listChanged;
    } else if (store.conversations.some((c) => c.id === conv.id)) {
      existing.push(conv);
    } else {
      listChanged = addFromChangeLog(state, conv) || listChanged;
    }
  }
  return { existing, listChanged };
}

/**
 * Any change to the open conversation - not only a higher count (a
 * delete, a regenerate or another device's finished stream keep it the
 * same), and also when it isn't in the loaded sidebar list (opened from
 * search or a deep link). The merge diffs against what is rendered, so
 * our own changes are a no-op.
 */
function notifyOpenConversation(state: SyncState, conversations: ConversationSummary[]): void {
  const open = useStore.getState().currentConversation;
  if (!open || state.notifiedCurrentUpdate || state.streamingConversations.has(open.id)) return;
  const changedOpen = conversations.find((c) => c.id === open.id && !c.trashed);
  if (changedOpen && (!changedOpen.archived || open.archived)) {
    state.callbacks.onCurrentConversationExternalUpdate(changedOpen.message_count);
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
function archiveOrTrashTouched(state: SyncState, result: SyncResponse): { archive: boolean; trash: boolean } {
  const { archivedConversations, trashedConversations } = useStore.getState();
  const archived = new Set(archivedConversations.map((c) => c.id));
  const trashed = new Set(trashedConversations.map((c) => c.id));
  const lists = { archive: false, trash: false };
  for (const id of result.removed_ids ?? []) {
    if (state.changedLocallySinceRequest(id)) continue;
    lists.archive ||= archived.has(id);
    lists.trash ||= trashed.has(id);
  }
  for (const conv of result.conversations) {
    if (state.changedLocallySinceRequest(conv.id)) continue;
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
function removeExternally(state: SyncState, id: string, reason: ExternalRemoval): boolean {
  const store = useStore.getState();
  const inList = store.conversations.some((c) => c.id === id);
  const current = store.currentConversation?.id === id ? store.currentConversation : null;
  // Gone here too: a recovery of its interrupted reply ends silently
  if (reason !== 'archived') state.cancelRecovery(id);
  // The known count stays (pruned on the next full sync): a restore or
  // unarchive then compares against it instead of counting it all unread
  state.deferredUpdates.delete(id);
  if (!inList && !current) return false;
  log.info('Conversation removed on another device', { conversationId: id, reason });

  if (inList) store.removeConversation(id);
  if (!current) return true;
  if (reason === 'archived') {
    store.setCurrentConversation({ ...current, archived: true });
    state.notify.info('This conversation was archived on another device.');
    return true;
  }
  state.notify.warning(
    reason === 'trashed'
      ? 'This conversation was moved to the trash on another device.'
      : 'This conversation was deleted on another device.'
  );
  state.callbacks.onCurrentConversationDeleted();
  return true;
}

/**
 * A live conversation the list doesn't hold: new on another device,
 * continued there, or restored/unarchived there. Added when it belongs in
 * the loaded part of the list (older ones arrive with pagination). Only a
 * conversation created after this page loaded counts as wholly unread; a
 * restored or unarchived one is old content.
 */
function addFromChangeLog(state: SyncState, conv: ConversationSummary): boolean {
  if (!conv.pinned && !inLoadedWindow(conv.updated_at)) {
    state.localMessageCounts.set(conv.id, conv.message_count);
    return false;
  }
  const known = state.localMessageCounts.get(conv.id);
  const isNew = conv.created_at
    ? !isPaginationDiscovered(state.initialLoadTime, conv.created_at)
    : known === undefined;
  const baseline = known ?? (isNew ? 0 : conv.message_count);
  state.localMessageCounts.set(conv.id, baseline);
  const unread =
    conv.read_count !== undefined
      ? Math.max(0, conv.message_count - conv.read_count)
      : Math.max(0, conv.message_count - baseline);
  log.info('Conversation appeared from another device', { conversationId: conv.id, isNew });

  useStore.getState().addConversation(listEntryFromSummary(conv, unread));
  return true;
}
