/**
 * Switching the main area to a conversation: tear down the previous
 * conversation's listeners/streaming UI, render the new one, restore any
 * in-flight request, and refresh composer/toolbar/sidebar state.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { resumeInflightStreamIfAny } from './stream-resume';
import { resumeInflightBatchIfAny } from './batch-resume';
import { renderConversationsList, setActiveConversation, closeSidebar } from '../components/Sidebar';
import {
  renderMessages,
  updateChatTitle,
  setupOlderMessagesScrollListener,
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
  restoreDraftForConversation,
  shouldAutoFocusInput,
} from '../components/MessageInput';
import { renderModelDropdown } from '../components/ModelSelector';
import { getElementById } from '../utils/dom';
import { enableScrollOnImageLoad, setCurrentConversationForBlobs } from '../utils/thumbnails';
import { setConversationHash } from '../router/deeplink';
import type { Conversation } from '../types/api';
import { getSyncManager } from '../sync/SyncManager';
import { renderAgentConversationHeader } from '../components/AgentConversationHeader';
import { renderChatHeader } from '../components/ChatHeader';
import { isTempConversation } from './conversation';
import { renderChatHeaderForConversation } from './conversation-header';
import { updateConversationCost, updateAnonymousButtonState } from './toolbar';
import { hideNewMessagesAvailableBanner } from './sync-banner';
import { navigateToAgents, handleAgentEditById } from './agents';

const log = createLogger('conversation');

/** Look up agent name from command center data in the store. */
function getAgentNameById(agentId: string): string | null {
  const { commandCenterData } = useStore.getState();
  if (!commandCenterData) return null;
  const agent = commandCenterData.agents.find(a => a.id === agentId);
  return agent?.name ?? null;
}

/**
 * Clean up per-conversation listeners and streaming UI left over from the
 * previously shown conversation.
 */
function cleanupPreviousConversation(convId: string): void {
  // Clean up blob URLs from the previous conversation to prevent memory leaks
  // This must happen before we set the new conversation ID
  setCurrentConversationForBlobs(convId);

  // Clean up newer messages scroll listener from previous conversation
  // This must happen before setting up listeners for the new conversation
  cleanupNewerMessagesScrollListener();

  // Clean up streaming context only if switching to a DIFFERENT conversation
  // If switching back to the streaming conversation, we want to restore the UI state instead
  const streamingConvId = getStreamingContextConversationId();
  if (hasActiveStreamingContext() && streamingConvId !== convId) {
    log.debug('Cleaning up streaming context from different conversation', {
      streamingConvId,
      targetConvId: convId
    });
    cleanupStreamingContext();
  }
}

/**
 * Agent conversations use the shared chat header with back/edit actions.
 */
function renderAgentHeaderIfAgent(conv: Conversation): void {
  if (!conv.is_agent || !conv.agent_id) return;
  const agentName = getAgentNameById(conv.agent_id) || conv.title;
  renderAgentConversationHeader(
    agentName,
    () => {
      navigateToAgents();
    },
    () => {
      if (conv.agent_id) {
        handleAgentEditById(conv.agent_id!);
      }
    },
  );
}

/**
 * Check if there's an active request for this conversation and restore UI state
 */
function restoreActiveRequestUi(convId: string): void {
  const activeRequest = useStore.getState().getActiveRequest(convId);
  if (!activeRequest) return;
  log.debug('Restoring active request UI', { conversationId: convId, type: activeRequest.type });
  if (activeRequest.type === 'stream') {
    // Restore streaming message UI with accumulated content
    // The element is tracked in Messages.ts via currentStreamingContext
    restoreStreamingMessage(
      convId,
      activeRequest.content || '',
      activeRequest.thinkingState
    );
  } else if (activeRequest.type === 'batch') {
    // Show loading indicator for batch requests
    showLoadingIndicator();
  }
}

/**
 * Composer, toolbar and sidebar state after the conversation is shown.
 */
function refreshChromeAfterSwitch(conv: Conversation, totalMessageCount?: number): void {
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
    updateAnonymousButtonState(anonymousBtn, useStore.getState().getAnonymousMode(conv.id));
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
 * Switch to a conversation and update UI.
 */
export function switchToConversation(conv: Conversation, totalMessageCount?: number): void {
  log.debug('Switching to conversation', { conversationId: conv.id, title: conv.title, totalMessageCount });
  cleanupPreviousConversation(conv.id);

  useStore.getState().setCurrentConversation(conv);
  setActiveConversation(conv.id);
  updateChatTitle(conv.title);

  // Regular conversations get the shared chat header; agent conversations
  // keep their sticky in-messages header (hide the regular one)
  if (conv.is_agent) {
    renderChatHeader(null);
  } else {
    renderChatHeaderForConversation(conv);
  }

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

  // Restore this conversation's composer draft (typed text survives switches)
  restoreDraftForConversation(conv.id);

  renderAgentHeaderIfAgent(conv);

  // Set up scroll listener for loading older messages (if not a temp conversation)
  if (!isTempConversation(conv.id)) {
    setupOlderMessagesScrollListener(conv.id);
  }

  restoreActiveRequestUi(conv.id);

  // If the page died mid-stream in this conversation, resume from the journal.
  // MUST run after the active-request restore above: the resume registers an
  // active request of its own, and running first would make the restore path
  // immediately re-create a competing bubble for it (the resume bails out when
  // an active request already exists, so the two paths are mutually exclusive).
  void resumeInflightStreamIfAny(conv.id);
  // Same for a batch turn: wait for its reply instead of showing none
  void resumeInflightBatchIfAny(conv.id, conv.messages || []);

  refreshChromeAfterSwitch(conv, totalMessageCount);
}
