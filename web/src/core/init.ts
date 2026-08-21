/**
 * App initialization module.
 * Handles app shell rendering, login overlay, and initial data loading.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { conversations, models, config, todoist, calendar } from '../api/client';
import { initToast, toast } from '../components/Toast';
import { initModal } from '../components/Modal';
import { initGoogleSignIn, renderGoogleButton, checkAuth } from '../auth/google';
import {
  renderConversationsList,
  renderUserInfo,
  cleanupInfiniteScroll,
  loadArchivedConversations,
} from '../components/Sidebar';
import { initSearchInput } from '../components/SearchInput';
import { subscribeToSearchChanges } from '../components/SearchResults';
import {
  renderMessages,
  updateChatTitle,
  initOrientationChangeHandler,
  showConversationLoader,
} from '../components/messages';
import { initMessageInput } from '../components/MessageInput';
import { renderWelcomeMessageHtml } from '../components/WelcomeMessage';
import { registerServiceWorker, resyncPushSubscription } from './push';
import { initModelSelector, renderModelDropdown } from '../components/ModelSelector';
import { initFileUpload } from '../components/FileUpload';
import { initLightbox } from '../components/Lightbox';
import { initSourcesPopup } from '../components/SourcesPopup';
import { initImageGenPopup } from '../components/ImageGenPopup';
import { initMessageCostPopup } from '../components/MessageCostPopup';
import { costHistoryPopup, getCostHistoryPopupHtml } from '../components/CostHistoryPopup';
import { initVoiceInput } from '../components/VoiceInput';
import { initScrollToBottom, setBeforeScrollToBottomCallback } from '../components/ScrollToBottom';
import { initVersionBanner } from '../components/VersionBanner';
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
import { ATTACH_ICON, CHEVRON_DOWN_ICON, SLIDERS_ICON, CLOSE_ICON, SEND_ICON, MICROPHONE_ICON, STREAM_ICON, SEARCH_ICON, SPARKLES_ICON, PLUS_ICON, INCOGNITO_ICON, MENU_ICON } from '../utils/icons';
import { initSyncManager, stopSyncManager, getSyncManager } from '../sync/SyncManager';
import {
  cleanupOlderMessagesScrollListener,
  cleanupNewerMessagesScrollListener,
  loadAllRemainingNewerMessages,
} from '../components/messages';

import { sendMessage, handleStopStreaming, abortAllStreamingRequests, initOutboxHandlers } from './messaging';
import { handleSearchResultClick } from './search';
import { setupEventListeners } from './events';
import { setupTouchGestures } from './gestures';
import { initTTSVoices, speakMessageInternal as speakMessage } from './tts';
import { initToolbarButtons } from './toolbar';
import { loadDeepLinkedConversation, handleDeepLinkNavigation, deleteMessage } from './conversation';
import { navigateToPlanner, leavePlannerView } from './planner';
import { navigateToSports, navigateToSportsProgram } from './sports';
import { navigateToLanguage, navigateToLanguageProgram } from './language';
import { navigateToAgents, initAgents } from './agents';
import { navigateToStorage } from './kv-store';
import { showNewMessagesAvailableBanner } from './sync-banner';

const log = createLogger('init');

/**
 * Render the app shell HTML template.
 */
