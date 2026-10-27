/**
 * Starting multi-device sync once the initial data is in, and how the UI
 * reacts to what the sync manager reports.
 */
import { renderChatHeader } from '../../components/ChatHeader';
import { renderConversationsList, loadArchivedConversations } from '../../components/Sidebar';
import { renderMessages, updateChatTitle } from '../../components/messages';
import { toast } from '../../components/Toast';
import { APP_NAME } from '../../config';
import { clearConversationHash, pushEmptyHash } from '../../router/deeplink';
import { useStore } from '../../state/store';
import { initSyncManager, getSyncManager } from '../../sync/SyncManager';
import type { SyncManagerCallbacks } from '../../sync/sync-state';
import { createLogger } from '../../utils/logger';
import { navigateToPlanner, leavePlannerView } from '../planner';
import { mergeExternalChanges } from '../remote-merge';
import { attemptRecovery, cancelRecovery, hasPendingRecovery } from '../stream-recovery';
import { updateConversationCost } from '../toolbar';
import { loadTrashedConversations } from '../trash';

const log = createLogger('init');

// Every handler reads LIVE state (useStore.getState()) when it fires: a
// state object captured at startup is a stale snapshot (Zustand replaces it
// on every update), and reading isPlannerView / currentConversation from
// one meant the planner and agent handlers never fired.

function onCurrentConversationDeleted(): void {
  useStore.getState().setCurrentConversation(null);
  renderMessages([]);
  updateChatTitle(APP_NAME);
  // The deleted chat's header controls and cost chip go too (as for a
  // delete on this device - removeConversationFromUI)
  renderChatHeader(null);
  void updateConversationCost(null);
  // Clear the hash since conversation no longer exists
  clearConversationHash();
}

function onCurrentConversationExternalUpdate(): void {
  // Merge the other device's changes in place (no reload banner)
  const convId = useStore.getState().currentConversation?.id;
  if (convId) void mergeExternalChanges(convId);
}

function onPlannerDeleted(): void {
  // Planner was deleted in another tab
  if (useStore.getState().isPlannerView) {
    toast.info('Planning session was deleted.');
    leavePlannerView();
    pushEmptyHash();
  }
}

function onPlannerReset(): void {
  // Planner was reset in another tab
  if (useStore.getState().isPlannerView) {
    toast.info('Planning session was reset. Reloading...');
    void navigateToPlanner();
  }
}

function onPlannerExternalUpdate(): void {
  // New messages added to planner in another tab/device: merge in place
  const live = useStore.getState();
  if (live.isPlannerView && live.currentConversation) {
    void mergeExternalChanges(live.currentConversation.id);
  }
}

function onAgentConversationExternalUpdate(): void {
  // New messages added to agent conversation in another tab/device:
  // merge in place
  const currentConv = useStore.getState().currentConversation;
  if (currentConv?.is_agent) {
    void mergeExternalChanges(currentConv.id);
  }
}

const SYNC_CALLBACKS: SyncManagerCallbacks = {
  onConversationsUpdated: () => {
    renderConversationsList();
  },
  onCurrentConversationDeleted,
  onCurrentConversationExternalUpdate,
  onCurrentConversationRenamed: (title: string) => {
    updateChatTitle(title);
  },
  onArchiveOrTrashChanged: ({ archive, trash }) => {
    // Rows and counts come from the server (a trash row needs its purge date)
    if (archive) void loadArchivedConversations();
    if (trash) void loadTrashedConversations();
  },
  onPlannerDeleted,
  onPlannerReset,
  onPlannerExternalUpdate,
  onAgentConversationExternalUpdate,
};

/**
 * Create the sync manager and start polling. `onStarted` runs once the first
 * full sync is done (or failed), with the change-log cursor set.
 */
export function startSync(onStarted?: () => void): void {
  initSyncManager(
    SYNC_CALLBACKS,
    { hasPending: hasPendingRecovery, attempt: attemptRecovery, cancel: cancelRecovery },
    toast
  );
  // Unhandled rejection here would silently disable sync for the session
  getSyncManager()
    ?.start()
    .catch((error) => {
      log.error('SyncManager failed to start', { error });
    })
    .finally(() => onStarted?.());
}

// Test helper: Trigger a full sync (for E2E tests)
// Usage in browser console: await window.__testFullSync()
declare global {
  interface Window {
    __testFullSync: () => Promise<void>;
    __testIncrementalSync: () => Promise<void>;
  }
}
window.__testFullSync = async () => {
  const syncManager = getSyncManager();
  if (syncManager) {
    await syncManager.fullSync();
  }
};
// The regular poll tick (E2E: what a visible tab sees without a full sync)
window.__testIncrementalSync = async () => {
  await getSyncManager()?.incrementalSync();
};
