/**
 * Conversation trash: restore (one or in bulk), delete forever, empty trash, and the trash view.
 *
 * Deleting a conversation (conversation-actions.ts) moves it here; the server
 * purges it for good after its retention window.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { conversations } from '../api/conversations';
import { ApiError } from '../api/http';
import { toast } from '../components/Toast';
import { showConfirm } from '../components/Modal';
import { renderConversationsList, loadArchivedConversations } from '../components/Sidebar';
import { getSyncManager } from '../sync/SyncManager';
import { cleanupTrashInfiniteScroll } from '../components/TrashView';
import { setTrashHash, setConversationHash, clearConversationHash } from '../router/deeplink';
import type { Conversation } from '../types/api';
import { isTempConversation } from './conversation';
import { CONVERSATIONS_BULK_MAX_IDS } from '../config';

const log = createLogger('conversation');

/**
 * Restore a conversation from the trash, back to the main list or the archive.
 *
 * @param conv - The conversation as it was before deletion (Undo toast); when
 *   omitted it is taken from the loaded trash list.
 */
export async function restoreConversation(convId: string, conv?: Conversation): Promise<void> {
  const store = useStore.getState();
  const source = conv ?? store.trashedConversations.find((c) => c.id === convId);

  try {
    getSyncManager()?.noteLocalChange(convId);
    await conversations.restore(convId);
    // Again once it's committed: a poll started during the request may
    // already see (or not yet see) the write - skip it either way
    getSyncManager()?.noteLocalChange(convId);

    store.removeTrashedConversation(convId);
    if (source) {
      const restored = { ...source, deleted_at: null, purge_at: null };
      if (restored.archived) {
        store.addArchivedConversation(restored);
      } else {
        store.addConversation(restored);
      }
      renderConversationsList();
    } else {
      // No local copy to re-insert: pull it back from the server (the
      // restore is in the sync change log, so incremental sync returns it)
      void loadArchivedConversations();
      void getSyncManager()?.incrementalSync();
    }
    toast.success('Conversation restored.');
  } catch (error) {
    log.error('Failed to restore conversation', { error, conversationId: convId });
    toast.error('Failed to restore conversation.');
  }
}

/**
 * Restore many conversations (Undo of a bulk delete), in chunks of the
 * server's bulk cap. Rows not in the snapshot (unloaded pages of a
 * select-all delete) come back through sync (the restore is in the change
 * log), at their original place: restore puts back the pre-trash updated_at.
 */
export async function restoreConversations(ids: string[], snapshot: Conversation[]): Promise<void> {
  const store = useStore.getState();
  const sync = getSyncManager();
  const byId = new Map(snapshot.map((c) => [c.id, c]));
  const restored: string[] = [];

  try {
    for (let i = 0; i < ids.length; i += CONVERSATIONS_BULK_MAX_IDS) {
      const chunk = ids.slice(i, i + CONVERSATIONS_BULK_MAX_IDS);
      chunk.forEach((id) => sync?.noteLocalChange(id));
      restored.push(...(await conversations.bulkRestore(chunk)));
    }
  } catch (error) {
    log.error('Failed to bulk restore conversations', { error, count: ids.length });
    toast.error('Failed to restore chats.');
    return;
  }

  restored.forEach((id) => {
    sync?.noteLocalChange(id);
    store.removeTrashedConversation(id);
    const source = byId.get(id);
    if (source) store.addConversation({ ...source, deleted_at: null, purge_at: null });
  });
  if (restored.some((id) => !byId.has(id))) void sync?.incrementalSync();
  renderConversationsList();
  toast.success(restored.length === 1 ? 'Conversation restored.' : `Restored ${restored.length} chats.`);
}

/**
 * Permanently delete one trashed conversation (after confirmation).
 */
export async function deleteConversationForever(convId: string): Promise<void> {
  const confirmed = await showConfirm({
    title: 'Delete forever',
    message: 'Permanently delete this conversation? This cannot be undone.',
    confirmLabel: 'Delete forever',
    cancelLabel: 'Cancel',
    danger: true,
  });
  if (!confirmed) return;

  try {
    getSyncManager()?.noteLocalChange(convId);
    await conversations.deletePermanently(convId);
    // Again once it's committed: a poll started during the request may
    // already see (or not yet see) the write - skip it either way
    getSyncManager()?.noteLocalChange(convId);
  } catch (error) {
    // 404: already purged (or deleted on another device) - drop the stale row
    if (!(error instanceof ApiError && error.status === 404)) {
      log.error('Failed to delete conversation permanently', { error, conversationId: convId });
      toast.error('Failed to delete conversation.');
      return;
    }
  }
  useStore.getState().removeTrashedConversation(convId);
  renderConversationsList();
}

/**
 * Permanently delete everything in the trash (after confirmation).
 */
export async function emptyTrash(): Promise<void> {
  // A big trash takes a while: repeated taps started a purge each
  if (useStore.getState().isEmptyingTrash) return;
  const confirmed = await showConfirm({
    title: 'Empty trash',
    message: 'Permanently delete all conversations in the trash? This cannot be undone.',
    confirmLabel: 'Empty trash',
    cancelLabel: 'Cancel',
    danger: true,
  });
  if (!confirmed || useStore.getState().isEmptyingTrash) return;

  useStore.getState().setEmptyingTrash(true);
  renderConversationsList();
  try {
    await conversations.emptyTrash();
    useStore.getState().clearTrash();
  } catch (error) {
    log.error('Failed to empty trash', { error });
    toast.error('Failed to empty trash.');
  } finally {
    useStore.getState().setEmptyingTrash(false);
    renderConversationsList();
  }
}

/**
 * Load trashed conversations from the API (also feeds the user-menu badge).
 */
export async function loadTrashedConversations(): Promise<void> {
  try {
    const result = await conversations.listTrash();
    useStore.getState().setTrashedConversations(result.conversations, result.pagination);
    renderConversationsList();
  } catch (error) {
    log.error('Failed to load trashed conversations', { error });
  }
}

/**
 * Navigate to the trash view (full-view, like the archive).
 * Always reloads: rows trashed on this device lack the server's purge_at.
 */
export function navigateToTrash(): void {
  const store = useStore.getState();
  store.setIsArchiveView(false);
  store.setIsTrashView(true);
  setTrashHash();
  renderConversationsList();
  void loadTrashedConversations();
}

/**
 * Leave the trash view and return to the conversations list.
 */
export function leaveTrashView(): void {
  const store = useStore.getState();
  store.setIsTrashView(false);
  cleanupTrashInfiniteScroll();
  renderConversationsList();
  const currentId = store.currentConversation?.id;
  if (currentId && !isTempConversation(currentId)) {
    setConversationHash(currentId, { replace: true });
  } else {
    clearConversationHash();
  }
}
