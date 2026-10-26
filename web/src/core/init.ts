/**
 * App initialization module.
 * Handles app shell rendering, login overlay, and initial data loading.
 */

import { renderChatHeader } from '../components/ChatHeader';
import { updateConversationCost } from './toolbar';
import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { models, config } from '../api/app';
import { conversations } from '../api/conversations';
import { todoist, calendar } from '../api/integrations';
import { initToast, toast } from '../components/Toast';
import { initModal } from '../components/Modal';
import { initGoogleSignIn, renderGoogleButton, checkAuth } from '../auth/google';
import {
  renderConversationsList,
  renderUserInfo,
  cleanupInfiniteScroll,
  loadArchivedConversations,
  initSidebarTimeRefresh,
} from '../components/Sidebar';
import { refreshSpendWarning } from '../components/SpendBanner';
import { initSearchInput } from '../components/SearchInput';
import { subscribeToSearchChanges } from '../components/SearchResults';
import {
  renderMessages,
  updateChatTitle,
  initOrientationChangeHandler,
} from '../components/messages';
import { initMessageInput, updateSendButtonState } from '../components/MessageInput';
import { APP_NAME } from '../config';
import { initKbDebugToggle, initKeyboardViewportPinning } from './keyboard-viewport';
import { initComposerHeight } from './composer-height';
import { initQuickActions } from './quick-actions';
import { initAttention } from './attention';
import { initConnectivity } from './connectivity';
import { registerServiceWorker, resyncPushSubscription } from './push';
import { initModelSelector, renderModelDropdown } from '../components/ModelSelector';
import { initFileUpload } from '../components/FileUpload';
import { initLightbox } from '../components/Lightbox';
import { initSourcesPopup } from '../components/SourcesPopup';
import { initClaimCard } from '../components/ClaimCard';
import { initResearchOffers } from '../components/messages/research-offer';
import { initResearchProgress } from '../components/messages/research-progress';
import { initActionRows } from '../components/messages/action-row';
import { initClaimsSheet } from '../components/ClaimsSheet';
import { initImageGenPopup } from '../components/ImageGenPopup';
import { initMessageCostPopup } from '../components/MessageCostPopup';
import { costHistoryPopup } from '../components/CostHistoryPopup';
import { initCompactionIndicator } from '../components/CompactionIndicator';
import { initVoiceInput } from '../components/VoiceInput';
import { initScrollToBottom, setBeforeScrollToBottomCallback } from '../components/ScrollToBottom';
import { initTurnAnchorResizeHold } from '../components/messages/turn-anchor';
import { initHeaderAutoHide } from './header-autohide';
import { initVersionBanner } from '../components/VersionBanner';
import { initErrorReporting } from './error-reporting';
import { getElementById, clearElement } from '../utils/dom';
import { initializeTheme } from '../utils/theme';
import { initPopupEscapeListener } from '../utils/popupEscapeHandler';
import {
  initDeepLinking,
  cleanupDeepLinking,
  clearConversationHash,
  pushEmptyHash,
  isValidConversationId,
  parseHash,
  getSportsProgramFromHash,
  getLanguageProgramFromHash,
} from '../router/deeplink';
import type { InitialRoute } from '../router/deeplink';
import { initSyncManager, stopSyncManager, getSyncManager } from '../sync/SyncManager';
import {
  cleanupOlderMessagesScrollListener,
  cleanupNewerMessagesScrollListener,
  loadAllRemainingNewerMessages,
} from '../components/messages';

import { sendMessage } from './messaging';
import { handleStopStreaming, abortAllStreamingRequests } from './active-requests';
import { initOutboxHandlers } from './rerun';
import { handleSearchResultClick } from './search';
import { setupEventListeners } from './events';
import { initSidebarSelection } from '../components/SidebarSelection';
import { setupTouchGestures } from './gestures';
import { initTTSVoices, speakMessageInternal as speakMessage } from './tts';
import { initToolbarButtons } from './toolbar';
import { isTempConversation } from './conversation';
import { loadDeepLinkedConversation, handleDeepLinkNavigation } from './conversation-deeplink';
import { deleteMessage } from './conversation-actions';
import { navigateToArchive } from './archive';
import { navigateToTrash, loadTrashedConversations } from './trash';
import { navigateToPlanner, leavePlannerView } from './planner';
import { navigateToSports, navigateToSportsProgram } from './sports';
import { navigateToLanguage, navigateToLanguageProgram } from './language';
import { navigateToAgents, initAgents } from './agents';
import { navigateToStorage } from './kv-store';
import { mergeExternalChanges } from './remote-merge';
import { installAvatarFallback } from '../utils/avatar';
import { mountAppShell } from './startup/app-shell';

