import './styles/main.css';
import 'highlight.js/styles/github-dark.css';

import { useStore } from './state/store';
import { conversations, chat, models, config } from './api/client';
import { initGoogleSignIn, renderGoogleButton, checkAuth, logout } from './auth/google';
import {
  renderConversationsList,
  renderUserInfo,
  setActiveConversation,
  toggleSidebar,
  closeSidebar,
} from './components/Sidebar';
import {
  renderMessages,
  addMessageToUI,
  addStreamingMessage,
  updateStreamingMessage,
  finalizeStreamingMessage,
  showLoadingIndicator,
  hideLoadingIndicator,
  showConversationLoader,
  hideConversationLoader,
  updateChatTitle,
  addStreamingDetails,
  updateStreamingDetails,
  finalizeStreamingDetails,
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
import { initVoiceInput } from './components/VoiceInput';
import { initScrollToBottom } from './components/ScrollToBottom';
import { createSwipeHandler, isTouchDevice, resetSwipeStates } from './gestures/swipe';
import { getElementById } from './utils/dom';
import { ATTACH_ICON, CLOSE_ICON, SEND_ICON, CHECK_ICON, MICROPHONE_ICON, STREAM_ICON, STREAM_OFF_ICON, SEARCH_ICON, PLUS_ICON } from './utils/icons';
import { DEFAULT_CONVERSATION_TITLE } from './types/api';
import type { Conversation, Message, DetailEvent } from './types/api';

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
  const app = getElementById<HTMLDivElement>('app');
  if (!app) return;

  // Render app shell
  app.innerHTML = renderAppShell();

  // Initialize components
  initMessageInput(sendMessage);
  initModelSelector();
  initFileUpload();
  initVoiceInput();
  initLightbox();
  initScrollToBottom();
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
    await loadInitialData();
  });

  window.addEventListener('auth:logout', () => {
    showLoginOverlay();
    useStore.getState().setConversations([]);
    useStore.getState().setCurrentConversation(null);
    renderConversationsList();
    renderMessages([]);

    // Re-render Google Sign-In button
    const loginBtn = getElementById<HTMLDivElement>('google-login-btn');
    if (loginBtn) {
      loginBtn.innerHTML = ''; // Clear any existing content
      renderGoogleButton(loginBtn);
    }
  });
}

// Load initial data after authentication
async function loadInitialData(): Promise<void> {
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

    renderConversationsList();
    renderUserInfo();
    renderModelDropdown();
  } catch (error) {
    console.error('Failed to load initial data:', error);
  } finally {
    store.setLoading(false);
  }
}

// Switch to a conversation and update UI
function switchToConversation(conv: Conversation): void {
  const store = useStore.getState();
  store.setCurrentConversation(conv);
  setActiveConversation(conv.id);
  updateChatTitle(conv.title);
  renderMessages(conv.messages || []);
  renderModelDropdown();
  closeSidebar();
  focusMessageInput();
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
    console.error('Failed to load conversation:', error);
    hideConversationLoader();
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
  const store = useStore.getState();

  // Create a local-only conversation with a temp ID
  const tempId = `temp-${Date.now()}`;
  const now = new Date().toISOString();
  const conv = {
    id: tempId,
    title: DEFAULT_CONVERSATION_TITLE,
    model: store.defaultModel,
    created_at: now,
    updated_at: now,
    messages: [],
  };

  store.addConversation(conv);
  store.setCurrentConversation(conv);
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
  // TODO: Replace confirm() with custom modal
  if (!confirm('Delete this conversation?')) return;

  // For temp conversations, just remove locally (no API call needed)
  if (isTempConversation(convId)) {
    removeConversationFromUI(convId);
    return;
  }

  try {
    await conversations.delete(convId);
    removeConversationFromUI(convId);
  } catch (error) {
    console.error('Failed to delete conversation:', error);
  }
}

// Update conversation title after first message (auto-generated by backend)
async function refreshConversationTitle(convId: string): Promise<void> {
  const store = useStore.getState();
  if (store.currentConversation?.title === DEFAULT_CONVERSATION_TITLE) {
    const updatedConv = await conversations.get(convId);
    store.updateConversation(convId, { title: updatedConv.title });
    updateChatTitle(updatedConv.title);
    renderConversationsList();
  }
}

