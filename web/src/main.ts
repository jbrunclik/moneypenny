import './styles/main.css';
import 'highlight.js/styles/github-dark.css';

import { useStore } from './state/store';
import { createLogger } from './utils/logger';
import { conversations, chat, models, config, costs, ApiError } from './api/client';
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
} from './components/Sidebar';
import {
  renderMessages,
  addMessageToUI,
  addStreamingMessage,
  updateStreamingMessage,
  finalizeStreamingMessage,
  updateStreamingThinking,
  updateStreamingToolStart,
  updateStreamingToolEnd,
  cleanupStreamingContext,
  showLoadingIndicator,
  hideLoadingIndicator,
  showConversationLoader,
  hideConversationLoader,
  updateChatTitle,
} from './components/Messages';
import {
  initMessageInput,
  getMessageInput,
  clearMessageInput,
  focusMessageInput,
  setInputLoading,
} from './components/MessageInput';
import { initModelSelector, renderModelDropdown } from './components/ModelSelector';
import { initFileUpload, clearPendingFiles, getPendingFiles } from './components/FileUpload';
import { initLightbox } from './components/Lightbox';
import { initSourcesPopup } from './components/SourcesPopup';
import { initImageGenPopup } from './components/ImageGenPopup';
import { initMessageCostPopup } from './components/MessageCostPopup';
import { costHistoryPopup, getCostHistoryPopupHtml } from './components/CostHistoryPopup';
import { initMemoriesPopup, getMemoriesPopupHtml, openMemoriesPopup } from './components/MemoriesPopup';
import { initSettingsPopup, getSettingsPopupHtml, openSettingsPopup } from './components/SettingsPopup';
import { initVoiceInput, stopVoiceRecording } from './components/VoiceInput';
import { initScrollToBottom, checkScrollButtonVisibility } from './components/ScrollToBottom';
import { initVersionBanner } from './components/VersionBanner';
import { createSwipeHandler, isTouchDevice, resetSwipeStates } from './gestures/swipe';
import { initSyncManager, stopSyncManager, getSyncManager } from './sync/SyncManager';
import { getElementById, isScrolledToBottom, clearElement, scrollToBottom } from './utils/dom';
import { enableScrollOnImageLoad, getThumbnailObserver, observeThumbnail, programmaticScrollToBottom } from './utils/thumbnails';
import { ATTACH_ICON, CLOSE_ICON, SEND_ICON, CHECK_ICON, MICROPHONE_ICON, STREAM_ICON, STREAM_OFF_ICON, SEARCH_ICON, SPARKLES_ICON, PLUS_ICON } from './utils/icons';
import { DEFAULT_CONVERSATION_TITLE } from './types/api';
import type { Conversation, Message } from './types/api';

const log = createLogger('main');