const log = createLogger('init');

/**
 * Show the login overlay.
 */
export function showLoginOverlay(): void {
  getElementById('login-overlay')?.classList.remove('hidden');
}

/**
 * Hide the login overlay.
 */
export function hideLoginOverlay(): void {
  getElementById('login-overlay')?.classList.add('hidden');
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
    // Load data in parallel (including integration status for planner visibility)
    const [convResult, modelsData, uploadConfig, todoistStatus, calendarStatus] = await Promise.all([
      conversations.list(),
      models.list(),
      config.getUploadConfig(),
      todoist.getStatus().catch(() => ({ connected: false })),
      calendar.getStatus().catch(() => ({ connected: false })),
    ]);

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
    renderConversationsList();
    renderUserInfo();
    void refreshSpendWarning();
    renderModelDropdown();

    // Keep relative-time labels and date-group headers fresh even when no
    // sync poll returns changed data
    initSidebarTimeRefresh();

    // Load archive count in background (non-blocking) to show archive section
    loadArchivedConversations().catch(() => {
      // Ignore errors - archive section is optional
    });
    // Trash count for the user-menu badge (skipped when the trash view
    // itself is the initial route - navigateToTrash loads it)
    if (!initialRoute?.isTrash) {
      void loadTrashedConversations();
    }

    // Handle initial route from URL hash BEFORE starting sync manager
    // This prevents false "new messages available" banners for the deep-linked conversation
    if (initialRoute?.isPlanner) {
      await navigateToPlanner();
    } else if (initialRoute?.isAgents) {
      await navigateToAgents();
    } else if (initialRoute?.isStorage) {
      await navigateToStorage();
    } else if (initialRoute?.isSports) {
      const sportsProgramId = getSportsProgramFromHash();
      if (sportsProgramId) {
        await navigateToSportsProgram(sportsProgramId);
      } else {
        await navigateToSports();
      }
    } else if (initialRoute?.isLanguage) {
      const languageProgramId = getLanguageProgramFromHash();
      if (languageProgramId) {
        await navigateToLanguageProgram(languageProgramId);
      } else {
        await navigateToLanguage();
      }
    } else if (initialRoute?.isArchive) {
      navigateToArchive();
    } else if (initialRoute?.isTrash) {
      navigateToTrash();
    } else if (initialRoute?.conversationId && isValidConversationId(initialRoute.conversationId)) {
      await loadDeepLinkedConversation(initialRoute.conversationId);
    }

    // Initialize sync manager after data is loaded AND initial conversation is handled
    initSyncManager({
      onConversationsUpdated: () => {
        renderConversationsList();
      },
      onCurrentConversationDeleted: () => {
        store.setCurrentConversation(null);
        renderMessages([]);
        updateChatTitle(APP_NAME);
        // The deleted chat's header controls and cost chip go too (as for a
        // delete on this device - removeConversationFromUI)
        renderChatHeader(null);
        void updateConversationCost(null);
        // Clear the hash since conversation no longer exists
        clearConversationHash();
      },
      onCurrentConversationExternalUpdate: () => {
        // Merge the other device's changes in place (no reload banner).
        // Read LIVE state in these callbacks: `store` is a snapshot from
        // startup (Zustand replaces the state object on every update), and
        // reading isPlannerView / currentConversation from it meant the
        // planner and agent handlers below never fired.
        const convId = useStore.getState().currentConversation?.id;
        if (convId) void mergeExternalChanges(convId);
      },
      onCurrentConversationRenamed: (title: string) => {
        updateChatTitle(title);
      },
      onArchiveOrTrashChanged: ({ archive, trash }) => {
        // Rows and counts come from the server (a trash row needs its purge date)
        if (archive) void loadArchivedConversations();
        if (trash) void loadTrashedConversations();
      },
      onPlannerDeleted: () => {
        // Planner was deleted in another tab
        if (useStore.getState().isPlannerView) {
          toast.info('Planning session was deleted.');
          leavePlannerView();
          pushEmptyHash();
        }
      },
      onPlannerReset: () => {
        // Planner was reset in another tab
        if (useStore.getState().isPlannerView) {
          toast.info('Planning session was reset. Reloading...');
          void navigateToPlanner();
        }
      },
      onPlannerExternalUpdate: () => {
        // New messages added to planner in another tab/device: merge in place
        const live = useStore.getState();
        if (live.isPlannerView && live.currentConversation) {
          void mergeExternalChanges(live.currentConversation.id);
        }
      },
      onAgentConversationExternalUpdate: () => {
        // New messages added to agent conversation in another tab/device:
        // merge in place
        const currentConv = useStore.getState().currentConversation;
        if (currentConv?.is_agent) {
          void mergeExternalChanges(currentConv.id);
        }
      },
    });
    // Unhandled rejection here would silently disable sync for the session
    getSyncManager()
      ?.start()
      .catch((error) => {
        log.error('SyncManager failed to start', { error });
      });
  } catch (error) {
    log.error('Failed to load initial data', { error });
    toast.error('Failed to load data. Please refresh the page.', {
      action: { label: 'Refresh', onClick: () => window.location.reload() },
    });
  } finally {
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
}

