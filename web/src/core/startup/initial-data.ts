/**
 * Loading the signed-in user's data, opening the initial route and then
 * starting sync.
 */
import { models, config } from '../../api/app';
import { conversations } from '../../api/conversations';
import { todoist, calendar } from '../../api/integrations';
import { updateSendButtonState } from '../../components/MessageInput';
import { renderModelDropdown } from '../../components/ModelSelector';
import {
  renderConversationsList,
  renderUserInfo,
  loadArchivedConversations,
  initSidebarTimeRefresh,
} from '../../components/Sidebar';
import { refreshSpendWarning } from '../../components/SpendBanner';
import { toast } from '../../components/Toast';
import type { InitialRoute } from '../../router/deeplink';
import { useStore } from '../../state/store';
import type { AppState } from '../../state/store';
import { createLogger } from '../../utils/logger';
import { isTempConversation } from '../../utils/conversation-id';
import { resyncPushSubscription } from '../push';
import { loadTrashedConversations } from '../trash';
import { openInitialRoute } from './initial-route';
import { markAppReady } from './app-ready';
import { startSync } from './sync';

const log = createLogger('init');

/** Fetch everything the first render needs, in parallel. */
function fetchInitialData() {
  // Integration status decides the planner's visibility
  return Promise.all([
    conversations.list(),
    models.list(),
    config.getUploadConfig(),
    todoist.getStatus().catch(() => ({ connected: false })),
    calendar.getStatus().catch(() => ({ connected: false })),
  ]);
}

/**
 * Put the fetched data into the store. `store` is the state from before the
 * fetch (its actions are stable; its `user` is the one the fetch started for).
 */
function storeInitialData(
  store: AppState,
  [convResult, modelsData, uploadConfig, todoistStatus, calendarStatus]: Awaited<
    ReturnType<typeof fetchInitialData>
  >,
): void {
  store.setConversations(convResult.conversations, convResult.pagination);
  // "New Chat" clicked while this fetch was in flight created a local-only
  // conversation the server list can't know about - don't drop it from the
  // sidebar (it persists on the first message)
  const current = useStore.getState().currentConversation;
  if (current && isTempConversation(current.id)) {
    store.addConversation(current);
  }
  store.setModels(modelsData.models, modelsData.default);
  store.setUploadConfig(uploadConfig);

  // Update user with integration status for planner visibility
  const currentUser = store.user;
  if (currentUser) {
    store.setUser({
      ...currentUser,
      todoist_connected: todoistStatus.connected,
      calendar_connected: calendarStatus.connected,
    });
  }

  log.info('Initial data loaded', {
    conversationCount: convResult.conversations.length,
    modelCount: modelsData.models.length,
    todoistConnected: todoistStatus.connected,
    calendarConnected: calendarStatus.connected,
  });
}

/** Render the sidebar and composer from the loaded data; fetch the counts. */
function renderInitialData(): void {
  renderConversationsList();
  renderUserInfo();
  void refreshSpendWarning();
  renderModelDropdown();

  // Keep relative-time labels and date-group headers fresh even when no
  // sync poll returns changed data
  initSidebarTimeRefresh();
}

/**
 * Load the archive and trash lists (their counts badge the user menu) once
 * the first sync has its change-log cursor: a chat archived or trashed on
 * another device after that shows up in the change log and reloads them,
 * while one changed between an earlier load and the cursor was in neither
 * and left the badge stale (Oct 2026).
 */
async function loadArchiveAndTrash(initialRoute: InitialRoute | null | undefined): Promise<void> {
  await Promise.all([
    loadArchivedConversations().catch(() => {
      // Ignore errors - archive section is optional
    }),
    // Skipped when the trash view itself is the initial route - navigateToTrash loads it
    initialRoute?.isTrash ? undefined : loadTrashedConversations(),
  ]);
}

/** Once loading ends, whether it succeeded or not. */
function finishLoading(store: AppState): void {
  store.setLoading(false);
  // Text typed (or a file attached) during boot evaluated the send button
  // while isLoading was true and nothing re-runs the check afterwards -
  // the button stayed disabled until the next keystroke
  updateSendButtonState();
  // The sidebar may have last rendered during loading (skeletons). With
  // zero conversations nothing else re-renders it afterwards, leaving the
  // skeletons up forever on slow boots (caught by CI's container runners
  // on the #/agents route). Idempotent: the renderer dedups identical HTML.
  renderConversationsList();
}

/**
 * Load initial data after authentication.
 * If initialRoute is provided (from URL hash), handle it BEFORE starting sync.
 */
export async function loadInitialData(initialRoute?: InitialRoute | null): Promise<void> {
  log.debug('Loading initial data', { initialRoute });
  const store = useStore.getState();
  store.setLoading(true);

  // Heal silently-rotated push endpoints (idempotent upsert; needs auth,
  // which this post-login path guarantees)
  void resyncPushSubscription();

  try {
    storeInitialData(store, await fetchInitialData());
    renderInitialData();

    // After the store holds the conversation list: the views read it
    await openInitialRoute(initialRoute);

    // Only after data is loaded AND the initial route is handled: sync
    // starting earlier showed false "new messages available" banners for
    // the deep-linked conversation
    startSync(() => void loadArchiveAndTrash(initialRoute).finally(markAppReady));
  } catch (error) {
    log.error('Failed to load initial data', { error });
    toast.error('Failed to load data. Please refresh the page.', {
      action: { label: 'Refresh', onClick: () => window.location.reload() },
    });
    markAppReady();
  } finally {
    finishLoading(store);
  }
}
