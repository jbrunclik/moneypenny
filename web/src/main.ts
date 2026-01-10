import './styles/main.css';
import 'highlight.js/styles/github-dark.css';

import { useStore } from './state/store';
import { createLogger } from './utils/logger';
import { conversations, chat, models, config, costs, messages, ApiError } from './api/client';
import { initToast, toast } from './components/Toast';
import { initModal, showConfirm, showPrompt } from './components/Modal';
import { initGoogleSignIn, renderGoogleButton, checkAuth, logout } from './auth/google';
import {
  renderConversationsList,
  renderUserInfo,
  setActiveConversation,
  toggleSidebar,
  closeSidebar,
  updateMonthlyCost,
  cleanupInfiniteScroll,
} from './components/Sidebar';
import { initSearchInput } from './components/SearchInput';
import { subscribeToSearchChanges } from './components/SearchResults';
import {
  renderMessages,
  addMessageToUI,
  addStreamingMessage,
  updateStreamingMessage,
  finalizeStreamingMessage,
  updateStreamingThinking,
  updateStreamingToolStart,
  updateStreamingToolDetail,
  updateStreamingToolEnd,
  cleanupStreamingContext,
  hasActiveStreamingContext,
  getStreamingContextConversationId,
  getStreamingMessageElement,
  restoreStreamingMessage,
  showLoadingIndicator,
  hideLoadingIndicator,
  showConversationLoader,
  hideConversationLoader,
  updateChatTitle,
  updateUserMessageId,
  setupOlderMessagesScrollListener,
  cleanupOlderMessagesScrollListener,
  setupNewerMessagesScrollListener,
  cleanupNewerMessagesScrollListener,
  loadAllRemainingNewerMessages,
  initOrientationChangeHandler,
} from './components/Messages';
import {
  initMessageInput,
  getMessageInput,
  clearMessageInput,
  focusMessageInput,
  setInputLoading,
  shouldAutoFocusInput,
  showUploadProgress,
  hideUploadProgress,
  updateUploadProgress,
} from './components/MessageInput';
import { initModelSelector, renderModelDropdown } from './components/ModelSelector';
import { initFileUpload, clearPendingFiles, getPendingFiles } from './components/FileUpload';
import { initLightbox } from './components/Lightbox';
import { initSourcesPopup } from './components/SourcesPopup';
import { initImageGenPopup } from './components/ImageGenPopup';
import { initMessageCostPopup } from './components/MessageCostPopup';
import { costHistoryPopup, getCostHistoryPopupHtml } from './components/CostHistoryPopup';
import { initMemoriesPopup, getMemoriesPopupHtml, openMemoriesPopup } from './components/MemoriesPopup';
import { initSettingsPopup, getSettingsPopupHtml, openSettingsPopup, checkTodoistOAuthCallback } from './components/SettingsPopup';
import { initVoiceInput, stopVoiceRecording } from './components/VoiceInput';
import { initScrollToBottom, checkScrollButtonVisibility, setBeforeScrollToBottomCallback } from './components/ScrollToBottom';
import { initVersionBanner } from './components/VersionBanner';
import { createSwipeHandler, isTouchDevice, resetSwipeStates } from './gestures/swipe';
import { initSyncManager, stopSyncManager, getSyncManager } from './sync/SyncManager';
import { getElementById, isScrolledToBottom, clearElement } from './utils/dom';
import { enableScrollOnImageLoad, disableScrollOnImageLoad, getThumbnailObserver, observeThumbnail, programmaticScrollToBottom, setCurrentConversationForBlobs } from './utils/thumbnails';
import { initializeTheme } from './utils/theme';
import { initPopupEscapeListener } from './utils/popupEscapeHandler';
import {
  initDeepLinking,
  cleanupDeepLinking,
  getConversationIdFromHash,
  setConversationHash,
  clearConversationHash,
  pushEmptyHash,
  isValidConversationId,
} from './router/deeplink';
import { ATTACH_ICON, CLOSE_ICON, SEND_ICON, CHECK_ICON, MICROPHONE_ICON, STREAM_ICON, STREAM_OFF_ICON, SEARCH_ICON, SPARKLES_ICON, PLUS_ICON, SPEAKER_ICON, STOP_ICON } from './utils/icons';
import { DEFAULT_CONVERSATION_TITLE } from './types/api';
import type { Conversation, Message } from './types/api';
import { SEARCH_HIGHLIGHT_DURATION_MS, SEARCH_RESULT_MESSAGES_LIMIT } from './config';

const log = createLogger('main');

// Track the most recently requested conversation ID to handle race conditions
// When user clicks a conversation, we store its ID. If they click another
// conversation before the first loads, we update this. When an API call completes,
// we check if it matches - if not, the user navigated away and we should cancel.
let pendingConversationId: string | null = null;