// Send a message
async function sendMessage(): Promise<void> {
  let store = useStore.getState();
  const messageText = getMessageInput();
  const files = getPendingFiles();

  if (!messageText && files.length === 0) return;

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
      console.error('Failed to create conversation:', error);
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

  // Add to UI immediately
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (messagesContainer) {
    // Clear welcome message if present (first message in conversation)
    const welcomeMessage = messagesContainer.querySelector('.welcome-message');
    if (welcomeMessage) {
      welcomeMessage.remove();
    }
    addMessageToUI(userMessage, messagesContainer);
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
  } catch (error) {
    console.error('Failed to send message:', error);
    hideLoadingIndicator();
  } finally {
    setInputLoading(false);
    focusMessageInput();
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
  const details: DetailEvent[] = [];

  // Add details section placeholder for streaming
  addStreamingDetails(messageEl);

  try {
    for await (const event of chat.stream(convId, message, files, forceTools)) {
      if (event.type === 'token') {
        fullContent += event.text;
        updateStreamingMessage(messageEl, fullContent);
      } else if (event.type === 'tool_call') {
        // Track tool call for details
        details.push({
          type: 'tool_call',
          id: event.id,
          name: event.name,
          args: event.args,
        });
        updateStreamingDetails(messageEl, details);
      } else if (event.type === 'tool_result') {
        // Track tool result for details
        details.push({
          type: 'tool_result',
          tool_call_id: event.tool_call_id,
          content: event.content,
        });
        updateStreamingDetails(messageEl, details);
      } else if (event.type === 'thinking') {
        // Track thinking for details (Phase 2)
        details.push({
          type: 'thinking',
          content: event.content,
        });
        updateStreamingDetails(messageEl, details);
      } else if (event.type === 'done') {
        // Finalize details section
        finalizeStreamingDetails(messageEl, event.id, event.details);
        finalizeStreamingMessage(messageEl, event.id, event.created_at);

        // Update conversation title if this was the first message
        await refreshConversationTitle(convId);
      } else if (event.type === 'error') {
        console.error('Stream error:', event.message);
        messageEl.remove();
      }
    }
  } catch (error) {
    console.error('Streaming failed:', error);
    messageEl.remove();
    throw error;
  }
}

// Send message with batch response
async function sendBatchMessage(
  convId: string,
  message: string,
  files: ReturnType<typeof getPendingFiles>,
  forceTools: string[]
): Promise<void> {
  showLoadingIndicator();

  try {
    const response = await chat.sendBatch(convId, message, files, forceTools);
    hideLoadingIndicator();

    const assistantMessage: Message = {
      id: response.id,
      role: 'assistant',
      content: response.content,
      created_at: response.created_at,
    };

    const messagesContainer = getElementById<HTMLDivElement>('messages');
    if (messagesContainer) {
      addMessageToUI(assistantMessage, messagesContainer);
    }

    // Update conversation title if this was the first message
    await refreshConversationTitle(convId);
  } catch (error) {
    hideLoadingIndicator();
    throw error;
  }
}

// Initialize toolbar buttons (stream toggle, search toggle)
function initToolbarButtons(): void {
  const store = useStore.getState();
  const streamBtn = getElementById<HTMLButtonElement>('stream-btn');
  const searchBtn = getElementById<HTMLButtonElement>('search-btn');

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

// Reset force tools and update UI after message is sent
function resetForceTools(): void {
  const searchBtn = getElementById<HTMLButtonElement>('search-btn');
  useStore.getState().clearForceTools();
  if (searchBtn) {
    updateSearchButtonState(searchBtn, false);
  }
}

// Setup event listeners
function setupEventListeners(): void {
  // New chat button
  getElementById('new-chat-btn')?.addEventListener('click', createConversation);

  // Mobile menu button
  getElementById('menu-btn')?.addEventListener('click', toggleSidebar);

  // Logout button (rendered dynamically)
  getElementById('user-info')?.addEventListener('click', (e) => {
    if ((e.target as HTMLElement).closest('#logout-btn')) {
      logout();
    }
  });

  // Conversation list clicks
  getElementById('conversations-list')?.addEventListener('click', (e) => {
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

  // Document download buttons and message copy buttons
  getElementById('messages')?.addEventListener('click', (e) => {
    const downloadBtn = (e.target as HTMLElement).closest('.document-download');
    if (downloadBtn) {
      const messageId = (downloadBtn as HTMLElement).dataset.messageId;
      const fileIndex = (downloadBtn as HTMLElement).dataset.fileIndex;
      if (messageId && fileIndex) {
        downloadFile(messageId, parseInt(fileIndex, 10));
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
    console.error('Failed to copy:', error);
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
  const SWIPE_DISTANCE = 80;
  const EDGE_ZONE = 50; // px from left edge to trigger sidebar swipe

  // Track active swipe type to prevent conflicts
  let activeSwipeType: 'none' | 'conversation' | 'sidebar' = 'none';

  // Swipe to reveal delete on conversations
  const conversationSwipe = createSwipeHandler({
    shouldStart: (e) => {
      if (activeSwipeType === 'sidebar') return false;
      const wrapper = (e.target as HTMLElement).closest('.conversation-item-wrapper');
      if (!wrapper) {
        resetSwipeStates();
        return false;
      }
      if ((e.target as HTMLElement).closest('.conversation-delete-swipe')) return false;
      activeSwipeType = 'conversation';
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
    if (target.closest('.conversation-item-wrapper')) return;

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

  // Attach sidebar swipe to main area (for edge swipe to open)
  main.addEventListener('touchstart', handleSidebarTouchStart, { passive: true });
  main.addEventListener('touchmove', handleSidebarTouchMove, { passive: true });
  main.addEventListener('touchend', handleSidebarTouchEnd, { passive: true });

  // Attach to sidebar itself (for swipe left to close)
  sidebar.addEventListener('touchstart', handleSidebarTouchStart, { passive: true });
  sidebar.addEventListener('touchmove', handleSidebarTouchMove, { passive: true });
  sidebar.addEventListener('touchend', handleSidebarTouchEnd, { passive: true });

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

  // Close swipe on outside touch
  document.addEventListener('touchstart', (e) => {
    if (!(e.target as HTMLElement).closest('.conversation-item-wrapper')) {
      resetSwipeStates();
    }
  }, { passive: true });
}

// Download a file
async function downloadFile(messageId: string, fileIndex: number): Promise<void> {
  try {
    const { files } = await import('./api/client');
    const blob = await files.fetchFile(messageId, fileIndex);
    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = `file-${fileIndex}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);

    URL.revokeObjectURL(url);
  } catch (error) {
    console.error('Failed to download file:', error);
  }
}

// Show/hide login overlay
function showLoginOverlay(): void {
  getElementById('login-overlay')?.classList.remove('hidden');
}

function hideLoginOverlay(): void {
  getElementById('login-overlay')?.classList.add('hidden');
}

// Start the app
document.addEventListener('DOMContentLoaded', init);