/**
 * Initialize the application.
 */
export async function init(): Promise<void> {
  log.info('Initializing application');

  // First, so errors from the rest of startup reach the server too
  initErrorReporting();

  // Initialize theme early to prevent flash of wrong theme
  const { scheme, effectiveTheme } = initializeTheme();
  log.debug('Theme initialized', { scheme, effectiveTheme });

  const app = getElementById<HTMLDivElement>('app');
  if (!app) return;

  // Before any avatar renders: a dead Google photo URL falls back to initials
  installAvatarFallback();

  // Every init* below looks its elements up in the shell, so it goes first
  mountAppShell(app);

  // Initialize components
  initToast();
  initModal();
  initPopupEscapeListener(); // Single Escape key listener for all popups
  initMessageInput(() => {
    void sendMessage().catch((error: unknown) => log.error('Failed to send message', { error }));
  }, handleStopStreaming);
  initOutboxHandlers();
  initModelSelector();
  initFileUpload();
  initVoiceInput();
  initLightbox();
  initSourcesPopup();
  initClaimCard();
  initClaimsSheet();
  initResearchOffers();
  initResearchProgress();
  initActionRows();
  initImageGenPopup();
  initMessageCostPopup();
  costHistoryPopup.init();
  initCompactionIndicator();
  initAgents();
  initScrollToBottom();
  const messagesList = document.getElementById('messages');
  if (messagesList) initTurnAnchorResizeHold(messagesList);
  initHeaderAutoHide();
  // Set up callback to load remaining newer messages before scrolling to bottom
  // This ensures clicking scroll-to-bottom in a partial view (after search navigation)
  // loads all missing messages first, so the user sees the actual latest messages
  setBeforeScrollToBottomCallback(async () => {
    const store = useStore.getState();
    const { currentConversation } = store;
    if (!currentConversation) return;

    const pagination = store.getMessagesPagination(currentConversation.id);
    if (pagination?.hasNewer) {
      log.debug('Loading remaining newer messages before scroll-to-bottom', {
        conversationId: currentConversation.id,
      });
      await loadAllRemainingNewerMessages(currentConversation.id);
      cleanupNewerMessagesScrollListener();
    }
  });
  initOrientationChangeHandler();
  initKeyboardViewportPinning();
  initComposerHeight();
  initQuickActions();
  initKbDebugToggle();
  initAttention();
  initConnectivity();
  initVersionBanner();
  // Keep an existing push subscription working after reloads; actual
  // permission requests only happen from the Settings toggle
  void registerServiceWorker();
  initSearchInput();
  subscribeToSearchChanges((convId, messageId, resultIndex) => {
    void handleSearchResultClick(convId, messageId, resultIndex).catch((error: unknown) =>
      log.error('Failed to open search result', { error }),
    );
  });
  initTTSVoices();
  setupEventListeners();
  initSidebarSelection();
  setupTouchGestures();

  // Initialize toolbar buttons
  initToolbarButtons();

  // Initialize deep linking and capture initial route from URL
  const initialRoute = initDeepLinking(handleDeepLinkNavigation);

  // Check authentication
  const isAuthenticated = await checkAuth();

  if (isAuthenticated) {
    hideLoginOverlay();
    // Check for integration OAuth callbacks
    // OAuth callbacks only matter mid-flow (state keys set when the flow
    // started); gate the settings OAuth import on them so boot stays lean.
    // Key literals must match TODOIST_STATE_KEY / CALENDAR_STATE_KEY in
    // components/settings/{todoist,calendar}.ts.
    if (
      sessionStorage.getItem('todoist-oauth-state') ||
      sessionStorage.getItem('calendar-oauth-state')
    ) {
      const oauth = await import('../components/settings/oauth');
      await oauth.checkTodoistOAuthCallback();
      await oauth.checkCalendarOAuthCallback();
    }
    await loadInitialData(initialRoute);
  } else {
    showLoginOverlay();
    // Clear any conversation hash since user isn't authenticated
    clearConversationHash();
    await initGoogleSignIn();
    const loginBtn = getElementById<HTMLDivElement>('google-login-btn');
    if (loginBtn) {
      renderGoogleButton(loginBtn);
    }
  }

  // Listen for auth events
  const handleLogin = async (): Promise<void> => {
    hideLoginOverlay();
    try {
      // Check URL hash again in case user logged out then back in on a deep link
      const route = parseHash();
      const initialRoute: InitialRoute = {
        conversationId: route.type === 'conversation' ? route.conversationId ?? null : null,
        isPlanner: route.type === 'planner',
        isAgents: route.type === 'agents',
        isStorage: route.type === 'storage',
        isSports: route.type === 'sports',
        isLanguage: route.type === 'language',
        isArchive: route.type === 'archive',
        isTrash: route.type === 'trash',
      };
      await loadInitialData(initialRoute);
    } catch (error) {
      log.error('Failed to load data after login', { error });
      toast.error('Failed to load data. Please refresh the page.', {
        action: { label: 'Refresh', onClick: () => window.location.reload() },
      });
    }
  };
  window.addEventListener('auth:login', () => {
    void handleLogin();
  });

  const handleLogout = async (): Promise<void> => {
    // Kill in-flight readers and persisted resume entries before anything
    // else - they would keep writing into the logged-out UI, and another
    // account on this browser must not resume the previous user's turns
    abortAllStreamingRequests();

    // Stop sync manager and scroll listeners on logout
    stopSyncManager();
    cleanupInfiniteScroll();
    cleanupOlderMessagesScrollListener();
    cleanupNewerMessagesScrollListener();

    // Clear URL hash and clean up deep linking
    clearConversationHash();
    cleanupDeepLinking();

    showLoginOverlay();
    // All user data in the store (messages, pagination, drafts, agents,
    // storage, programs, ...) is wiped by the store.logout() the event
    // dispatcher already ran - only re-render the now-empty UI here
    renderConversationsList();
    renderMessages([]);

    // Re-render Google Sign-In button. A session that started signed in
    // never initialized sign-in (Google's script loads on demand), so
    // initialize first - the button used to render empty here
    await initGoogleSignIn();
    const loginBtn = getElementById<HTMLDivElement>('google-login-btn');
    if (loginBtn) {
      clearElement(loginBtn);
      renderGoogleButton(loginBtn);
    }

    // Re-initialize deep linking for next login
    initDeepLinking(handleDeepLinkNavigation);
  };
  window.addEventListener('auth:logout', () => {
    void handleLogout().catch((error: unknown) => log.error('Failed to reset the UI after logout', { error }));
  });

  // Listen for message delete events
  window.addEventListener('message:delete', (event: Event) => {
    const customEvent = event as CustomEvent<{ messageId: string }>;
    const { messageId } = customEvent.detail;
    log.debug('Message delete event received', { messageId });
    void deleteMessage(messageId);
  });

  // Listen for message speak events (TTS)
  window.addEventListener('message:speak', (event: Event) => {
    const customEvent = event as CustomEvent<{ messageId: string; language?: string }>;
    const { messageId, language } = customEvent.detail;
    log.debug('Message speak event received', { messageId, language });
    speakMessage(messageId, language);
  });
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