// App HTML template
function renderAppShell(): string {
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
        <button id="menu-btn" class="btn-icon">☰</button>
        <span id="current-chat-title">AI Chatbot</span>
      </header>

      <div id="messages" class="messages">
        <div class="welcome-message">
          <h2>Welcome to AI Chatbot</h2>
          <p>Start a conversation with Gemini AI</p>
        </div>
      </div>

      <div class="input-area">
        <div class="input-wrapper">
          <div class="input-toolbar">
            <div class="toolbar-left">
              <div class="model-selector">
                <button id="model-selector-btn" class="model-selector-btn">
                  <span id="current-model-name">Loading...</span>
                  <span class="dropdown-arrow">▼</span>
                </button>
                <div id="model-dropdown" class="model-dropdown hidden"></div>
              </div>
              <button id="stream-btn" class="btn-toolbar active" title="Toggle streaming" aria-pressed="true">
                ${STREAM_ICON}
              </button>
              <button id="search-btn" class="btn-toolbar" title="Force web search for next message">
                ${SEARCH_ICON}
              </button>
              <button id="imagegen-btn" class="btn-toolbar" title="Force image generation for next message">
                ${SPARKLES_ICON}
              </button>
            </div>
            <div class="toolbar-right">
              <button id="voice-btn" class="btn-toolbar btn-voice" title="Voice input" aria-pressed="false">
                ${MICROPHONE_ICON}
              </button>
              <button id="attach-btn" class="btn-toolbar" title="Attach files">
                ${ATTACH_ICON}
              </button>
            </div>
          </div>
          <div id="file-preview" class="file-preview hidden"></div>
          <input type="file" id="file-input" multiple>
          <div id="upload-progress" class="upload-progress hidden">
            <div class="upload-progress-bar"></div>
            <span class="upload-progress-text">Uploading...</span>
          </div>
          <div class="input-container">
            <textarea id="message-input" placeholder="Type your message..." rows="1"></textarea>
            <button id="send-btn" class="btn btn-send" disabled>
              ${SEND_ICON}
            </button>
          </div>
          <div id="conversation-cost" class="conversation-cost-display"></div>
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

    <!-- Memories Popup -->
    ${getMemoriesPopupHtml()}

    <!-- Settings Popup -->
    ${getSettingsPopupHtml()}

    <!-- Login overlay -->
    <div id="login-overlay" class="login-overlay hidden">
      <div class="login-box">
        <h2>AI Chatbot</h2>
        <p>Sign in to continue</p>
        <div id="google-login-btn" class="google-btn-container"></div>
      </div>
    </div>
  `;
}

// Initialize the application
async function init(): Promise<void> {
  log.info('Initializing application');

  // Initialize theme early to prevent flash of wrong theme
  const { scheme, effectiveTheme } = initializeTheme();
  log.debug('Theme initialized', { scheme, effectiveTheme });

  const app = getElementById<HTMLDivElement>('app');
  if (!app) return;

  // Render app shell
  app.innerHTML = renderAppShell();

  // Initialize components
  initToast();
  initModal();
  initPopupEscapeListener(); // Single Escape key listener for all popups
  initMessageInput(sendMessage, handleStopStreaming);
  initModelSelector();
  initFileUpload();
  initVoiceInput();
  initLightbox();
  initSourcesPopup();
  initImageGenPopup();
  initMessageCostPopup();
  costHistoryPopup.init();
  initMemoriesPopup();
  initSettingsPopup();
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
  initSearchInput();
  subscribeToSearchChanges(handleSearchResultClick);
  initTTSVoices();
  setupEventListeners();
  setupTouchGestures();

  // Initialize toolbar buttons
  initToolbarButtons();

  // Initialize deep linking and capture initial conversation ID from URL
  const initialConversationId = initDeepLinking(handleDeepLinkNavigation);

  // Check authentication
  const isAuthenticated = await checkAuth();

  if (isAuthenticated) {
    hideLoginOverlay();
    // Check for Todoist OAuth callback (user returning from Todoist auth)
    await checkTodoistOAuthCallback();
    await loadInitialData(initialConversationId);
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
      const conversationId = getConversationIdFromHash();
      await loadInitialData(conversationId);
    } catch (error) {
      log.error('Failed to load data after login', { error });
      toast.error('Failed to load data. Please refresh the page.', {
        action: { label: 'Refresh', onClick: () => window.location.reload() },
      });
    }
  });

  window.addEventListener('auth:logout', () => {
    // Stop sync manager and scroll listeners on logout
    stopSyncManager();
    cleanupInfiniteScroll();
    cleanupOlderMessagesScrollListener();
    cleanupNewerMessagesScrollListener();

    // Clear URL hash and clean up deep linking
    clearConversationHash();
    cleanupDeepLinking();

    showLoginOverlay();
    useStore.getState().setConversations([], { next_cursor: null, has_more: false, total_count: 0 });
    useStore.getState().setCurrentConversation(null);
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

// Load initial data after authentication
// If initialConversationId is provided (from URL hash), load that conversation BEFORE starting sync
async function loadInitialData(initialConversationId?: string | null): Promise<void> {
  log.debug('Loading initial data', { initialConversationId });
  const store = useStore.getState();
  store.setLoading(true);

  try {
    // Load data in parallel
    const [convResult, modelsData, uploadConfig] = await Promise.all([
      conversations.list(),
      models.list(),
      config.getUploadConfig(),
    ]);

    store.setConversations(convResult.conversations, convResult.pagination);
    store.setModels(modelsData.models, modelsData.default);
    store.setUploadConfig(uploadConfig);

    log.info('Initial data loaded', { conversationCount: convResult.conversations.length, modelCount: modelsData.models.length });
    renderConversationsList();
    renderUserInfo();
    renderModelDropdown();

    // Handle initial conversation from URL hash BEFORE starting sync manager
    // This prevents false "new messages available" banners for the deep-linked conversation
    if (initialConversationId && isValidConversationId(initialConversationId)) {
      await loadDeepLinkedConversation(initialConversationId);
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
    });
    getSyncManager()?.start();
  } catch (error) {
    log.error('Failed to load initial data', { error });
    toast.error('Failed to load data. Please refresh the page.', {
      action: { label: 'Refresh', onClick: () => window.location.reload() },
    });
  } finally {
    store.setLoading(false);
  }
}

// Update conversation cost display and monthly cost in sidebar
async function updateConversationCost(convId: string | null): Promise<void> {
  const costEl = getElementById<HTMLDivElement>('conversation-cost');
  if (!costEl) return;

  if (!convId || isTempConversation(convId)) {
    costEl.textContent = '';
    return;
  }

  try {
    const costData = await costs.getConversationCost(convId);
    // Only show cost if it's greater than 0
    if (costData.cost_usd > 0) {
      costEl.textContent = costData.formatted;
    } else {
      costEl.textContent = '';
    }
    // Also update the monthly cost in the sidebar
    updateMonthlyCost();
  } catch {
    // Ignore errors - cost display is optional
    costEl.textContent = '';
  }
}

/**
 * Load a conversation from a deep link URL.
 * Handles conversations that may not be in the initially paginated list.
 * Called BEFORE sync manager starts to prevent false "new messages available" banners.
 */
async function loadDeepLinkedConversation(conversationId: string): Promise<void> {
  log.info('Loading deep-linked conversation', { conversationId });
  const store = useStore.getState();

  // Track that we're trying to load this conversation
  pendingConversationId = conversationId;

  // Check if conversation is already in the store (from initial list)
  const existingConv = store.conversations.find((c) => c.id === conversationId);

  if (existingConv) {
    // Conversation is in the list, fetch full details and switch
    log.debug('Deep-linked conversation found in store', { conversationId });
    try {
      showConversationLoader();
      const response = await conversations.get(conversationId);
      hideConversationLoader();

      // Check if user navigated away during API call
      if (pendingConversationId !== conversationId) {
        log.debug('Deep-link navigation cancelled - user navigated away', {
          requestedId: conversationId,
          pendingId: pendingConversationId,
        });
        return;
      }

      // Store messages and pagination
      store.setMessages(conversationId, response.messages, response.message_pagination);

      const conv: Conversation = {
        id: response.id,
        title: response.title,
        model: response.model,
        created_at: response.created_at,
        updated_at: response.updated_at,
        messages: response.messages,
      };
      // Use total message count from pagination for correct sync behavior
      switchToConversation(conv, response.message_pagination.total_count);
    } catch (error) {
      log.error('Failed to load deep-linked conversation', { error, conversationId });
      hideConversationLoader();
      // Clear the invalid hash and show error
      clearConversationHash();
      toast.error('Failed to load conversation from URL.', {
        action: { label: 'Retry', onClick: () => loadDeepLinkedConversation(conversationId) },
      });
    }
  } else {
    // Conversation not in paginated list - fetch directly from API
    // This handles conversations beyond the initial page load
    log.debug('Deep-linked conversation not in store, fetching from API', { conversationId });
    try {
      showConversationLoader();
      const response = await conversations.get(conversationId);
      hideConversationLoader();

      // Check if user navigated away during API call
      if (pendingConversationId !== conversationId) {
        log.debug('Deep-link navigation cancelled - user navigated away', {
          requestedId: conversationId,
          pendingId: pendingConversationId,
        });
        return;
      }

      // Add conversation to store (it wasn't in the initial list)
      // This is important for sync manager to track it correctly
      const conv: Conversation = {
        id: response.id,
        title: response.title,
        model: response.model,
        created_at: response.created_at,
        updated_at: response.updated_at,
        messages: response.messages,
        // Set messageCount from pagination for sync manager
        messageCount: response.message_pagination.total_count,
      };
      store.addConversation(conv);
      store.setMessages(conversationId, response.messages, response.message_pagination);
      renderConversationsList();

      // Switch to the conversation
      switchToConversation(conv, response.message_pagination.total_count);
    } catch (error) {
      log.error('Failed to load deep-linked conversation from API', { error, conversationId });
      hideConversationLoader();
      // Clear the invalid hash - conversation likely doesn't exist or user doesn't have access
      clearConversationHash();
      toast.error('Conversation not found or you don\'t have access to it.');
    }
  }
}

/**
 * Handle deep link navigation (browser back/forward buttons).
 * This is called when the URL hash changes via browser navigation.
 */
function handleDeepLinkNavigation(conversationId: string | null): void {
  log.debug('Deep link navigation', { conversationId });
  const store = useStore.getState();

  if (!conversationId) {
    // User navigated to home (no conversation selected)
    // Clear current conversation but don't navigate away if there's an active request
    const currentConv = store.currentConversation;
    if (currentConv && !store.getActiveRequest(currentConv.id)) {
      store.setCurrentConversation(null);
      renderMessages([]);
      updateChatTitle('AI Chatbot');
      setActiveConversation('');
      renderConversationsList();
      if (shouldAutoFocusInput()) {
        focusMessageInput();
      }
    }
    return;
  }

  // Navigate to the specified conversation
  // Skip if already viewing this conversation
  if (store.currentConversation?.id === conversationId) {
    return;
  }

  // Check if conversation is in store
  const conv = store.conversations.find((c) => c.id === conversationId);
  if (conv) {
    // Conversation is known, use selectConversation to load it
    selectConversation(conversationId);
  } else {
    // Conversation not in store - try to load it from API
    // This handles going back to a conversation that was beyond the paginated list
    loadDeepLinkedConversation(conversationId);
  }
}

// Switch to a conversation and update UI
function switchToConversation(conv: Conversation, totalMessageCount?: number): void {
  log.debug('Switching to conversation', { conversationId: conv.id, title: conv.title, totalMessageCount });
  const store = useStore.getState();

  // Clean up blob URLs from the previous conversation to prevent memory leaks
  // This must happen before we set the new conversation ID
  setCurrentConversationForBlobs(conv.id);

  // Clean up newer messages scroll listener from previous conversation
  // This must happen before setting up listeners for the new conversation
  cleanupNewerMessagesScrollListener();

  // Clean up streaming context only if switching to a DIFFERENT conversation
  // If switching back to the streaming conversation, we want to restore the UI state instead
  const streamingConvId = getStreamingContextConversationId();
  if (hasActiveStreamingContext() && streamingConvId !== conv.id) {
    log.debug('Cleaning up streaming context from different conversation', {
      streamingConvId,
      targetConvId: conv.id
    });
    cleanupStreamingContext();
  }

  store.setCurrentConversation(conv);
  setActiveConversation(conv.id);
  updateChatTitle(conv.title);

  // Update URL hash for deep linking (skips temp conversations automatically)
  setConversationHash(conv.id);

  // Hide any existing new messages banner when switching conversations
  hideNewMessagesAvailableBanner();

  // Enable scroll-to-bottom for images that load after initial render
  enableScrollOnImageLoad();

  renderMessages(conv.messages || []);

  // Set up scroll listener for loading older messages (if not a temp conversation)
  if (!isTempConversation(conv.id)) {
    setupOlderMessagesScrollListener(conv.id);
  }

  // Check if there's an active request for this conversation and restore UI state
  const activeRequest = store.getActiveRequest(conv.id);
  if (activeRequest) {
    log.debug('Restoring active request UI', { conversationId: conv.id, type: activeRequest.type });
    if (activeRequest.type === 'stream') {
      // Restore streaming message UI with accumulated content
      // The element is tracked in Messages.ts via currentStreamingContext
      restoreStreamingMessage(
        conv.id,
        activeRequest.content || '',
        activeRequest.thinkingState
      );
    } else if (activeRequest.type === 'batch') {
      // Show loading indicator for batch requests
      showLoadingIndicator();
    }
  }

  renderModelDropdown();
  closeSidebar();
  if (shouldAutoFocusInput()) {
    focusMessageInput();
  }

  // Update conversation cost
  updateConversationCost(conv.id);

  // Mark conversation as read in sync manager and re-render sidebar to clear badge
  // Use totalMessageCount if provided (from pagination), otherwise fall back to messages.length
  // This is critical for correct sync behavior: using messages.length when pagination is active
  // would set localMessageCount too low, causing false "new messages available" banners
  const messageCount = totalMessageCount ?? conv.messages?.length ?? 0;
  getSyncManager()?.markConversationRead(conv.id, messageCount);
  renderConversationsList();
}

// Select a conversation
async function selectConversation(convId: string): Promise<void> {
  const store = useStore.getState();

  // For temp conversations, just switch to them locally (no API call needed)
  if (isTempConversation(convId)) {
    const conv = store.conversations.find((c) => c.id === convId);
    if (conv) {
      pendingConversationId = convId;
      switchToConversation(conv);
      pendingConversationId = null;
    }
    return;
  }

  // Track that we're trying to load this conversation
  // If user clicks another conversation before this loads, pendingConversationId will change
  pendingConversationId = convId;

  store.setLoading(true);
  showConversationLoader();

  try {
    const response = await conversations.get(convId);
    hideConversationLoader();

    // IMPORTANT: Check if the user is still trying to view this conversation
    // During the API call, the user might have clicked "New Chat" or selected
    // a different conversation. If so, we should NOT switch to this conversation
    // as it would overwrite the current view with stale data.
    //
    // We check pendingConversationId because:
    // - If user clicked conv A, pendingConversationId = A
    // - If user then clicked conv B while A is loading, pendingConversationId = B
    // - When A's API returns, we check: is pendingConversationId still A? No → cancel
    if (pendingConversationId !== convId) {
      log.debug('Conversation selection cancelled - user navigated away', {
        requestedId: convId,
        pendingId: pendingConversationId,
      });
      return;
    }

    // Store messages and pagination in the per-conversation Maps
    store.setMessages(convId, response.messages, response.message_pagination);

    // Convert response to Conversation object for switchToConversation
    const conv: Conversation = {
      id: response.id,
      title: response.title,
      model: response.model,
      created_at: response.created_at,
      updated_at: response.updated_at,
      messages: response.messages,
    };
    // Pass total message count from pagination for correct sync behavior
    switchToConversation(conv, response.message_pagination.total_count);
  } catch (error) {
    log.error('Failed to load conversation', { error, conversationId: convId });
    hideConversationLoader();
    toast.error('Failed to load conversation.', {
      action: { label: 'Retry', onClick: () => selectConversation(convId) },
    });
  } finally {
    store.setLoading(false);
  }
}

// Check if a conversation ID is temporary (not yet saved to DB)
function isTempConversation(convId: string): boolean {
  return convId.startsWith('temp-');
}

/**
 * Handle click on a search result - navigate to conversation and optionally scroll to message
 * Search results stay visible so user can try other results
 */
async function handleSearchResultClick(convId: string, messageId: string | null, resultIndex: number): Promise<void> {
  log.debug('Search result clicked', { convId, messageId, resultIndex });

  // Track which result is being viewed (by index, not by message_id to handle duplicates)
  useStore.getState().setViewedSearchResult(resultIndex);

  // Close sidebar on mobile (user can reopen to see results)
  closeSidebar();

  // Navigate to the conversation
  await navigateToSearchResult(convId, messageId);
}

/**
 * Navigate to a conversation from search result and highlight the matching message
 */
async function navigateToSearchResult(convId: string, messageId: string | null): Promise<void> {
  const store = useStore.getState();
  const { currentConversation, streamingConversationId } = store;

  // Check if we're already viewing this conversation
  if (currentConversation?.id === convId) {
    // If streaming is active in this conversation, don't navigate away from the current view
    // as it would break the streaming UI. Just show a toast instead.
    if (streamingConversationId === convId && messageId) {
      toast.info('Please wait for the response to complete.');
      return;
    }

    // Already viewing - just scroll to message if provided
    if (messageId) {
      await scrollToAndHighlightMessage(messageId);
    }
    return;
  }

  // Load and switch to the conversation
  await selectConversation(convId);

  // After loading, scroll to and highlight the message if provided
  if (messageId) {
    // Use setTimeout to ensure DOM has updated after conversation switch
    setTimeout(async () => {
      await scrollToAndHighlightMessage(messageId);
    }, 100);
  }
}

// Track the most recently requested message ID for search navigation
// This prevents stale API responses from rendering when user clicks multiple search results quickly
let pendingSearchNavigationMessageId: string | null = null;

/**
 * Scroll to a message and apply highlight animation.
 * If the message isn't in the current DOM (due to pagination), loads messages
 * centered around the target in a single API call using around_message_id.
 */
async function scrollToAndHighlightMessage(messageId: string): Promise<void> {
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (!messagesContainer) {
    return;
  }

  const store = useStore.getState();
  const { currentConversation, streamingConversationId } = store;
  if (!currentConversation) {
    return;
  }

  // Don't perform search navigation while streaming is active in this conversation
  // as loading messages around the target would break the streaming UI
  if (streamingConversationId === currentConversation.id) {
    log.debug('Skipping search navigation while streaming is active', {
      conversationId: currentConversation.id,
    });
    return;
  }

  // Track this navigation request - if another navigation starts, we'll abort this one
  pendingSearchNavigationMessageId = messageId;

  // Try to find the message element in the current DOM first
  let messageEl = messagesContainer.querySelector<HTMLDivElement>(`.message[data-message-id="${messageId}"]`);

  // If not found in DOM, use around_message_id to load messages centered on the target
  if (!messageEl) {
    log.debug('Message not in DOM, loading messages around target', { messageId });

    try {
      // Single API call to get messages centered around the target
      const response = await conversations.getMessagesAround(
        currentConversation.id,
        messageId,
        SEARCH_RESULT_MESSAGES_LIMIT
      );

      // Guard: Check if user clicked a different search result during the API call
      if (pendingSearchNavigationMessageId !== messageId) {
        log.debug('Search navigation cancelled - user clicked different result', {
          originalMessageId: messageId,
          newMessageId: pendingSearchNavigationMessageId,
        });
        return;
      }

      // Guard: Check if user switched conversations during the API call
      const currentConvNow = useStore.getState().currentConversation;
      if (!currentConvNow || currentConvNow.id !== currentConversation.id) {
        log.debug('Conversation changed during search navigation, aborting', {
          originalConvId: currentConversation.id,
          currentConvId: currentConvNow?.id,
        });
        return;
      }

      // Replace messages in store with the new page centered on target
      store.setMessages(currentConversation.id, response.messages, response.pagination);

      // Update sync manager's local message count to match the total from pagination.
      // This prevents false unread badges when sync runs after search navigation.
      // We use the total_count from pagination, which represents ALL messages in the conversation,
      // not just the subset we loaded around the target.
      getSyncManager()?.markConversationRead(currentConversation.id, response.pagination.total_count);

      // IMPORTANT: Disable scroll-on-image-load BEFORE rendering.
      // We want to scroll to the target message, not to the bottom.
      // renderMessages() normally enables scroll-on-image-load, but we need to override that.
      disableScrollOnImageLoad();

      // Re-render messages with skipScrollToBottom: true
      // This prevents the default scroll-to-bottom behavior so we can scroll to the target instead
      renderMessages(response.messages, { skipScrollToBottom: true });

      // Set up both scroll listeners for bi-directional pagination
      // These will be cleaned up on conversation switch
      setupOlderMessagesScrollListener(currentConversation.id);
      setupNewerMessagesScrollListener(currentConversation.id);

      // Wait for layout to settle (including lazy-loaded images) before finding and scrolling
      // Use multiple RAFs to ensure images have started rendering
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            resolve();
          });
        });
      });

      // Guard again after RAFs - user might have clicked another search result
      if (pendingSearchNavigationMessageId !== messageId) {
        log.debug('Search navigation cancelled during layout - user clicked different result', {
          originalMessageId: messageId,
          newMessageId: pendingSearchNavigationMessageId,
        });
        return;
      }

      // Try to find the message element again after rendering
      messageEl = messagesContainer.querySelector<HTMLDivElement>(`.message[data-message-id="${messageId}"]`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        log.warn('Message not found via around_message_id', { messageId });
        toast.info('Message not found in this conversation.');
        return;
      }
      log.error('Failed to load messages around search result', { error, messageId });
      toast.error('Failed to navigate to message.');
      return;
    }
  }

  // If still not found after loading, show a toast
  if (!messageEl) {
    log.warn('Message element not found after loading around page', { messageId });
    toast.info('Message not found in this conversation.');
    return;
  }

  // Scroll the message into view - use 'start' to position it at the top of the viewport
  // This is better UX for long messages where 'center' would show the middle of the message
  messageEl.scrollIntoView({ behavior: 'smooth', block: 'start' });

  // Apply highlight animation
  messageEl.classList.add('search-highlight');

  // Remove highlight class after animation completes
  setTimeout(() => {
    messageEl?.classList.remove('search-highlight');
  }, SEARCH_HIGHLIGHT_DURATION_MS);

  log.debug('Scrolled to and highlighted message', { messageId });
}

// Create a new conversation (local only - saved to DB on first message)
function createConversation(): void {
  log.debug('Creating new conversation');
  const store = useStore.getState();

  // Clear any pending conversation load - user clicked "New Chat"
  pendingConversationId = null;

  // Clean up scroll listeners from previous conversation to prevent them from
  // loading messages after we switch to the new conversation
  cleanupOlderMessagesScrollListener();
  cleanupNewerMessagesScrollListener();

  // Clean up blob URLs from the previous conversation to prevent memory leaks
  setCurrentConversationForBlobs(null);

  // Create a local-only conversation with a temp ID
  const tempId = `temp-${Date.now()}`;
  const now = new Date().toISOString();

  // Use pending model if set, otherwise default model
  const model = store.pendingModel || store.defaultModel;

  // Clear cost display for new conversation
  updateConversationCost(null);
  const conv = {
    id: tempId,
    title: DEFAULT_CONVERSATION_TITLE,
    model,
    created_at: now,
    updated_at: now,
    messages: [],
  };

  store.addConversation(conv);
  store.setCurrentConversation(conv);
  // Clear pending model since it's now used
  store.setPendingModel(null);
  renderConversationsList();
  setActiveConversation(conv.id);
  updateChatTitle(conv.title);
  renderMessages([]);
  renderModelDropdown();
  closeSidebar();
  if (shouldAutoFocusInput()) {
    focusMessageInput();
  }

  // Push empty hash to history so back button works (navigates to previous conversation)
  // The real hash will be set when the conversation is persisted
  pushEmptyHash();
}

// Remove conversation from UI and clear if it was current
function removeConversationFromUI(convId: string): void {
  const store = useStore.getState();
  store.removeConversation(convId);
  renderConversationsList();

  if (store.currentConversation?.id === convId) {
    store.setCurrentConversation(null);
    renderMessages([]);
    updateChatTitle('AI Chatbot');
    // Clear the hash since conversation no longer exists
    clearConversationHash();
  }
}

// Delete a conversation
async function deleteConversation(convId: string): Promise<void> {
  const confirmed = await showConfirm({
    title: 'Delete Conversation',
    message: 'Are you sure you want to delete this conversation? This cannot be undone.',
    confirmLabel: 'Delete',
    cancelLabel: 'Cancel',
    danger: true,
  });

  if (!confirmed) return;

  // For temp conversations, just remove locally (no API call needed)
  if (isTempConversation(convId)) {
    removeConversationFromUI(convId);
    return;
  }

  try {
    await conversations.delete(convId);
    removeConversationFromUI(convId);
  } catch (error) {
    log.error('Failed to delete conversation', { error, conversationId: convId });
    toast.error('Failed to delete conversation. Please try again.');
  }
}

// Preload voices for TTS (some browsers load them asynchronously)
function initTTSVoices(): void {
  if (!('speechSynthesis' in window)) {
    log.debug('Speech synthesis not supported');
    return;
  }

  // Try to get voices immediately (works in some browsers)
  const voices = speechSynthesis.getVoices();
  if (voices.length > 0) {
    log.debug('TTS voices loaded', { count: voices.length });
    return;
  }

  // In Chrome, voices load asynchronously
  speechSynthesis.addEventListener('voiceschanged', () => {
    const loadedVoices = speechSynthesis.getVoices();
    log.debug('TTS voices loaded (async)', { count: loadedVoices.length });
  }, { once: true });
}

// Find the best voice for a language code
function findVoiceForLanguage(langCode: string): SpeechSynthesisVoice | null {
  const voices = speechSynthesis.getVoices();
  if (voices.length === 0) {
    log.debug('No voices available yet');
    return null;
  }

  // Normalize the language code
  const normalizedLang = langCode.toLowerCase();

  // Try to find a voice that matches:
  // 1. Exact match (e.g., "cs" matches "cs" or "cs-CZ" matches "cs-CZ")
  // 2. Primary language match (e.g., "cs" matches "cs-CZ")

  // First, try to find a voice where the lang starts with our code
  const matchingVoice = voices.find(v =>
    v.lang.toLowerCase().startsWith(normalizedLang + '-') ||
    v.lang.toLowerCase() === normalizedLang
  );

  if (matchingVoice) {
    log.debug('Found matching voice', { langCode, voice: matchingVoice.name, voiceLang: matchingVoice.lang });
    return matchingVoice;
  }

  // Log available voices for debugging
  log.debug('No voice found for language', {
    langCode,
    availableVoices: voices.map(v => ({ name: v.name, lang: v.lang })),
  });

  return null;
}

// Speak a message using Web Speech API
function speakMessage(messageId: string, language?: string): void {
  // Cancel any ongoing speech first
  if (speechSynthesis.speaking) {
    speechSynthesis.cancel();
    // If clicking the same message that was speaking, just stop (toggle behavior)
    const speakingButton = document.querySelector('.message-speak-btn.speaking');
    if (speakingButton) {
      const speakingMsgId = speakingButton.closest('.message')?.getAttribute('data-message-id');
      if (speakingMsgId === messageId) {
        speakingButton.classList.remove('speaking');
        speakingButton.innerHTML = SPEAKER_ICON;
        return;
      }
    }
  }

  // Clear any previous speaking state and restore icons
  document.querySelectorAll('.message-speak-btn.speaking').forEach(btn => {
    btn.classList.remove('speaking');
    btn.innerHTML = SPEAKER_ICON;
  });

  // Get the message content
  const messageEl = document.querySelector(`.message[data-message-id="${messageId}"]`);
  if (!messageEl) {
    log.warn('Message not found for TTS', { messageId });
    return;
  }

  const contentEl = messageEl.querySelector('.message-content');
  if (!contentEl) {
    log.warn('Message content not found for TTS', { messageId });
    return;
  }

  // Get text content, excluding thinking/tool traces and inline copy buttons
  const textContent = getTextContentForTTS(contentEl as HTMLElement);
  if (!textContent.trim()) {
    log.warn('No text content to speak', { messageId });
    return;
  }

  // Create utterance
  const utterance = new SpeechSynthesisUtterance(textContent);

  // Set language and find appropriate voice
  if (language) {
    // Set the lang attribute (browser may use this as fallback)
    utterance.lang = language;

    // Try to find a voice for this language
    const matchingVoice = findVoiceForLanguage(language);
    if (matchingVoice) {
      utterance.voice = matchingVoice;
    } else {
      log.warn('No voice found for language, using browser default', { language });
    }
  }

  // Mark button as speaking and swap to stop icon
  const speakBtn = messageEl.querySelector('.message-speak-btn');
  if (speakBtn) {
    speakBtn.classList.add('speaking');
    speakBtn.innerHTML = STOP_ICON;
  }

  // Handle end of speech - restore speaker icon
  utterance.onend = () => {
    speakBtn?.classList.remove('speaking');
    if (speakBtn) {
      speakBtn.innerHTML = SPEAKER_ICON;
    }
  };

  utterance.onerror = (event) => {
    log.error('TTS error', { error: event.error, messageId });
    speakBtn?.classList.remove('speaking');
    if (speakBtn) {
      speakBtn.innerHTML = SPEAKER_ICON;
    }
    // Don't show error for user-initiated cancellation or interruption
    if (event.error !== 'canceled' && event.error !== 'interrupted') {
      toast.error('Failed to read message aloud.');
    }
  };

  speechSynthesis.speak(utterance);
  log.info('Started TTS', { messageId, language, voice: utterance.voice?.name });
}

// Extract text content for TTS, excluding UI elements
function getTextContentForTTS(element: HTMLElement): string {
  // Clone to avoid modifying the actual DOM
  const clone = element.cloneNode(true) as HTMLElement;

  // Remove elements we don't want to read (UI elements, file attachments, etc.)
  clone.querySelectorAll('.thinking-indicator, .inline-copy-btn, .code-language, .copyable-header, .message-files').forEach(el => el.remove());

  // Get text content
  return clone.textContent || '';
}

// Delete a message
async function deleteMessage(messageId: string): Promise<void> {
  const confirmed = await showConfirm({
    title: 'Delete Message',
    message: 'Are you sure you want to delete this message? This cannot be undone.',
    confirmLabel: 'Delete',
    cancelLabel: 'Cancel',
    danger: true,
  });

  if (!confirmed) return;

  try {
    await messages.delete(messageId);
    // Remove the message element from the DOM
    const messageEl = document.querySelector(`.message[data-message-id="${messageId}"]`);
    if (messageEl) {
      messageEl.remove();
    }
    toast.success('Message deleted.');
  } catch (error) {
    log.error('Failed to delete message', { error, messageId });
    toast.error('Failed to delete message. Please try again.');
  }
}

// Rename a conversation
async function renameConversation(convId: string): Promise<void> {
  const store = useStore.getState();
  const conv = store.conversations.find(c => c.id === convId);

  if (!conv) {
    log.warn('Conversation not found for rename', { conversationId: convId });
    return;
  }

  const currentTitle = conv.title || DEFAULT_CONVERSATION_TITLE;

  const newTitle = await showPrompt({
    title: 'Rename Conversation',
    message: 'Enter a new name for this conversation:',
    defaultValue: currentTitle,
    placeholder: 'Conversation name',
    confirmLabel: 'Rename',
    cancelLabel: 'Cancel',
  });

  // User cancelled or entered empty string
  if (!newTitle || newTitle.trim() === '') {
    return;
  }

  const trimmedTitle = newTitle.trim();

  // No change
  if (trimmedTitle === currentTitle) {
    return;
  }

  // Validate length (backend accepts 1-200 chars)
  if (trimmedTitle.length > 200) {
    toast.error('Conversation name is too long (max 200 characters).');
    return;
  }

  // For temp conversations, just update locally (no API call needed)
  if (isTempConversation(convId)) {
    store.updateConversation(convId, { title: trimmedTitle });
    if (store.currentConversation?.id === convId) {
      updateChatTitle(trimmedTitle);
    }
    renderConversationsList();
    toast.success('Conversation renamed.');
    return;
  }

  try {
    await conversations.update(convId, { title: trimmedTitle });

    // Update local state
    store.updateConversation(convId, { title: trimmedTitle });

    // Update chat title if this is the current conversation
    if (store.currentConversation?.id === convId) {
      updateChatTitle(trimmedTitle);
    }

    // Update sidebar
    renderConversationsList();

    toast.success('Conversation renamed.');
  } catch (error) {
    log.error('Failed to rename conversation', { error, conversationId: convId });
    toast.error('Failed to rename conversation. Please try again.');
  }
}

// Update conversation title after first message (auto-generated by backend)
// Title is included in the response from both batch and streaming endpoints.
function updateConversationTitle(convId: string, title?: string): void {
  if (!title) return;

  const store = useStore.getState();
  if (store.currentConversation?.title === DEFAULT_CONVERSATION_TITLE) {
    store.updateConversation(convId, { title });
    updateChatTitle(title);
    renderConversationsList();
  }
}

// Send a message
async function sendMessage(): Promise<void> {
  // Stop voice recording if active (prevents text from being re-added after send)
  stopVoiceRecording();

  let store = useStore.getState();
  const messageText = getMessageInput();
  const files = getPendingFiles();

  if (!messageText && files.length === 0) return;

  log.info('Sending message', {
    conversationId: store.currentConversation?.id,
    messageLength: messageText.length,
    fileCount: files.length,
    streaming: store.streamingEnabled,
  });

  // Create local conversation if none selected
  if (!store.currentConversation) {
    createConversation();
    store = useStore.getState();
  }

  let conv = store.currentConversation;
  if (!conv) return;

  // If this is a temp conversation, persist it to the backend first
  if (isTempConversation(conv.id)) {
    try {
      const persistedConv = await conversations.create(conv.model);
      const tempId = conv.id;
      // Update store with real ID
      store.removeConversation(tempId);
      store.addConversation(persistedConv);
      store.setCurrentConversation(persistedConv);
      renderConversationsList();
      setActiveConversation(persistedConv.id);
      conv = persistedConv;

      // Update URL hash with the real (persisted) conversation ID
      // Use replaceState to replace the empty hash (from createConversation) with the real ID
      // This prevents empty hash entries from cluttering browser history
      setConversationHash(persistedConv.id, { replace: true });
    } catch (error) {
      log.error('Failed to create conversation', { error });
      toast.error('Failed to create conversation. Please try again.');
      return;
    }
  }

  // If we're in a partial view (e.g., after search navigation), load all remaining
  // newer messages first to ensure there's no gap when the new message is added.
  // This prevents the scenario where user searches, navigates to message 50, and sends
  // a new message which would appear after message 60 with a gap of 140 missing messages.
  const pagination = store.getMessagesPagination(conv.id);
  if (pagination?.hasNewer) {
    log.info('In partial view, loading remaining messages before send', {
      conversationId: conv.id,
      hasNewer: pagination.hasNewer,
    });
    setInputLoading(true);
    try {
      await loadAllRemainingNewerMessages(conv.id);
      // Clean up the newer messages scroll listener since we've loaded everything
      cleanupNewerMessagesScrollListener();
    } catch (error) {
      log.error('Failed to load remaining messages before send', { error, conversationId: conv.id });
      setInputLoading(false);
      toast.error('Failed to load conversation history. Please try again.');
      return;
    }
  }

  // Create user message for UI
  const userMessage: Message = {
    id: `temp-${Date.now()}`,
    role: 'user',
    content: messageText,
    files: files.map((f, i) => ({
      name: f.name,
      type: f.type,
      fileIndex: i,
      previewUrl: f.previewUrl, // Include blob URL for immediate display
    })),
    created_at: new Date().toISOString(),
  };

  // Add to UI immediately and scroll to bottom to show user's message
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (messagesContainer) {
    // Clear welcome message if present (first message in conversation)
    const welcomeMessage = messagesContainer.querySelector('.welcome-message');
    if (welcomeMessage) {
      welcomeMessage.remove();
    }
    addMessageToUI(userMessage, messagesContainer);
    // Scroll to bottom after adding user message so it's visible
    programmaticScrollToBottom(messagesContainer);
    // Update scroll button visibility after adding user message
    requestAnimationFrame(() => {
      checkScrollButtonVisibility();
    });
  }

  // Clear input and reset force tools (one-shot)
  clearMessageInput();
  clearPendingFiles();
  setInputLoading(true);
  const forceTools = [...store.forceTools];
  resetForceTools();

  try {
    if (store.streamingEnabled) {
      await sendStreamingMessage(conv.id, messageText, files, forceTools, userMessage.id);
    } else {
      await sendBatchMessage(conv.id, messageText, files, forceTools, userMessage.id);
    }
    // Clear draft on successful send
    useStore.getState().clearDraft();

    // Note: incrementLocalMessageCount is handled inside sendStreamingMessage (in finally block)
    // and sendBatchMessage (after success) to avoid race conditions with sync
  } catch (error) {
    log.error('Failed to send message', { error, conversationId: conv.id });
    hideLoadingIndicator();

    // Save draft for recovery
    useStore.getState().setDraft(messageText, files);

    // Show appropriate error toast
    if (error instanceof ApiError) {
      if (error.isTimeout) {
        toast.error('Request timed out. Your message has been saved.', {
          action: { label: 'Retry', onClick: () => retryFromDraft() },
        });
      } else if (error.isNetworkError) {
        toast.error('Network error. Please check your connection.', {
          action: { label: 'Retry', onClick: () => retryFromDraft() },
        });
      } else if (error.retryable) {
        toast.error('Failed to send message. Please try again.', {
          action: { label: 'Retry', onClick: () => retryFromDraft() },
        });
      } else {
        toast.error(error.message || 'Failed to send message.');
      }
    } else if (error instanceof Error && error.name === 'AbortError') {
      toast.warning('Request was cancelled.');
    } else {
      toast.error('An unexpected error occurred. Please try again.');
    }
  } finally {
    setInputLoading(false);
    if (shouldAutoFocusInput()) {
      focusMessageInput();
    }
  }
}

/**
 * Retry sending message from saved draft.
 */
function retryFromDraft(): void {
  const { draftMessage, draftFiles } = useStore.getState();
  if (draftMessage || draftFiles.length > 0) {
    // Restore draft to input
    const textarea = getElementById<HTMLTextAreaElement>('message-input');
    if (textarea && draftMessage) {
      textarea.value = draftMessage;
      // Trigger input event to update UI
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    }
    // Restore files to pending files
    draftFiles.forEach((file) => {
      useStore.getState().addPendingFile(file);
    });
    // Clear draft after restoring
    useStore.getState().clearDraft();
    // Focus input - user explicitly clicked retry, so it's intentional even on iOS
    if (shouldAutoFocusInput()) {
      focusMessageInput();
    }
  }
}

// Track active requests per conversation to allow continuation when switching
interface ActiveRequest {
  conversationId: string;
  type: 'stream' | 'batch';
  abortController?: AbortController;
}

const activeRequests = new Map<string, ActiveRequest>();

// Note: Streaming message elements are tracked in Messages.ts via currentStreamingContext
// Use getStreamingMessageElement(convId) to get the element for a conversation

/**
 * Abort a streaming request for a conversation.
 * Called when user clicks the stop button.
 * Returns true if a request was found and aborted.
 */
export function abortStreamingRequest(convId: string): boolean {
  for (const [requestId, request] of activeRequests.entries()) {
    if (request.conversationId === convId && request.type === 'stream' && request.abortController) {
      log.info('Aborting streaming request', { conversationId: convId, requestId });
      request.abortController.abort();
      return true;
    }
  }
  return false;
}

/**
 * Handle stop button click - abort current streaming request.
 * This is passed to MessageInput as the onStop callback.
 */
function handleStopStreaming(): void {
  const currentConvId = useStore.getState().currentConversation?.id;
  if (currentConvId) {
    const aborted = abortStreamingRequest(currentConvId);
    if (!aborted) {
      log.warn('No streaming request found to abort', { conversationId: currentConvId });
    }
  }
}

/**
 * Deep copy a ThinkingState to avoid reference issues when storing in Zustand.
 */
function deepCopyThinkingState(state: import('./types/api').ThinkingState): import('./types/api').ThinkingState {
  return {
    isThinking: state.isThinking,
    thinkingText: state.thinkingText,
    activeTool: state.activeTool,
    activeToolDetail: state.activeToolDetail,
    completedTools: [...state.completedTools],
    trace: state.trace.map(item => ({
      type: item.type,
      label: item.label,
      detail: item.detail,
      completed: item.completed,
    })),
  };
}

/**
 * Update local thinking state based on streaming event type.
 * This mirrors the logic in ThinkingIndicator.ts but operates on a local state object
 * so we can track state even when the user switches conversations.
 */
function updateLocalThinkingState(
  state: import('./types/api').ThinkingState,
  eventType: 'thinking' | 'tool_start' | 'tool_detail' | 'tool_end',
  toolOrText?: string,
  detail?: string,
  metadata?: import('./types/api').ToolMetadata
): void {
  if (eventType === 'thinking') {
    // Find existing thinking item or create one
    const thinkingItem = state.trace.find(item => item.type === 'thinking');
    if (thinkingItem) {
      thinkingItem.detail = toolOrText;
      thinkingItem.completed = false;
    } else {
      state.trace.push({
        type: 'thinking',
        label: 'thinking',
        detail: toolOrText,
        completed: false,
      });
    }
    state.thinkingText = toolOrText || '';
    state.isThinking = true;
  } else if (eventType === 'tool_detail') {
    // Update detail for an existing tool
    const toolItem = state.trace.find(
      item => item.type === 'tool' && item.label === toolOrText && !item.completed
    );
    if (toolItem) {
      toolItem.detail = detail;
    }
    if (state.activeTool === toolOrText) {
      state.activeToolDetail = detail;
    }
  } else if (eventType === 'tool_start') {
    // Mark thinking as completed
    const thinkingIndex = state.trace.findIndex(item => item.type === 'thinking');
    if (thinkingIndex !== -1) {
      state.trace[thinkingIndex].completed = true;
    }
    // Create tool item and insert before thinking (to keep thinking at end)
    const toolItem: import('./types/api').ThinkingTraceItem = {
      type: 'tool',
      label: toolOrText || '',
      detail,
      completed: false,
      metadata, // Include metadata from backend for display
    };
    if (thinkingIndex !== -1) {
      state.trace.splice(thinkingIndex, 0, toolItem);
    } else {
      state.trace.push(toolItem);
    }
    state.activeTool = toolOrText || null;
    state.activeToolDetail = detail;
    state.isThinking = false;
  } else if (eventType === 'tool_end') {
    // Find the tool and mark it completed
    for (const item of state.trace) {
      if (item.type === 'tool' && item.label === toolOrText && !item.completed) {
        item.completed = true;
        break;
      }
    }
    if (toolOrText && !state.completedTools.includes(toolOrText)) {
      state.completedTools.push(toolOrText);
    }
    if (state.activeTool === toolOrText) {
      state.activeTool = null;
      state.activeToolDetail = undefined;
    }
  }
}

// Send message with streaming response
async function sendStreamingMessage(
  convId: string,
  message: string,
  files: ReturnType<typeof getPendingFiles>,
  forceTools: string[],
  tempUserMessageId: string
): Promise<void> {
  let messageEl = addStreamingMessage(convId);
  let fullContent = '';
  // Track thinking state locally for store sync (independent of Messages.ts context)
  const localThinkingState: import('./types/api').ThinkingState = {
    isThinking: true,
    thinkingText: '',
    activeTool: null,
    activeToolDetail: undefined,
    completedTools: [],
    trace: [],
  };
  const requestId = `stream-${convId}-${Date.now()}`;
  const abortController = new AbortController();
  // Track if message was successfully sent (for incrementing count in finally block)
  let messageSuccessful = false;

  // Track this request with abort controller
  const request: ActiveRequest = {
    conversationId: convId,
    type: 'stream',
    abortController,
  };
  activeRequests.set(requestId, request);

  // Note: The message element is tracked in Messages.ts via currentStreamingContext
  // (set by addStreamingMessage). Use getStreamingMessageElement(convId) to retrieve it.

  // Register active request in store for UI restoration on conversation switch
  useStore.getState().setActiveRequest(convId, {
    conversationId: convId,
    type: 'stream',
    content: '',
    thinkingState: undefined,
  });

  // Mark conversation as streaming to prevent sync race conditions
  getSyncManager()?.setConversationStreaming(convId, true);

  // Set streaming state in store for UI updates (stop button)
  useStore.getState().setStreamingConversation(convId);

  // Show upload progress for requests with files (indeterminate since fetch doesn't support progress)
  const hasFiles = files && files.length > 0;
  if (hasFiles) {
    showUploadProgress();
    // Show indeterminate progress (no percentage available with fetch)
    updateUploadProgress(0);
    const progressText = document.querySelector('.upload-progress-text');
    if (progressText) {
      progressText.textContent = 'Uploading...';
    }
  }

  try {
    // Hide upload progress once streaming starts (upload complete)
    let uploadProgressHidden = false;

    // Check if conversation is still current before processing each event
    for await (const event of chat.stream(convId, message, files, forceTools, abortController)) {
      // Hide upload progress on first event (means upload is complete)
      if (hasFiles && !uploadProgressHidden) {
        hideUploadProgress();
        useStore.getState().setUploadProgress(null);
        uploadProgressHidden = true;
      }
      // Check if user switched conversations - if so, update store but don't update UI
      const store = useStore.getState();
      const isCurrentConversation = store.currentConversation?.id === convId;

      // Get the current message element from Messages.ts (may have been restored after conversation switch)
      // This is the single source of truth for the streaming element
      const currentMessageEl = getStreamingMessageElement(convId);
      if (currentMessageEl) {
        messageEl = currentMessageEl;
      }

      if (event.type === 'user_message_saved') {
        // Update user message ID from temp to real ID immediately (before streaming completes)
        // This enables lightbox to fetch files during streaming
        if (event.user_message_id) {
          updateUserMessageId(tempUserMessageId, event.user_message_id);
        }
      } else if (event.type === 'thinking') {
        // Update local thinking state (always, regardless of current conversation)
        updateLocalThinkingState(localThinkingState, 'thinking', event.text);
        // Update UI only if this is the current conversation
        if (isCurrentConversation) {
          updateStreamingThinking(event.text);
        }
        // Sync the full thinking state to store for restoration when switching back
        store.updateActiveRequestContent(convId, fullContent, deepCopyThinkingState(localThinkingState));
      } else if (event.type === 'tool_start') {
        // Update local thinking state (always, regardless of current conversation)
        updateLocalThinkingState(localThinkingState, 'tool_start', event.tool, event.detail, event.metadata);
        // Tool execution started (with optional detail like search query, URL, or prompt)
        if (isCurrentConversation) {
          updateStreamingToolStart(event.tool, event.detail, event.metadata);
        }
        // Sync the full thinking state to store for restoration when switching back
        store.updateActiveRequestContent(convId, fullContent, deepCopyThinkingState(localThinkingState));
      } else if (event.type === 'tool_detail') {
        // Update local thinking state with the new detail (always, regardless of current conversation)
        updateLocalThinkingState(localThinkingState, 'tool_detail', event.tool, event.detail);
        // Update the tool detail in the UI (only if current conversation)
        if (isCurrentConversation) {
          updateStreamingToolDetail(event.tool, event.detail);
        }
        // Sync the full thinking state to store for restoration when switching back
        store.updateActiveRequestContent(convId, fullContent, deepCopyThinkingState(localThinkingState));
      } else if (event.type === 'tool_end') {
        // Update local thinking state (always, regardless of current conversation)
        updateLocalThinkingState(localThinkingState, 'tool_end', event.tool);
        // Tool execution completed
        if (isCurrentConversation) {
          updateStreamingToolEnd(event.tool);
        }
        // Sync the full thinking state to store for restoration when switching back
        store.updateActiveRequestContent(convId, fullContent, deepCopyThinkingState(localThinkingState));
      } else if (event.type === 'token') {
        fullContent += event.text;
        // Mark thinking as no longer active when content starts flowing
        if (localThinkingState.isThinking) {
          localThinkingState.isThinking = false;
        }
        // Always update the store content for restoration
        store.updateActiveRequestContent(convId, fullContent, deepCopyThinkingState(localThinkingState));
        // Update UI only if this is the current conversation
        if (isCurrentConversation) {
          updateStreamingMessage(messageEl, fullContent);
        }
      } else if (event.type === 'done') {
        log.info('Streaming complete', { conversationId: convId, messageId: event.id });

        // Update user message ID from temp to real ID (for file fetching in lightbox)
        if (event.user_message_id) {
          updateUserMessageId(tempUserMessageId, event.user_message_id);
        }

        // Only update UI if this is still the current conversation
        if (isCurrentConversation) {
          finalizeStreamingMessage(messageEl, event.id, event.created_at, event.sources, event.generated_images, event.files, 'assistant', event.language);

          // Handle scroll-to-bottom for lazy-loaded images (same logic as batch mode)
          const messagesContainer = getElementById<HTMLDivElement>('messages');
          if (messagesContainer && event.files) {
            const hasImagesToLoad = event.files.some(
              (f) => f.type.startsWith('image/') && !f.previewUrl
            );
            const wasAtBottom = isScrolledToBottom(messagesContainer);
            if (hasImagesToLoad && wasAtBottom) {
              enableScrollOnImageLoad();
              programmaticScrollToBottom(messagesContainer, false);
              requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                  const images = messageEl.querySelectorAll<HTMLImageElement>(
                    'img[data-message-id][data-file-index]:not([src])'
                  );
                  images.forEach((img) => {
                    const rect = img.getBoundingClientRect();
                    const containerRect = messagesContainer.getBoundingClientRect();
                    const isVisible = rect.top < containerRect.bottom && rect.bottom > containerRect.top;
                    if (isVisible && !img.src) {
                      getThumbnailObserver().unobserve(img);
                      observeThumbnail(img);
                    }
                  });
                  checkScrollButtonVisibility();
                });
              });
            } else {
              if (wasAtBottom) {
                programmaticScrollToBottom(messagesContainer);
              }
              requestAnimationFrame(() => {
                checkScrollButtonVisibility();
              });
            }
          }

          // Update conversation title if this was the first message (title comes from response)
          updateConversationTitle(convId, event.title);

          // Update conversation cost
          await updateConversationCost(convId);

          // Mark as successful for message count increment in finally block
          messageSuccessful = true;
        }
      } else if (event.type === 'error') {
        log.error('Stream error', { message: event.message, conversationId: convId });
        // Keep partial content if any was received
        if (fullContent.trim()) {
          // Mark message as incomplete but keep the content
          messageEl.classList.add('message-incomplete');
        } else {
          messageEl.remove();
        }
        // Convert error event to ApiError and throw - outer sendMessage catch handles draft/toast
        const errorEvent = event as { message?: string; code?: string; retryable?: boolean };
        const streamError = new ApiError(
          errorEvent.message || 'Failed to generate response.',
          errorEvent.code === 'TIMEOUT' ? 408 : 500,
          {
            code: errorEvent.code,
            retryable: errorEvent.retryable ?? false,
            isTimeout: errorEvent.code === 'TIMEOUT',
          }
        );
        throw streamError;
      }
    }
  } catch (error) {
    // Check if this was a user-initiated abort
    if (error instanceof Error && error.name === 'AbortError') {
      log.info('Stream aborted by user', { conversationId: convId });
      // User actively stopped - remove the streaming assistant message from UI
      messageEl.remove();
      // Show a toast so user knows the action was successful
      toast.info('Response stopped.');
      // Note: Partial messages may remain in the backend database.
      // A future message delete button can be used to clean them up if needed.
      // Don't re-throw - this is intentional user action, not an error
      return;
    }

    log.error('Streaming failed', { error, conversationId: convId });

    // Check if conversation is still current before cleaning up UI
    const store = useStore.getState();
    const isCurrentConversation = store.currentConversation?.id === convId;

    // Keep partial content if any was received, otherwise remove the message element
    if (fullContent.trim()) {
      messageEl.classList.add('message-incomplete');
    } else {
      messageEl.remove();
    }

    // Re-throw error if this is still the current conversation
    // Outer sendMessage catch handles draft saving and toast display
    if (isCurrentConversation) {
      throw error;
    }
    // If user switched conversations, silently swallow the error
  } finally {
    // Clean up request tracking and streaming context
    activeRequests.delete(requestId);
    // Note: cleanupStreamingContext() handles clearing the element reference in Messages.ts
    cleanupStreamingContext();

    // Remove active request from store
    useStore.getState().removeActiveRequest(convId);

    // Ensure upload progress is hidden (safety net)
    hideUploadProgress();
    useStore.getState().setUploadProgress(null);

    // IMPORTANT: Increment local message count BEFORE clearing streaming flag
    // This prevents a race condition where sync happens between clearing the flag
    // and incrementing the count, causing false "new messages available" banner
    if (messageSuccessful) {
      getSyncManager()?.incrementLocalMessageCount(convId, 2);
    }

    // Clear streaming flag so sync can update this conversation again
    getSyncManager()?.setConversationStreaming(convId, false);

    // Clear streaming state in store (for stop button UI)
    useStore.getState().setStreamingConversation(null);
  }
}

// Send message with batch response
async function sendBatchMessage(
  convId: string,
  message: string,
  files: ReturnType<typeof getPendingFiles>,
  forceTools: string[],
  tempUserMessageId: string
): Promise<void> {
  const requestId = `batch-${convId}-${Date.now()}`;

  // Track this request
  const request: ActiveRequest = {
    conversationId: convId,
    type: 'batch',
  };
  activeRequests.set(requestId, request);

  // Register active request in store for UI restoration on conversation switch
  useStore.getState().setActiveRequest(convId, {
    conversationId: convId,
    type: 'batch',
  });

  // Show upload progress for requests with files
  const hasFiles = files && files.length > 0;
  if (hasFiles) {
    showUploadProgress();
  } else {
    showLoadingIndicator();
  }

  try {
    // Pass progress callback for requests with files
    const onUploadProgress = hasFiles ? (progress: number) => {
      updateUploadProgress(progress);
      useStore.getState().setUploadProgress(progress);
    } : undefined;

    const response = await chat.sendBatch(convId, message, files, forceTools, onUploadProgress);
    log.info('Batch response received', { conversationId: convId, messageId: response.id });

    // Update user message ID from temp to real ID (for file fetching in lightbox)
    if (response.user_message_id) {
      updateUserMessageId(tempUserMessageId, response.user_message_id);
    }

    // Check if conversation is still current before updating UI
    const store = useStore.getState();
    const isCurrentConversation = store.currentConversation?.id === convId;

    if (!isCurrentConversation) {
      // User switched conversations - message is saved to DB, just hide loading
      hideLoadingIndicator();
      hideUploadProgress();
      useStore.getState().setUploadProgress(null);
      return;
    }

    hideLoadingIndicator();
    hideUploadProgress();
    useStore.getState().setUploadProgress(null);

    const assistantMessage: Message = {
      id: response.id,
      role: 'assistant',
      content: response.content,
      sources: response.sources,
      generated_images: response.generated_images,
      files: response.files,
      created_at: response.created_at,
    };

    const messagesContainer = getElementById<HTMLDivElement>('messages');
    if (messagesContainer) {
      const hasImagesToLoad = assistantMessage.files?.some(
        (f) => f.type.startsWith('image/') && !f.previewUrl
      );
      const wasAtBottom = isScrolledToBottom(messagesContainer);
      if (hasImagesToLoad && wasAtBottom) {
        enableScrollOnImageLoad();
      }
      addMessageToUI(assistantMessage, messagesContainer);
      if (hasImagesToLoad && wasAtBottom) {
        // Scroll to bottom immediately to ensure images are visible
        // IntersectionObserver will re-check after scroll and fire for visible images
        programmaticScrollToBottom(messagesContainer, false);
        // Use double RAF to ensure scroll completed and layout settled
        // Then check if images need manual triggering (fallback)
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            const messageEl = messagesContainer.querySelector(
              `[data-message-id="${assistantMessage.id}"]`
            );
            if (messageEl) {
              const images = messageEl.querySelectorAll<HTMLImageElement>(
                'img[data-message-id][data-file-index]:not([src])'
              );
              // If images are visible but haven't started loading, manually trigger
              // This is a fallback in case IntersectionObserver didn't fire
              images.forEach((img) => {
                const rect = img.getBoundingClientRect();
                const containerRect = messagesContainer.getBoundingClientRect();
                const isVisible = rect.top < containerRect.bottom && rect.bottom > containerRect.top;
                if (isVisible && !img.src) {
                  // Image is visible but not loading - unobserve and re-observe to trigger check
                  getThumbnailObserver().unobserve(img);
                  observeThumbnail(img);
                }
              });
            }
            checkScrollButtonVisibility();
          });
        });
      } else {
        if (wasAtBottom) {
          programmaticScrollToBottom(messagesContainer);
        }
        requestAnimationFrame(() => {
          checkScrollButtonVisibility();
        });
      }
    }

    // Update conversation title if this was the first message (title comes from response)
    updateConversationTitle(convId, response.title);

    // Update conversation cost
    await updateConversationCost(convId);

    // Update sync manager's local message count (user message + assistant response = 2)
    // This is done here (after success) to ensure the count is updated before any sync
    getSyncManager()?.incrementLocalMessageCount(convId, 2);
  } catch (error) {
    hideLoadingIndicator();
    hideUploadProgress();
    useStore.getState().setUploadProgress(null);

    // Check if conversation is still current before showing errors
    const store = useStore.getState();
    const isCurrentConversation = store.currentConversation?.id === convId;

    if (!isCurrentConversation) {
      // User switched conversations - silently handle error, message will be in DB
      return;
    }

    throw error;
  } finally {
    // Clean up request tracking
    activeRequests.delete(requestId);
    // Remove active request from store
    useStore.getState().removeActiveRequest(convId);
    // Ensure upload progress is hidden (safety net)
    hideUploadProgress();
    useStore.getState().setUploadProgress(null);
  }
}

// Initialize toolbar buttons (stream toggle, search toggle, imagegen toggle)
function initToolbarButtons(): void {
  const store = useStore.getState();
  const streamBtn = getElementById<HTMLButtonElement>('stream-btn');
  const searchBtn = getElementById<HTMLButtonElement>('search-btn');
  const imagegenBtn = getElementById<HTMLButtonElement>('imagegen-btn');

  // Initialize stream button state from store
  if (streamBtn) {
    updateStreamButtonState(streamBtn, store.streamingEnabled);
    streamBtn.addEventListener('click', () => {
      const currentState = useStore.getState().streamingEnabled;
      const newState = !currentState;
      useStore.getState().setStreamingEnabled(newState);
      updateStreamButtonState(streamBtn, newState);
    });
  }

  // Initialize search button (one-shot toggle for web_search tool)
  if (searchBtn) {
    updateSearchButtonState(searchBtn, store.forceTools.includes('web_search'));
    searchBtn.addEventListener('click', () => {
      useStore.getState().toggleForceTool('web_search');
      const isActive = useStore.getState().forceTools.includes('web_search');
      updateSearchButtonState(searchBtn, isActive);
    });
  }

  // Initialize image generation button (one-shot toggle for generate_image tool)
  if (imagegenBtn) {
    updateImagegenButtonState(imagegenBtn, store.forceTools.includes('generate_image'));
    imagegenBtn.addEventListener('click', () => {
      useStore.getState().toggleForceTool('generate_image');
      const isActive = useStore.getState().forceTools.includes('generate_image');
      updateImagegenButtonState(imagegenBtn, isActive);
    });
  }
}

// Update stream button visual state
function updateStreamButtonState(btn: HTMLButtonElement, enabled: boolean): void {
  btn.classList.toggle('active', enabled);
  btn.setAttribute('aria-pressed', String(enabled));
  btn.innerHTML = enabled ? STREAM_ICON : STREAM_OFF_ICON;
  btn.title = enabled ? 'Streaming enabled (click to disable)' : 'Streaming disabled (click to enable)';
}

// Update search button visual state
function updateSearchButtonState(btn: HTMLButtonElement, active: boolean): void {
  btn.classList.toggle('active', active);
  btn.title = active ? 'Web search will be used for next message' : 'Force web search for next message';
}

// Update image generation button visual state
function updateImagegenButtonState(btn: HTMLButtonElement, active: boolean): void {
  btn.classList.toggle('active', active);
  btn.title = active ? 'Image generation will be used for next message' : 'Force image generation for next message';
}

// Reset force tools and update UI after message is sent
function resetForceTools(): void {
  const searchBtn = getElementById<HTMLButtonElement>('search-btn');
  const imagegenBtn = getElementById<HTMLButtonElement>('imagegen-btn');
  useStore.getState().clearForceTools();
  if (searchBtn) {
    updateSearchButtonState(searchBtn, false);
  }
  if (imagegenBtn) {
    updateImagegenButtonState(imagegenBtn, false);
  }
}

// Setup event listeners
function setupEventListeners(): void {
  // New chat button
  getElementById('new-chat-btn')?.addEventListener('click', createConversation);

  // Mobile menu button
  getElementById('menu-btn')?.addEventListener('click', toggleSidebar);

  // User info area clicks (logout and monthly cost buttons)
  getElementById('user-info')?.addEventListener('click', async (e) => {
    if ((e.target as HTMLElement).closest('#logout-btn')) {
      logout();
      return;
    }
    if ((e.target as HTMLElement).closest('#monthly-cost')) {
      try {
        const history = await costs.getCostHistory(12);
        const { openCostHistory } = await import('./components/CostHistoryPopup');
        openCostHistory(history);
      } catch (error) {
        log.error('Failed to load cost history', { error });
        toast.error('Failed to load cost history.');
      }
      return;
    }
    if ((e.target as HTMLElement).closest('#memories-btn')) {
      openMemoriesPopup();
      return;
    }
    if ((e.target as HTMLElement).closest('#settings-btn')) {
      openSettingsPopup();
    }
  });

  // Conversation list clicks
  getElementById('conversations-list')?.addEventListener('click', (e) => {
    // Handle rename button clicks
    const renameBtn = (e.target as HTMLElement).closest('[data-rename-id]');
    if (renameBtn) {
      e.stopPropagation();
      const id = (renameBtn as HTMLElement).dataset.renameId;
      if (id) {
        resetSwipeStates();
        renameConversation(id);
      }
      return;
    }

    // Handle delete button clicks
    const deleteBtn = (e.target as HTMLElement).closest('[data-delete-id]');
    if (deleteBtn) {
      e.stopPropagation();
      const id = (deleteBtn as HTMLElement).dataset.deleteId;
      if (id) {
        resetSwipeStates();
        deleteConversation(id);
      }
      return;
    }

    // Handle conversation selection
    const convItem = (e.target as HTMLElement).closest('.conversation-item');
    if (convItem) {
      const wrapper = convItem.closest('[data-conv-id]');
      if (wrapper) {
        resetSwipeStates();
        const id = (wrapper as HTMLElement).dataset.convId;
        if (id) selectConversation(id);
      }
    }
  });

  // Document preview (open in new tab), download buttons, and message copy buttons
  getElementById('messages')?.addEventListener('click', (e) => {
    // Document preview (click on filename to open in new tab)
    const previewLink = (e.target as HTMLElement).closest('.document-preview');
    if (previewLink) {
      e.preventDefault();
      const messageId = (previewLink as HTMLElement).dataset.messageId;
      const fileIndex = (previewLink as HTMLElement).dataset.fileIndex;
      const fileName = (previewLink as HTMLElement).dataset.fileName;
      const fileType = (previewLink as HTMLElement).dataset.fileType;
      if (messageId && fileIndex) {
        openFileInNewTab(messageId, parseInt(fileIndex, 10), fileName || 'file', fileType || '');
      }
      return;
    }

    // Document download button
    const downloadBtn = (e.target as HTMLElement).closest('.document-download');
    if (downloadBtn) {
      const messageId = (downloadBtn as HTMLElement).dataset.messageId;
      const fileIndex = (downloadBtn as HTMLElement).dataset.fileIndex;
      const fileName = (downloadBtn as HTMLElement).dataset.fileName;
      if (messageId && fileIndex) {
        downloadFile(messageId, parseInt(fileIndex, 10), fileName || `file-${fileIndex}`);
      }
      return;
    }

    const copyBtn = (e.target as HTMLElement).closest('.message-copy-btn');
    if (copyBtn) {
      copyMessageContent(copyBtn as HTMLButtonElement);
      return;
    }

    // Inline copy button (code blocks, tables)
    const inlineCopyBtn = (e.target as HTMLElement).closest('.inline-copy-btn');
    if (inlineCopyBtn) {
      copyInlineContent(inlineCopyBtn as HTMLButtonElement);
    }
  });
}

// Copy message content to clipboard with rich text support
async function copyMessageContent(button: HTMLButtonElement): Promise<void> {
  const messageEl = button.closest('.message');
  const contentEl = messageEl?.querySelector('.message-content');

  if (!contentEl) return;

  // Clone the content and remove non-response elements (files, thinking/tool traces, inline copy buttons)
  const clone = contentEl.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('.message-files').forEach((el) => el.remove());
  clone.querySelectorAll('.thinking-indicator').forEach((el) => el.remove());
  clone.querySelectorAll('.inline-copy-btn').forEach((el) => el.remove());
  clone.querySelectorAll('.code-language').forEach((el) => el.remove());

  const textContent = clone.textContent?.trim();
  if (!textContent) return;

  try {
    // Copy as both plain text and HTML for rich text support
    await copyWithRichText(clone.innerHTML, textContent);
    showCopySuccess(button);
  } catch (error) {
    log.error('Failed to copy to clipboard', { error });
    toast.error('Failed to copy to clipboard.');
  }
}

// Copy inline content (code blocks, tables) to clipboard
async function copyInlineContent(button: HTMLButtonElement): Promise<void> {
  const wrapper = button.closest('.copyable-content');
  if (!wrapper) return;

  const isCodeBlock = wrapper.classList.contains('code-block-wrapper');
  const isTable = wrapper.classList.contains('table-wrapper');

  let textContent: string;
  let htmlContent: string;

  if (isCodeBlock) {
    // For code blocks, copy plain text only (no formatting needed)
    const codeEl = wrapper.querySelector('code');
    textContent = codeEl?.textContent?.trim() || '';
    htmlContent = `<pre><code>${textContent}</code></pre>`;
  } else if (isTable) {
    // For tables, copy with HTML formatting
    const tableEl = wrapper.querySelector('table');
    if (!tableEl) return;
    textContent = tableToPlainText(tableEl);
    htmlContent = tableEl.outerHTML;
  } else {
    return;
  }

  if (!textContent) return;

  try {
    await copyWithRichText(htmlContent, textContent);
    showCopySuccess(button);
  } catch (error) {
    log.error('Failed to copy to clipboard', { error });
    toast.error('Failed to copy to clipboard.');
  }
}

// Copy content with both HTML and plain text formats
async function copyWithRichText(html: string, plainText: string): Promise<void> {
  // Try to use the modern clipboard API with multiple formats
  if (navigator.clipboard && typeof ClipboardItem !== 'undefined') {
    try {
      const htmlBlob = new Blob([html], { type: 'text/html' });
      const textBlob = new Blob([plainText], { type: 'text/plain' });
      const clipboardItem = new ClipboardItem({
        'text/html': htmlBlob,
        'text/plain': textBlob,
      });
      await navigator.clipboard.write([clipboardItem]);
      return;
    } catch {
      // Fall back to plain text if ClipboardItem fails
    }
  }

  // Fallback to plain text only
  await navigator.clipboard.writeText(plainText);
}

// Convert table to plain text with tab-separated values
function tableToPlainText(table: HTMLTableElement): string {
  const rows: string[] = [];

  table.querySelectorAll('tr').forEach((tr) => {
    const cells: string[] = [];
    tr.querySelectorAll('th, td').forEach((cell) => {
      cells.push((cell.textContent || '').trim());
    });
    rows.push(cells.join('\t'));
  });

  return rows.join('\n');
}

// Show copy success feedback on button
function showCopySuccess(button: HTMLButtonElement): void {
  const originalHtml = button.innerHTML;
  button.innerHTML = CHECK_ICON;
  button.classList.add('copied');

  setTimeout(() => {
    button.innerHTML = originalHtml;
    button.classList.remove('copied');
  }, 2000);
}

// Setup touch gestures
function setupTouchGestures(): void {
  if (!isTouchDevice()) return;

  const conversationsList = getElementById('conversations-list');
  const sidebar = getElementById('sidebar');
  const main = document.querySelector('.main') as HTMLElement | null;

  if (!conversationsList || !sidebar || !main) return;

  // Constants
  const SWIPE_THRESHOLD = 60;
  const SWIPE_DISTANCE = 160; // Updated from 80 to accommodate both rename and delete buttons
  const EDGE_ZONE = 50; // px from left edge to trigger sidebar swipe

  // Track active swipe type to prevent conflicts
  let activeSwipeType: 'none' | 'conversation' | 'sidebar' = 'none';

  // Swipe to reveal rename and delete on conversations
  const conversationSwipe = createSwipeHandler({
    shouldStart: (e) => {
      if (activeSwipeType === 'sidebar') return false;
      const wrapper = (e.target as HTMLElement).closest('.conversation-item-wrapper');
      if (!wrapper) {
        resetSwipeStates();
        return false;
      }
      // Prevent starting new swipe if clicking action buttons
      if ((e.target as HTMLElement).closest('.conversation-rename-swipe')) return false;
      if ((e.target as HTMLElement).closest('.conversation-delete-swipe')) return false;
      // Note: We set activeSwipeType in onSwipeMove (when actual swiping starts),
      // not here, to avoid blocking sidebar swipes after a tap (non-swipe touch)
      return true;
    },
    getTarget: (e) => {
      const wrapper = (e.target as HTMLElement).closest('.conversation-item-wrapper');
      return wrapper?.querySelector('.conversation-item') as HTMLElement | null;
    },
    getTransform: (deltaX, isOpen, { maxDistance }) => {
      if (isOpen && deltaX < 0) {
        const translateX = Math.max(deltaX + maxDistance, 0);
        return `translateX(-${translateX}px)`;
      } else if (!isOpen && deltaX > 0) {
        const translateX = Math.min(deltaX, maxDistance);
        return `translateX(-${translateX}px)`;
      }
      return null;
    },
    getInitialState: (target) => {
      return target?.closest('.conversation-item-wrapper')?.classList.contains('swiped') || false;
    },
    onSwipeMove: () => {
      // Mark as conversation swipe once actual swiping starts
      // This prevents sidebar swipes from interfering mid-gesture
      activeSwipeType = 'conversation';
    },
    onComplete: (target, deltaX) => {
      activeSwipeType = 'none';
      const wrapper = target.closest('.conversation-item-wrapper');
      if (!wrapper) return;

      const isOpen = wrapper.classList.contains('swiped');
      if (isOpen && deltaX < -SWIPE_THRESHOLD) {
        wrapper.classList.remove('swiped');
      } else if (!isOpen && deltaX > SWIPE_THRESHOLD) {
        resetSwipeStates(wrapper as HTMLElement);
        wrapper.classList.add('swiped');
      }
    },
    onSnapBack: (target) => {
      activeSwipeType = 'none';
      const wrapper = target.closest('.conversation-item-wrapper');
      wrapper?.classList.remove('swiped');
    },
    threshold: SWIPE_THRESHOLD,
    maxDistance: SWIPE_DISTANCE,
  });

  conversationsList.addEventListener('touchstart', conversationSwipe.handleTouchStart, { passive: true });
  conversationsList.addEventListener('touchmove', conversationSwipe.handleTouchMove, { passive: true });
  conversationsList.addEventListener('touchend', conversationSwipe.handleTouchEnd, { passive: true });
  conversationsList.addEventListener('touchcancel', conversationSwipe.handleTouchCancel, { passive: true });

  // Sidebar edge swipe - swipe from left edge to open, swipe left to close
  let sidebarSwipeStartX = 0;
  let sidebarSwipeCurrentX = 0;
  let isSidebarSwiping = false;
  const sidebarWidth = 280; // matches CSS --sidebar-width

  const handleSidebarTouchStart = (e: TouchEvent): void => {
    if (activeSwipeType === 'conversation') return;

    const target = e.target as HTMLElement;
    const startX = e.touches[0].clientX;
    const isSidebarOpen = sidebar.classList.contains('open');

    // Don't start sidebar swipe if touching a conversation item (let conversation swipe handle it)
    if (target.closest('.conversation-item-wrapper')) {
      // Reset activeSwipeType if it was stuck on 'sidebar' from a previous incomplete swipe
      if (activeSwipeType === 'sidebar') {
        activeSwipeType = 'none';
      }
      return;
    }

    // Start swipe if:
    // - Closed: in edge zone (swipe right to open)
    // - Open: anywhere on sidebar or overlay (swipe left to close)
    const shouldStartSwipe = isSidebarOpen
      ? target.closest('.sidebar') || target.closest('.sidebar-overlay')
      : startX < EDGE_ZONE;

    if (shouldStartSwipe) {
      sidebarSwipeStartX = startX;
      sidebarSwipeCurrentX = startX;
      isSidebarSwiping = false;
      activeSwipeType = 'sidebar';
    } else {
      // Reset if we're not starting a sidebar swipe
      if (activeSwipeType === 'sidebar') {
        activeSwipeType = 'none';
      }
    }
  };

  const handleSidebarTouchMove = (e: TouchEvent): void => {
    if (activeSwipeType !== 'sidebar') return;

    sidebarSwipeCurrentX = e.touches[0].clientX;
    const deltaX = sidebarSwipeCurrentX - sidebarSwipeStartX;
    const isSidebarOpen = sidebar.classList.contains('open');

    // Determine if this is a horizontal swipe
    if (!isSidebarSwiping && Math.abs(deltaX) > 10) {
      isSidebarSwiping = true;
    }

    if (isSidebarSwiping) {
      let translateX: number;

      if (isSidebarOpen) {
        // Sidebar is open - allow swiping left to close
        translateX = Math.max(Math.min(deltaX, 0), -sidebarWidth);
      } else {
        // Sidebar is closed - allow swiping right to open
        translateX = Math.min(Math.max(deltaX - sidebarWidth, -sidebarWidth), 0);
      }

      sidebar.style.transform = `translateX(${translateX}px)`;
      sidebar.style.transition = 'none';
    }
  };

  const handleSidebarTouchEnd = (): void => {
    if (activeSwipeType !== 'sidebar') return;

    const deltaX = sidebarSwipeCurrentX - sidebarSwipeStartX;
    const isSidebarOpen = sidebar.classList.contains('open');

    sidebar.style.transform = '';
    sidebar.style.transition = '';

    if (isSidebarSwiping) {
      if (isSidebarOpen && deltaX < -SWIPE_THRESHOLD) {
        // Close sidebar
        closeSidebar();
      } else if (!isSidebarOpen && deltaX > SWIPE_THRESHOLD) {
        // Open sidebar
        toggleSidebar();
      }
    }

    isSidebarSwiping = false;
    activeSwipeType = 'none';
  };

  // Handle touch cancel (iOS Safari can cancel touches during gestures)
  const handleSidebarTouchCancel = (): void => {
    sidebar.style.transform = '';
    sidebar.style.transition = '';
    isSidebarSwiping = false;
    activeSwipeType = 'none';
  };

  // Attach sidebar swipe to main area (for edge swipe to open)
  main.addEventListener('touchstart', handleSidebarTouchStart, { passive: true });
  main.addEventListener('touchmove', handleSidebarTouchMove, { passive: true });
  main.addEventListener('touchend', handleSidebarTouchEnd, { passive: true });
  main.addEventListener('touchcancel', handleSidebarTouchCancel, { passive: true });

  // Attach to sidebar itself (for swipe left to close)
  sidebar.addEventListener('touchstart', handleSidebarTouchStart, { passive: true });
  sidebar.addEventListener('touchmove', handleSidebarTouchMove, { passive: true });
  sidebar.addEventListener('touchend', handleSidebarTouchEnd, { passive: true });
  sidebar.addEventListener('touchcancel', handleSidebarTouchCancel, { passive: true });

  // Listen on document for overlay swipes and edge swipes
  document.addEventListener('touchstart', (e) => {
    const target = e.target as HTMLElement;
    const startX = e.touches[0].clientX;
    // Handle overlay swipes or edge swipes outside sidebar
    if (target.closest('.sidebar-overlay') || (startX < EDGE_ZONE && !target.closest('.sidebar'))) {
      handleSidebarTouchStart(e);
    }
  }, { passive: true });

  document.addEventListener('touchmove', handleSidebarTouchMove, { passive: true });
  document.addEventListener('touchend', handleSidebarTouchEnd, { passive: true });
  document.addEventListener('touchcancel', handleSidebarTouchCancel, { passive: true });

  // Close swipe on outside touch
  document.addEventListener('touchstart', (e) => {
    if (!(e.target as HTMLElement).closest('.conversation-item-wrapper')) {
      resetSwipeStates();
    }
  }, { passive: true });
}

// Open a file in a new browser tab (for preview)
async function openFileInNewTab(
  messageId: string,
  fileIndex: number,
  fileName: string,
  fileType: string
): Promise<void> {
  try {
    const { files } = await import('./api/client');
    const blob = await files.fetchFile(messageId, fileIndex);
    const url = URL.createObjectURL(blob);

    // Open in new tab
    const newTab = window.open(url, '_blank');

    // Clean up URL after a delay (give time for the tab to load)
    // For PDFs and other documents, the browser needs the URL to remain valid
    setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 60000); // Keep URL valid for 1 minute

    if (!newTab) {
      toast.warning('Pop-up blocked. Please allow pop-ups to preview files.');
    }
  } catch (error) {
    log.error('Failed to open file', { error, messageId, fileIndex, fileName, fileType });
    toast.error('Failed to open file.');
  }
}

// Download a file with correct filename
async function downloadFile(messageId: string, fileIndex: number, fileName: string): Promise<void> {
  try {
    const { files } = await import('./api/client');
    const blob = await files.fetchFile(messageId, fileIndex);
    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    URL.revokeObjectURL(url);
  } catch (error) {
    log.error('Failed to download file', { error, messageId, fileIndex, fileName });
    toast.error('Failed to download file.');
  }
}

// Show/hide login overlay
function showLoginOverlay(): void {
  getElementById('login-overlay')?.classList.remove('hidden');
}

function hideLoginOverlay(): void {
  getElementById('login-overlay')?.classList.add('hidden');
}

// Show banner when new messages are available from another device
// Note: We don't use the messageCount parameter from the callback because
// we get the accurate total_count from the API when reloading the conversation
function showNewMessagesAvailableBanner(_messageCount: number): void {
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (!messagesContainer) return;

  // Don't show if banner already exists
  if (messagesContainer.querySelector('.new-messages-banner')) return;

  const store = useStore.getState();
  const currentConvId = store.currentConversation?.id;
  if (!currentConvId) return;

  const banner = document.createElement('div');
  banner.className = 'new-messages-banner';
  banner.innerHTML = `
    <span>New messages available</span>
    <button class="btn btn-small">Reload</button>
  `;

  banner.querySelector('button')?.addEventListener('click', async () => {
    banner.remove();

    // Reload the conversation
    if (currentConvId && !isTempConversation(currentConvId)) {
      try {
        const store = useStore.getState();
        const response = await conversations.get(currentConvId);

        // Check if user switched away during API call
        const currentConv = useStore.getState().currentConversation;
        if (currentConv?.id !== currentConvId) {
          log.debug('Reload cancelled - user switched away', {
            requestedId: currentConvId,
            currentId: currentConv?.id,
          });
          return;
        }

        // Store messages and pagination in the per-conversation Maps
        store.setMessages(currentConvId, response.messages, response.message_pagination);

        // Convert response to Conversation object for switchToConversation
        // Use the actual total_count from the response, not the passed messageCount
        // The passed messageCount is from the sync callback and may be stale
        const conv: Conversation = {
          id: response.id,
          title: response.title,
          model: response.model,
          created_at: response.created_at,
          updated_at: response.updated_at,
          messages: response.messages,
        };
        // Pass total message count from pagination for correct sync behavior
        const totalCount = response.message_pagination.total_count;
        switchToConversation(conv, totalCount);
      } catch (error) {
        log.error('Failed to reload conversation', { error, conversationId: currentConvId });
        toast.error('Failed to reload conversation.');
      }
    }
  });

  // Insert at the top of messages container
  messagesContainer.insertBefore(banner, messagesContainer.firstChild);
}

// Hide the new messages banner
function hideNewMessagesAvailableBanner(): void {
  const banner = document.querySelector('.new-messages-banner');
  banner?.remove();
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

// Start the app
document.addEventListener('DOMContentLoaded', init);