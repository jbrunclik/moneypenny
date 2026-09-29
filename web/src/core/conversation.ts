/**
 * Conversation selection: temp IDs, the pending-load race guard, and
 * selecting/creating conversations. Rendering a switch lives in
 * conversation-switch.ts, CRUD actions in conversation-actions.ts, archive
 * in archive.ts, deep links in conversation-deeplink.ts, the chat header
 * in conversation-header.ts.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { agents } from '../api/agents';
import { conversations } from '../api/conversations';
import { toast } from '../components/Toast';
import { reconcileOutboxWithServer } from './outbox';
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
  cleanupOlderMessagesScrollListener,
  cleanupNewerMessagesScrollListener,
} from '../components/messages';
import {
  focusMessageInput,
  ensureInputAreaVisible,
  restoreDraftForConversation,
  shouldAutoFocusInput,
} from '../components/MessageInput';
import { renderModelDropdown } from '../components/ModelSelector';
import { getElementById } from '../utils/dom';
import { setCurrentConversationForBlobs } from '../utils/thumbnails';
import { pushEmptyHash } from '../router/deeplink';
import { DEFAULT_CONVERSATION_TITLE } from '../types/api';
import type { Conversation, ConversationDetailResponse, Message } from '../types/api';
import { getSyncManager } from '../sync/SyncManager';
import { revealHeader } from './header-autohide';
import { renderChatHeaderForConversation } from './conversation-header';
import { switchToConversation } from './conversation-switch';
import { updateConversationCost, updateAnonymousButtonState } from './toolbar';
import { leaveStorageView } from './kv-store';
import { leaveSportsView } from './sports';
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
 * Find an existing empty, untitled, non-archived, non-agent conversation
 * that New Chat can reuse instead of creating another one.
 */
export function findReusableEmptyConversation(
  conversationList: Conversation[],
): Conversation | null {
  return (
    conversationList.find((c) => {
      if (c.title !== DEFAULT_CONVERSATION_TITLE || c.archived || c.is_agent) return false;
      const isEmpty =
        c.messageCount === 0 || (c.messageCount === undefined && c.messages?.length === 0);
      return isEmpty;
    }) ?? null
  );
}

/**
 * Build the store's Conversation from a detail response, with the
 * outbox-reconciled message list.
 */
export function toConversation(
  response: ConversationDetailResponse,
  mergedMessages: Message[],
): Conversation {
  return {
    id: response.id,
    title: response.title,
    model: response.model,
    created_at: response.created_at,
    updated_at: response.updated_at,
    messages: mergedMessages,
    is_agent: response.is_agent,
    agent_id: response.agent_id,
    has_pending_approval: response.has_pending_approval,
    archived: response.archived,
  };
}

/**
 * Mark an agent's messages as viewed on the server and refresh the
 * command center so unread badges clear. Fire-and-forget: reading the
 * conversation must never block on this.
 */
export function markAgentViewedAndRefresh(agentId: string): void {
  agents.markViewed(agentId)
    .then(() => agents.getCommandCenter())
    .then((data) => {
      useStore.getState().setCommandCenterData(data);
    })
    .catch((err) => {
      log.warn('Failed to mark agent as viewed', { agentId, error: err });
    });
}

/**
 * Agent bookkeeping shared by every path that opens a conversation
 * (selectConversation AND the deep-link loader used by push-notification
 * taps): track the agent for sync and reset the server-side unread state.
 * Skipping this on any open path leaves last_viewed_at stale, so the
 * unread badge persists on every device.
 */
export function trackViewedAgentConversation(
  response: { is_agent?: boolean; agent_id?: string | null; message_pagination: { total_count: number } }
): void {
  if (response.is_agent && response.agent_id) {
    getSyncManager()?.setViewedAgent(response.agent_id, response.message_pagination.total_count);
    markAgentViewedAndRefresh(response.agent_id);
  } else {
    getSyncManager()?.setViewedAgent(null);
  }
}

/**
 * Leave any special view (planner, agents, storage, sports) before a
 * conversation takes over the main area.
 */
function leaveSpecialViewsForChat(): void {
  const store = useStore.getState();
  if (store.isPlannerView) {
    setPlannerActive(false);
  }
  if (store.isAgentsView) {
    leaveAgentsView(false);
  }
  if (store.isStorageView) {
    leaveStorageView(false);
  }
  if (store.isSportsView) {
    leaveSportsView();
  }
  store.setActiveView('chat');
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

  // A new conversation always opens with the header visible (it may have been
  // auto-hidden by scrolling in the previous one).
  revealHeader();

  // Get navigation token to detect if user navigates to planner/agents during load
  // This supplements pendingConversationId which only tracks conversation-to-conversation
  // See docs/features/agents.md section "Routing Race Condition Prevention"
  const navToken = store.startNavigation();

  // Leave any special view before switching to a conversation
  leaveSpecialViewsForChat();

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
    showLoadedConversation(convId, response);
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

/** Store a freshly fetched conversation and switch to it. */
function showLoadedConversation(convId: string, response: ConversationDetailResponse): void {
  const store = useStore.getState();

  // Merge in unconfirmed outbox sends (pending/failed) before storing:
  // this is what makes a lost send reappear with a retry affordance
  const mergedMessages = reconcileOutboxWithServer(convId, response.messages);

  // Store messages and pagination in the per-conversation Maps
  store.setMessages(convId, mergedMessages, response.message_pagination);

  // Anonymous mode is persisted server-side; adopt it so a reload does not
  // silently drop the conversation back to memory-enabled.
  if (response.anonymous_mode) {
    store.setAnonymousMode(convId, true);
  }

  // Mark agent conversation as viewed to reset unread count
  // Also track the agent for sync purposes
  trackViewedAgentConversation(response);

  // Pass total message count from pagination for correct sync behavior
  switchToConversation(toConversation(response, mergedMessages), response.message_pagination.total_count);
}

/**
 * Reuse an existing empty conversation instead of piling up untitled ones.
 * Returns true when one was found (and selected unless already shown).
 */
function reuseEmptyConversation(): boolean {
  const store = useStore.getState();
  const reusable = findReusableEmptyConversation(store.conversations);
  if (!reusable) return false;
  const inSpecialView =
    store.isPlannerView ||
    store.isAgentsView ||
    store.isStorageView ||
    store.isSportsView ||
    store.isLanguageView;
  const alreadyViewingIt = store.currentConversation?.id === reusable.id && !inSpecialView;
  if (!alreadyViewingIt) {
    void selectConversation(reusable.id);
  }
  return true;
}

/** Add a local-only conversation with a temp ID and make it current. */
function addTempConversation(): { conv: Conversation; pendingAnonymous: boolean } {
  const store = useStore.getState();
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
  return { conv, pendingAnonymous };
}

/**
 * Create a new conversation (local only - saved to DB on first message).
 */
export function createConversation(): void {
  log.debug('Creating new conversation');

  if (reuseEmptyConversation()) return;

  // Leave any special view before creating new conversation
  leaveSpecialViewsForChat();

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

  const { conv, pendingAnonymous } = addTempConversation();

  renderConversationsList();
  setActiveConversation(conv.id);
  updateChatTitle(conv.title);
  renderChatHeaderForConversation(conv);
  renderMessages([]);
  renderModelDropdown();
  closeSidebar();

  // Fresh conversation, fresh (empty) composer draft
  restoreDraftForConversation(conv.id);

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