// App HTML template
function renderAppShell(): string {
  return `
    <!-- Sidebar -->
    <aside id="sidebar" class="sidebar">
      <div class="sidebar-header">
        <h1>AI Chatbot</h1>
        <button id="new-chat-btn" class="btn btn-primary">${PLUS_ICON} New Chat</button>
      </div>
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
          <div class="input-container">
            <textarea id="message-input" placeholder="Type your message..." rows="1" autofocus></textarea>
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
  const app = getElementById<HTMLDivElement>('app');
  if (!app) return;

  // Render app shell
  app.innerHTML = renderAppShell();

  // Initialize components
  initToast();
  initModal();
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
  initVersionBanner();
  setupEventListeners();
  setupTouchGestures();

  // Initialize toolbar buttons
  initToolbarButtons();

  // Check authentication
  const isAuthenticated = await checkAuth();

  if (isAuthenticated) {
    hideLoginOverlay();
    await loadInitialData();
  } else {
    showLoginOverlay();
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
      await loadInitialData();
    } catch (error) {
      log.error('Failed to load data after login', { error });
      toast.error('Failed to load data. Please refresh the page.', {
        action: { label: 'Refresh', onClick: () => window.location.reload() },
      });
    }
  });

  window.addEventListener('auth:logout', () => {
    // Stop sync manager on logout
    stopSyncManager();

    showLoginOverlay();
    useStore.getState().setConversations([]);
    useStore.getState().setCurrentConversation(null);
    renderConversationsList();
    renderMessages([]);

    // Re-render Google Sign-In button
    const loginBtn = getElementById<HTMLDivElement>('google-login-btn');
    if (loginBtn) {
      clearElement(loginBtn);
      renderGoogleButton(loginBtn);
    }
  });

}

// Load initial data after authentication
async function loadInitialData(): Promise<void> {
  log.debug('Loading initial data');
  const store = useStore.getState();
  store.setLoading(true);

  try {
    // Load data in parallel
    const [convList, modelsData, uploadConfig] = await Promise.all([
      conversations.list(),
      models.list(),
      config.getUploadConfig(),
    ]);

    store.setConversations(convList);
    store.setModels(modelsData.models, modelsData.default);
    store.setUploadConfig(uploadConfig);

    log.info('Initial data loaded', { conversationCount: convList.length, modelCount: modelsData.models.length });
    renderConversationsList();
    renderUserInfo();
    renderModelDropdown();

    // Initialize sync manager after data is loaded
    initSyncManager({
      onConversationsUpdated: () => {
        renderConversationsList();
      },
      onCurrentConversationDeleted: () => {
        store.setCurrentConversation(null);
        renderMessages([]);
        updateChatTitle('AI Chatbot');
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

// Switch to a conversation and update UI
function switchToConversation(conv: Conversation): void {
  log.debug('Switching to conversation', { conversationId: conv.id, title: conv.title });
  const store = useStore.getState();
  store.setCurrentConversation(conv);
  setActiveConversation(conv.id);
  updateChatTitle(conv.title);

  // Hide any existing new messages banner when switching conversations
  hideNewMessagesAvailableBanner();

  // Enable scroll-to-bottom for images that load after initial render
  enableScrollOnImageLoad();

  renderMessages(conv.messages || []);
  renderModelDropdown();
  closeSidebar();
  focusMessageInput();

  // Update conversation cost
  updateConversationCost(conv.id);

  // Mark conversation as read in sync manager and re-render sidebar to clear badge
  const messageCount = conv.messages?.length || 0;
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
      switchToConversation(conv);
    }
    return;
  }

  store.setLoading(true);
  showConversationLoader();

  try {
    const conv = await conversations.get(convId);
    hideConversationLoader();
    switchToConversation(conv);
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

// Create a new conversation (local only - saved to DB on first message)
function createConversation(): void {
  log.debug('Creating new conversation');
  const store = useStore.getState();

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
  focusMessageInput();
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
    } catch (error) {
      log.error('Failed to create conversation', { error });
      toast.error('Failed to create conversation. Please try again.');
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
    scrollToBottom(messagesContainer);
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
      await sendStreamingMessage(conv.id, messageText, files, forceTools);
    } else {
      await sendBatchMessage(conv.id, messageText, files, forceTools);
    }
    // Clear draft on successful send
    useStore.getState().clearDraft();

    // Update sync manager's local message count (user message + assistant response = 2)
    getSyncManager()?.incrementLocalMessageCount(conv.id, 2);
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
    focusMessageInput();
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
    // Focus input
    focusMessageInput();
  }
}

// Track active requests per conversation to allow continuation when switching
interface ActiveRequest {
  conversationId: string;
  type: 'stream' | 'batch';
  abortController?: AbortController;
}

const activeRequests = new Map<string, ActiveRequest>();

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

// Send message with streaming response
async function sendStreamingMessage(
  convId: string,
  message: string,
  files: ReturnType<typeof getPendingFiles>,
  forceTools: string[]
): Promise<void> {
  const messageEl = addStreamingMessage();
  let fullContent = '';
  const requestId = `stream-${convId}-${Date.now()}`;
  const abortController = new AbortController();

  // Track this request with abort controller
  const request: ActiveRequest = {
    conversationId: convId,
    type: 'stream',
    abortController,
  };
  activeRequests.set(requestId, request);

  // Mark conversation as streaming to prevent sync race conditions
  getSyncManager()?.setConversationStreaming(convId, true);

  // Set streaming state in store for UI updates (stop button)
  useStore.getState().setStreamingConversation(convId);

  try {
    // Check if conversation is still current before processing each event
    for await (const event of chat.stream(convId, message, files, forceTools, abortController)) {
      // Check if user switched conversations - if so, silently continue in background
      const store = useStore.getState();
      const isCurrentConversation = store.currentConversation?.id === convId;

      if (!isCurrentConversation) {
        // User switched conversations - continue processing in background but don't update UI
        // The message will be saved to DB and visible when user switches back
        continue;
      }
      if (event.type === 'thinking') {
        // Update thinking indicator with thinking text
        updateStreamingThinking(event.text);
      } else if (event.type === 'tool_start') {
        // Tool execution started (with optional detail like search query, URL, or prompt)
        updateStreamingToolStart(event.tool, event.detail);
      } else if (event.type === 'tool_end') {
        // Tool execution completed
        updateStreamingToolEnd(event.tool);
      } else if (event.type === 'token') {
        fullContent += event.text;
        updateStreamingMessage(messageEl, fullContent);
      } else if (event.type === 'done') {
        log.info('Streaming complete', { conversationId: convId, messageId: event.id });
        finalizeStreamingMessage(messageEl, event.id, event.created_at, event.sources, event.generated_images, event.files);

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
    cleanupStreamingContext();

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
  forceTools: string[]
): Promise<void> {
  const requestId = `batch-${convId}-${Date.now()}`;

  // Track this request
  const request: ActiveRequest = {
    conversationId: convId,
    type: 'batch',
  };
  activeRequests.set(requestId, request);

  showLoadingIndicator();

  try {
    const response = await chat.sendBatch(convId, message, files, forceTools);
    log.info('Batch response received', { conversationId: convId, messageId: response.id });

    // Check if conversation is still current before updating UI
    const store = useStore.getState();
    const isCurrentConversation = store.currentConversation?.id === convId;

    if (!isCurrentConversation) {
      // User switched conversations - message is saved to DB, just hide loading
      hideLoadingIndicator();
      return;
    }

    hideLoadingIndicator();

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
  } catch (error) {
    hideLoadingIndicator();

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
    }
  });
}

// Copy message content to clipboard
async function copyMessageContent(button: HTMLButtonElement): Promise<void> {
  const messageEl = button.closest('.message');
  const contentEl = messageEl?.querySelector('.message-content');

  if (!contentEl) return;

  // Clone the content element and remove file attachments to get clean text
  const clone = contentEl.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('.message-files').forEach((el) => el.remove());

  const textContent = clone.textContent?.trim();
  if (!textContent) return;

  try {
    await navigator.clipboard.writeText(textContent);

    // Show success feedback
    const originalHtml = button.innerHTML;
    button.innerHTML = CHECK_ICON;
    button.classList.add('copied');

    setTimeout(() => {
      button.innerHTML = originalHtml;
      button.classList.remove('copied');
    }, 2000);
  } catch (error) {
    log.error('Failed to copy to clipboard', { error });
    toast.error('Failed to copy to clipboard.');
  }
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
function showNewMessagesAvailableBanner(messageCount: number): void {
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
        const conv = await conversations.get(currentConvId);
        switchToConversation(conv);

        // Mark as read in sync manager
        getSyncManager()?.markConversationRead(currentConvId, messageCount);
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