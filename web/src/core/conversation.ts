/**
 * Conversation management module.
 * Handles conversation CRUD, selection, temp IDs, and switching.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { agents, conversations, messages } from '../api/client';
import { toast } from '../components/Toast';
import { showConfirm, showPrompt } from '../components/Modal';
import {
  renderConversationsList,
  setActiveConversation,
  closeSidebar,
  setPlannerActive,
} from '../components/Sidebar';
import {
  renderMessages,
  showConversationLoader,
  hideConversationLoader,
  updateChatTitle,
  setupOlderMessagesScrollListener,
  cleanupOlderMessagesScrollListener,
  cleanupNewerMessagesScrollListener,
  showLoadingIndicator,
  restoreStreamingMessage,
  hasActiveStreamingContext,
  getStreamingContextConversationId,
  cleanupStreamingContext,
} from '../components/messages';
import {
  focusMessageInput,
  ensureInputAreaVisible,
  shouldAutoFocusInput,
} from '../components/MessageInput';
import { renderModelDropdown } from '../components/ModelSelector';
import { getElementById } from '../utils/dom';
import { enableScrollOnImageLoad, setCurrentConversationForBlobs } from '../utils/thumbnails';
import {
  setConversationHash,
  clearConversationHash,
  pushEmptyHash,
} from '../router/deeplink';
import { DEFAULT_CONVERSATION_TITLE } from '../types/api';
import type { Conversation } from '../types/api';
import { getSyncManager } from '../sync/SyncManager';

import { updateConversationCost, updateAnonymousButtonState } from './toolbar';
import { leavePlannerView } from './planner';
import { hideNewMessagesAvailableBanner } from './sync-banner';
import { leaveAgentsView } from './agents';

const log = createLogger('conversation');

// Track the most recently requested conversation ID to handle race conditions
// When user clicks a conversation, we store its ID. If they click another
// conversation before the first loads, we update this. When an API call completes,
// we check if it matches - if not, the user navigated away and we should cancel.
let pendingConversationId: string | null = null;

/**
 * Get the pending conversation ID (for race condition checks).
 */
export function getPendingConversationId(): string | null {
  return pendingConversationId;
}

/**
 * Set the pending conversation ID.
 */
export function setPendingConversationId(id: string | null): void {
  pendingConversationId = id;
}

/**
 * Check if a conversation ID is temporary (not yet saved to DB).
 */
export function isTempConversation(convId: string | undefined): boolean {
  return convId?.startsWith('temp-') ?? false;
}

/**
 * Switch to a conversation and update UI.
 */
