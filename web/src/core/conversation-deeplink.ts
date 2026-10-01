/**
 * Deep links: loading a conversation from the URL on boot, and routing
 * browser back/forward hash changes to the right view.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { conversations } from '../api/conversations';
import { toast } from '../components/Toast';
import { reconcileOutboxWithServer } from './outbox';
import { renderConversationsList, setActiveConversation } from '../components/Sidebar';
import {
  renderMessages,
  showConversationLoader,
  hideConversationLoader,
  updateChatTitle,
} from '../components/messages';
import { focusMessageInput, shouldAutoFocusInput } from '../components/MessageInput';
import {
  clearConversationHash,
  getSportsProgramFromHash,
  getLanguageProgramFromHash,
} from '../router/deeplink';
import type { ConversationDetailResponse } from '../types/api';
import { APP_NAME } from '../config';
import {
  getPendingConversationId,
  selectConversation,
  setPendingConversationId,
  toConversation,
  trackViewedAgentConversation,
} from './conversation';
import { switchToConversation } from './conversation-switch';
import { navigateToArchive, leaveArchiveView } from './archive';
import { navigateToTrash, leaveTrashView } from './trash';
import { leavePlannerView, navigateToPlanner } from './planner';
import { leaveStorageView, navigateToStorage } from './kv-store';
import { leaveSportsView, navigateToSportsProgram, navigateToSports } from './sports';
import { leaveLanguageView, navigateToLanguageProgram, navigateToLanguage } from './language';
import { leaveAgentsView, navigateToAgents } from './agents';

const log = createLogger('conversation');

/**
 * Fetch the conversation behind a deep link. Returns null when the user
 * navigated elsewhere during the request (the loader stays up for that
 * other navigation); otherwise hides the loader and returns the response.
 */
async function fetchDeepLinked(conversationId: string): Promise<ConversationDetailResponse | null> {
  showConversationLoader();
  const response = await conversations.get(conversationId);

  // Check if user navigated away during API call
  if (getPendingConversationId() !== conversationId) {
    log.debug('Deep-link navigation cancelled - user navigated away', {
      requestedId: conversationId,
      pendingId: getPendingConversationId(),
    });
    // Don't hide loader - another navigation may need it
    return null;
  }

  // Safe to hide loader now - this navigation will proceed
  hideConversationLoader();
  return response;
}

/** Deep link to a conversation that is already in the sidebar list. */
async function openKnownDeepLinked(conversationId: string): Promise<void> {
  // Conversation is in the list, fetch full details and switch
  log.debug('Deep-linked conversation found in store', { conversationId });
  try {
    const response = await fetchDeepLinked(conversationId);
    if (!response) return;

    // Merge unconfirmed outbox sends, then store messages and pagination
    const mergedMessages = reconcileOutboxWithServer(conversationId, response.messages);
    useStore.getState().setMessages(conversationId, mergedMessages, response.message_pagination);

    trackViewedAgentConversation(response);
    // Use total message count from pagination for correct sync behavior
    switchToConversation(toConversation(response, mergedMessages), response.message_pagination.total_count);
  } catch (error) {
    log.error('Failed to load deep-linked conversation', { error, conversationId });
    hideConversationLoader();
    // Clear the invalid hash and show error
    clearConversationHash();
    toast.error('Failed to load conversation from URL.', {
      action: { label: 'Retry', onClick: () => loadDeepLinkedConversation(conversationId) },
    });
  }
}

/** Deep link to a conversation beyond the initially paginated list. */
async function openUnlistedDeepLinked(conversationId: string): Promise<void> {
  // Conversation not in paginated list - fetch directly from API
  // This handles conversations beyond the initial page load
  log.debug('Deep-linked conversation not in store, fetching from API', { conversationId });
  try {
    const response = await fetchDeepLinked(conversationId);
    if (!response) return;
    const store = useStore.getState();

    // Add conversation to store (it wasn't in the initial list)
    // This is important for sync manager to track it correctly
    // Note: Don't add agent conversations to store - they're handled separately
    // and would be detected as "deleted" by sync since they're not in the sync response
    const mergedMessages = reconcileOutboxWithServer(conversationId, response.messages);
    const conv = {
      ...toConversation(response, mergedMessages),
      // Set messageCount from pagination for sync manager
      messageCount: response.message_pagination.total_count,
    };
    // Agent conversations are managed separately; archived ones must not
    // appear in the main sidebar list (and sync would treat them oddly)
    if (!response.is_agent && !response.archived) {
      store.addConversation(conv);
      renderConversationsList();
    }
    trackViewedAgentConversation(response);
    store.setMessages(conversationId, mergedMessages, response.message_pagination);

    // Switch to the conversation
    switchToConversation(conv, response.message_pagination.total_count);
  } catch (error) {
    log.error('Failed to load deep-linked conversation from API', { error, conversationId });
    hideConversationLoader();
    // Fall back to the welcome state - the boot path replaced it with
    // the loader, so it must be re-rendered explicitly
    renderMessages([]);
    // Clear the invalid hash - conversation likely doesn't exist or user doesn't have access
    clearConversationHash();
    toast.error('Conversation not found or you don\'t have access to it.');
  }
}