export function renderAppShell(): string {
  return `
    <!-- Sidebar -->
    <aside id="sidebar" class="sidebar">
      <div class="sidebar-header">
        <h1>AI Chatbot</h1>
        <button id="new-chat-btn" class="btn btn-primary">${PLUS_ICON} New Chat</button>
      </div>
      <div id="search-container" class="search-container"></div>
      <div id="conversations-list" class="conversations-list"></div>
      <div class="sidebar-footer">
        <div id="user-info" class="user-info"></div>
      </div>
    </aside>

    <!-- Main chat area -->
    <main class="main">
      <header class="mobile-header">
        <button id="menu-btn" class="btn-icon">${MENU_ICON}</button>
        <span id="current-chat-title">AI Chatbot</span>
        <span id="conversation-cost-mobile" class="chat-header-cost"></span>
      </header>

      <header id="chat-header" class="chat-header hidden"></header>

      <div id="messages" class="messages">
        ${renderWelcomeMessageHtml()}
      </div>

      <div class="input-area">
        <div class="input-wrapper">
          <div id="file-preview" class="file-preview hidden"></div>
          <input type="file" id="file-input" multiple accept="image/*,video/mp4,video/quicktime,video/webm,application/pdf,text/plain,text/markdown,text/csv,application/json">
          <div id="input-container" class="input-container">
            <textarea id="message-input" placeholder="Type your message..." rows="1"></textarea>
            <div class="input-toolbar">
            <div class="toolbar-left">
              <div class="model-selector">
                <button id="model-selector-btn" class="model-selector-btn">
                  <span id="current-model-name">Loading...</span>
                  <span class="dropdown-arrow">${CHEVRON_DOWN_ICON}</span>
                </button>
                <div id="model-dropdown" class="model-dropdown hidden"></div>
              </div>
              <button id="toolbar-options-btn" class="btn-toolbar" aria-label="Message options" aria-expanded="false">
                ${SLIDERS_ICON}
              </button>
              <div class="toolbar-toggles">
                <button id="stream-btn" class="btn-toolbar active" title="Toggle streaming" aria-label="Toggle streaming" aria-pressed="true">
                  ${STREAM_ICON}<span class="toolbar-toggle-label">Streaming</span>
                </button>
                <button id="search-btn" class="btn-toolbar" aria-pressed="false" title="Force web search for next message" aria-label="Force web search for next message">
                  ${SEARCH_ICON}<span class="toolbar-toggle-label">Web search</span>
                </button>
                <button id="imagegen-btn" class="btn-toolbar" aria-pressed="false" title="Force image generation for next message" aria-label="Force image generation for next message">
                  ${SPARKLES_ICON}<span class="toolbar-toggle-label">Generate image</span>
                </button>
                <button id="anonymous-btn" class="btn-toolbar" aria-pressed="false" title="Anonymous mode - disable memory and integrations" aria-label="Anonymous mode">
                  ${INCOGNITO_ICON}<span class="toolbar-toggle-label">Incognito</span>
                </button>
              </div>
            </div>
            <div class="toolbar-right">
              <button id="voice-btn" class="btn-toolbar btn-voice" title="Voice input" aria-label="Voice input" aria-pressed="false">
                ${MICROPHONE_ICON}
              </button>
              <button id="attach-btn" class="btn-toolbar" title="Attach files" aria-label="Attach files">
                ${ATTACH_ICON}
              </button>
              <button id="send-btn" class="btn btn-send" aria-label="Send message" disabled>
                ${SEND_ICON}
              </button>
            </div>
            </div>
          </div>
        </div>
      </div>
    </main>

    <!-- Lightbox -->
    <div id="lightbox" class="lightbox hidden">
      <div class="lightbox-loader">
        <div class="loading-dots">
          <span></span>
          <span></span>
          <span></span>
        </div>
        <p>Loading image...</p>
      </div>
      <div class="lightbox-container">
        <button class="lightbox-close" aria-label="Close">
          ${CLOSE_ICON}
        </button>
        <img id="lightbox-img" src="" alt="Full size image">
      </div>
    </div>

    <!-- Sources Popup -->
    <div id="sources-popup" class="info-popup hidden">
      <div class="info-popup-content">
        <!-- Content populated dynamically -->
      </div>
    </div>

    <!-- Image Generation Popup -->
    <div id="imagegen-popup" class="info-popup hidden">
      <div class="info-popup-content">
        <!-- Content populated dynamically -->
      </div>
    </div>

    <!-- Message Cost Popup -->
    <div id="message-cost-popup" class="info-popup hidden">
      <div class="info-popup-content">
        <!-- Content populated dynamically -->
      </div>
    </div>

    <!-- Cost History Popup -->
    ${getCostHistoryPopupHtml()}

    <!-- Settings Popup shell (contents + handlers lazy-load from
         SettingsPopup.ts on first open - keep the id in sync) -->
    <div id="settings-popup" class="info-popup hidden">
      <div class="info-popup-content">
        <!-- Content populated dynamically -->
      </div>
    </div>

    <!-- Login overlay -->
    <div id="login-overlay" class="login-overlay hidden">
      <div class="login-box">
        <img class="login-logo" src="/static/icon-192.png" alt="" width="64" height="64">
        <h2>AI Chatbot</h2>
        <p>Sign in to continue</p>
        <div id="google-login-btn" class="google-btn-container"></div>
        <a href="/privacy" class="login-privacy-link" target="_blank">Privacy Policy</a>
      </div>
    </div>
  `;
}

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
    renderModelDropdown();

    // Load archive count in background (non-blocking) to show archive section
    loadArchivedConversations().catch(() => {
      // Ignore errors - archive section is optional
    });

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
        updateChatTitle('AI Chatbot');
        // Clear the hash since conversation no longer exists
        clearConversationHash();
      },
      onCurrentConversationExternalUpdate: (messageCount: number) => {
        // Show banner that new messages are available
        // The user can click to reload messages
        showNewMessagesAvailableBanner(messageCount);
      },
      onPlannerDeleted: () => {
        // Planner was deleted in another tab
        if (store.isPlannerView) {
          toast.info('Planning session was deleted.');
          leavePlannerView();
          pushEmptyHash();
        }
      },
      onPlannerReset: () => {
        // Planner was reset in another tab
        if (store.isPlannerView) {
          toast.info('Planning session was reset. Reloading...');
          navigateToPlanner();
        }
      },
      onPlannerExternalUpdate: (messageCount: number) => {
        // New messages added to planner in another tab/device
        if (store.isPlannerView) {
          showNewMessagesAvailableBanner(messageCount);
        }
      },
      onAgentConversationExternalUpdate: (messageCount: number) => {
        // New messages added to agent conversation in another tab/device
        const currentConv = store.currentConversation;
        if (currentConv?.is_agent) {
          showNewMessagesAvailableBanner(messageCount);
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

  // Initialize theme early to prevent flash of wrong theme
  const { scheme, effectiveTheme } = initializeTheme();
  log.debug('Theme initialized', { scheme, effectiveTheme });

  const app = getElementById<HTMLDivElement>('app');
  if (!app) return;

  // Render app shell
  app.innerHTML = renderAppShell();

  // Booting straight into a route (deep link / PWA relaunch) must show a
  // loading state, not the new-chat welcome screen - the welcome flashing
  // before messages arrive reads as landing in the wrong place
  const bootRoute = parseHash(window.location.hash);
  if (bootRoute.type !== 'home' && bootRoute.type !== 'unknown') {
    const messagesEl = getElementById<HTMLDivElement>('messages');
    if (messagesEl) {
      clearElement(messagesEl);
      showConversationLoader();
    }
  }

  // Initialize components
  initToast();
  initModal();
  initPopupEscapeListener(); // Single Escape key listener for all popups
  initMessageInput(sendMessage, handleStopStreaming);
  initOutboxHandlers();
  initModelSelector();
  initFileUpload();
  initVoiceInput();
  initLightbox();
  initSourcesPopup();
  initImageGenPopup();
  initMessageCostPopup();
  costHistoryPopup.init();
  initAgents();
  initScrollToBottom();
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
  initVersionBanner();
  // Keep an existing push subscription working after reloads; actual
  // permission requests only happen from the Settings toggle
  void registerServiceWorker();
  initSearchInput();
  subscribeToSearchChanges(handleSearchResultClick);
  initTTSVoices();
  setupEventListeners();
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
    // started); gate the SettingsPopup import on them so boot stays lean.
    // Key literals must match TODOIST_STATE_KEY / CALENDAR_STATE_KEY there.
    if (
      sessionStorage.getItem('todoist-oauth-state') ||
      sessionStorage.getItem('calendar-oauth-state')
    ) {
      const settings = await import('../components/SettingsPopup');
      await settings.checkTodoistOAuthCallback();
      await settings.checkCalendarOAuthCallback();
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
  window.addEventListener('auth:login', async () => {
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
      };
      await loadInitialData(initialRoute);
    } catch (error) {
      log.error('Failed to load data after login', { error });
      toast.error('Failed to load data. Please refresh the page.', {
        action: { label: 'Refresh', onClick: () => window.location.reload() },
      });
    }
  });

  window.addEventListener('auth:logout', () => {
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

    // Re-render Google Sign-In button
    const loginBtn = getElementById<HTMLDivElement>('google-login-btn');
    if (loginBtn) {
      clearElement(loginBtn);
      renderGoogleButton(loginBtn);
    }

    // Re-initialize deep linking for next login
    initDeepLinking(handleDeepLinkNavigation);
  });

  // Listen for message delete events
  window.addEventListener('message:delete', (event: Event) => {
    const customEvent = event as CustomEvent<{ messageId: string }>;
    const { messageId } = customEvent.detail;
    log.debug('Message delete event received', { messageId });
    deleteMessage(messageId);
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
  }
}
window.__testFullSync = async () => {
  const syncManager = getSyncManager();
  if (syncManager) {
    await syncManager.fullSync();
  }
};