export function switchToConversation(conv: Conversation, totalMessageCount?: number): void {
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

  // Pass server's pending approval status if this is an agent conversation
  renderMessages(conv.messages || [], {
    hasPendingApproval: conv.has_pending_approval,
  });

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

  // Ensure input area is visible (defensive fix for race conditions
  // when navigating between agents/planner/conversation views)
  ensureInputAreaVisible();

  if (shouldAutoFocusInput()) {
    focusMessageInput();
  }

  // Update anonymous button state for the new conversation
  const anonymousBtn = getElementById<HTMLButtonElement>('anonymous-btn');
  if (anonymousBtn) {
    updateAnonymousButtonState(anonymousBtn, store.getAnonymousMode(conv.id));
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

/**
 * Select a conversation.
 *
 * Uses the navigation token pattern for race condition prevention:
 * 1. Call startNavigation() to get a token before async operations
 * 2. After async completes, check isNavigationValid(token) before rendering
 * 3. If invalid, another navigation started - abort without rendering
 */
export async function selectConversation(convId: string): Promise<void> {
  const store = useStore.getState();

  // Get navigation token to detect if user navigates to planner/agents during load
  // This supplements pendingConversationId which only tracks conversation-to-conversation
  // See docs/features/agents.md section "Routing Race Condition Prevention"
  const navToken = store.startNavigation();

  // If we're in planner view, leave it first
  if (store.isPlannerView) {
    store.setIsPlannerView(false);
    setPlannerActive(false);
  }

  // If we're in agents view, leave it first (but don't clear messages - we'll load the conversation)
  if (store.isAgentsView) {
    leaveAgentsView(false);
  }

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

    // IMPORTANT: Check if the user is still trying to view this conversation
    // During the API call, the user might have clicked "New Chat" or selected
    // a different conversation. If so, we should NOT switch to this conversation
    // as it would overwrite the current view with stale data.
    //
    // We check two things:
    // 1. pendingConversationId - detects conversation-to-conversation navigation
    // 2. navigation token - detects navigation to planner/agents (generic pattern)
    //
    // The navigation token pattern works for any new screens:
    // - Each navigation call increments the token
    // - If token changed, another navigation started → cancel
    if (pendingConversationId !== convId || !useStore.getState().isNavigationValid(navToken)) {
      log.debug('Conversation selection cancelled - user navigated away', {
        requestedId: convId,
        pendingId: pendingConversationId,
        navToken,
      });
      // Don't hide loader - another navigation may need it
      return;
    }

    // Safe to hide loader now - this navigation will proceed
    hideConversationLoader();

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
      is_agent: response.is_agent,
      agent_id: response.agent_id,
      has_pending_approval: response.has_pending_approval,
    };

    // Mark agent conversation as viewed to reset unread count
    // Also track the agent for sync purposes
    if (response.is_agent && response.agent_id) {
      // Track agent for sync manager to detect external updates
      getSyncManager()?.setViewedAgent(response.agent_id, response.message_pagination.total_count);

      agents.markViewed(response.agent_id)
        .then(() => {
          // Refresh command center data to update badge counts
          return agents.getCommandCenter();
        })
        .then((data) => {
          store.setCommandCenterData(data);
        })
        .catch((err) => {
          log.warn('Failed to mark agent as viewed', { agentId: response.agent_id, error: err });
        });
    } else {
      // Not an agent conversation - clear any tracked agent
      getSyncManager()?.setViewedAgent(null);
    }

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

/**
 * Create a new conversation (local only - saved to DB on first message).
 */
export function createConversation(): void {
  log.debug('Creating new conversation');
  const store = useStore.getState();

  // If we're in planner view, leave it first
  if (store.isPlannerView) {
    store.setIsPlannerView(false);
    setPlannerActive(false);
  }

  // If we're in agents view, leave it first
  if (store.isAgentsView) {
    leaveAgentsView(false);
  }

  // Clear any tracked agent since we're starting a new conversation
  getSyncManager()?.setViewedAgent(null);

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

  // Apply pending anonymous mode to the new conversation, then clear it
  const pendingAnonymous = store.pendingAnonymousMode;
  if (pendingAnonymous) {
    store.setAnonymousMode(tempId, true);
  }
  store.setPendingAnonymousMode(false);

  renderConversationsList();
  setActiveConversation(conv.id);
  updateChatTitle(conv.title);
  renderMessages([]);
  renderModelDropdown();
  closeSidebar();

  // Ensure input area is visible (defensive fix for race conditions
  // when navigating between agents/planner/conversation views)
  ensureInputAreaVisible();

  if (shouldAutoFocusInput()) {
    focusMessageInput();
  }

  // Update anonymous button state (reflects pending state that was just applied)
  const anonymousBtn = getElementById<HTMLButtonElement>('anonymous-btn');
  if (anonymousBtn) {
    updateAnonymousButtonState(anonymousBtn, pendingAnonymous);
  }

  // Push empty hash to history so back button works (navigates to previous conversation)
  // The real hash will be set when the conversation is persisted
  pushEmptyHash();
}

/**
 * Remove conversation from UI and clear if it was current.
 */
export function removeConversationFromUI(convId: string): void {
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

/**
 * Delete a conversation.
 */
export async function deleteConversation(convId: string): Promise<void> {
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

/**
 * Delete a message.
 */
export async function deleteMessage(messageId: string): Promise<void> {
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

/**
 * Rename a conversation.
 */
export async function renameConversation(convId: string): Promise<void> {
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

/**
 * Update conversation title after first message (auto-generated by backend).
 * Title is included in the response from both batch and streaming endpoints.
 */
export function updateConversationTitle(convId: string, title?: string): void {
  if (!title) return;

  const store = useStore.getState();
  if (store.currentConversation?.title === DEFAULT_CONVERSATION_TITLE) {
    store.updateConversation(convId, { title });
    updateChatTitle(title);
    renderConversationsList();
  }
}

/**
 * Load a conversation from a deep link URL.
 * Handles conversations that may not be in the initially paginated list.
 * Called BEFORE sync manager starts to prevent false "new messages available" banners.
 */
export async function loadDeepLinkedConversation(conversationId: string): Promise<void> {
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

      // Check if user navigated away during API call
      if (pendingConversationId !== conversationId) {
        log.debug('Deep-link navigation cancelled - user navigated away', {
          requestedId: conversationId,
          pendingId: pendingConversationId,
        });
        // Don't hide loader - another navigation may need it
        return;
      }

      // Safe to hide loader now - this navigation will proceed
      hideConversationLoader();

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

      // Check if user navigated away during API call
      if (pendingConversationId !== conversationId) {
        log.debug('Deep-link navigation cancelled - user navigated away', {
          requestedId: conversationId,
          pendingId: pendingConversationId,
        });
        // Don't hide loader - another navigation may need it
        return;
      }

      // Safe to hide loader now - this navigation will proceed
      hideConversationLoader();

      // Add conversation to store (it wasn't in the initial list)
      // This is important for sync manager to track it correctly
      // Note: Don't add agent conversations to store - they're handled separately
      // and would be detected as "deleted" by sync since they're not in the sync response
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
      if (!response.is_agent) {
        store.addConversation(conv);
        renderConversationsList();
      }
      store.setMessages(conversationId, response.messages, response.message_pagination);

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
export function handleDeepLinkNavigation(conversationId: string | null, isPlanner?: boolean, isAgents?: boolean): void {
  log.debug('Deep link navigation', { conversationId, isPlanner, isAgents });
  const store = useStore.getState();

  // Handle planner navigation - import dynamically to avoid circular dependency
  if (isPlanner) {
    import('./planner').then(({ navigateToPlanner }) => {
      navigateToPlanner();
    });
    return;
  }

  // Handle agents navigation - import dynamically to avoid circular dependency
  if (isAgents) {
    import('./agents').then(({ navigateToAgents }) => {
      navigateToAgents();
    });
    return;
  }

  // If we were in planner view and navigating away, leave planner
  if (store.isPlannerView) {
    leavePlannerView();
  }

  // If we were in agents view and navigating away, leave agents
  if (store.isAgentsView) {
    import('./agents').then(({ leaveAgentsView }) => {
      leaveAgentsView();
    });
  }

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