/**
 * Load a conversation from a deep link URL.
 * Handles conversations that may not be in the initially paginated list.
 * Called BEFORE sync manager starts to prevent false "new messages available" banners.
 */
export async function loadDeepLinkedConversation(conversationId: string): Promise<void> {
  log.info('Loading deep-linked conversation', { conversationId });

  // Track that we're trying to load this conversation
  setPendingConversationId(conversationId);

  // Check if conversation is already in the store (from initial list)
  const existingConv = useStore.getState().conversations.find((c) => c.id === conversationId);
  if (existingConv) {
    await openKnownDeepLinked(conversationId);
  } else {
    await openUnlistedDeepLinked(conversationId);
  }
}

interface DeepLinkViews {
  isPlanner?: boolean;
  isAgents?: boolean;
  isStorage?: boolean;
  isSports?: boolean;
  isLanguage?: boolean;
  isArchive?: boolean;
  isTrash?: boolean;
}

/**
 * Open the special view a hash points at. Returns false when the hash
 * is a plain conversation/home route.
 */
function navigateToViewFromHash(views: DeepLinkViews): boolean {
  if (views.isPlanner) {
    navigateToPlanner();
  } else if (views.isAgents) {
    navigateToAgents();
  } else if (views.isStorage) {
    navigateToStorage();
  } else if (views.isSports) {
    const sportsProgramId = getSportsProgramFromHash();
    if (sportsProgramId) {
      void navigateToSportsProgram(sportsProgramId);
    } else {
      void navigateToSports();
    }
  } else if (views.isArchive) {
    // Back/forward to #/archive
    navigateToArchive();
  } else if (views.isTrash) {
    navigateToTrash();
  } else if (views.isLanguage) {
    const languageProgramId = getLanguageProgramFromHash();
    if (languageProgramId) {
      void navigateToLanguageProgram(languageProgramId);
    } else {
      void navigateToLanguage();
    }
  } else {
    return false;
  }
  return true;
}

/** Leave whichever special view is showing when navigating to a conversation/home. */
function leaveViewsForHashNavigation(): void {
  const store = useStore.getState();
  if (store.isPlannerView) {
    leavePlannerView();
  }
  if (store.isAgentsView) {
    leaveAgentsView();
  }
  if (store.isStorageView) {
    leaveStorageView();
  }
  if (store.isSportsView) {
    leaveSportsView();
  }
  if (store.isLanguageView) {
    leaveLanguageView();
  }
  if (store.isArchiveView) {
    leaveArchiveView();
  }
  if (store.isTrashView) {
    leaveTrashView();
  }
}

/**
 * User navigated to home (no conversation selected): clear the current
 * conversation, but don't navigate away if there's an active request.
 */
function showHomeFromHash(store: ReturnType<typeof useStore.getState>): void {
  const currentConv = store.currentConversation;
  if (currentConv && !store.getActiveRequest(currentConv.id)) {
    store.setCurrentConversation(null);
    renderMessages([]);
    updateChatTitle(APP_NAME);
    setActiveConversation('');
    renderConversationsList();
    if (shouldAutoFocusInput()) {
      focusMessageInput();
    }
  }
}

/**
 * Handle deep link navigation (browser back/forward buttons).
 * This is called when the URL hash changes via browser navigation.
 */
export function handleDeepLinkNavigation(conversationId: string | null, isPlanner?: boolean, isAgents?: boolean, isStorage?: boolean, isSports?: boolean, isLanguage?: boolean, isArchive?: boolean, isTrash?: boolean): void {
  log.debug('Deep link navigation', { conversationId, isPlanner, isAgents, isStorage, isSports, isLanguage });

  if (navigateToViewFromHash({ isPlanner, isAgents, isStorage, isSports, isLanguage, isArchive, isTrash })) {
    return;
  }

  // Navigating away from any special view
  const store = useStore.getState();
  leaveViewsForHashNavigation();

  if (!conversationId) {
    showHomeFromHash(store);
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
