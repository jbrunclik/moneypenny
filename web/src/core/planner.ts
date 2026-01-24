/**
 * Planner module.
 * Handles planner navigation and management.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { planner } from '../api/client';
import { toast } from '../components/Toast';
import {
  setActiveConversation,
  closeSidebar,
  setPlannerActive,
} from '../components/Sidebar';
import {
  addMessageToUI,
  updateChatTitle,
  hasActiveStreamingContext,
  cleanupStreamingContext,
  cleanupNewerMessagesScrollListener,
} from '../components/messages';
import { renderModelDropdown } from '../components/ModelSelector';
import { checkScrollButtonVisibility } from '../components/ScrollToBottom';
import { getElementById, clearElement } from '../utils/dom';
import {
  clearConversationHash,
  setPlannerHash,
} from '../router/deeplink';
import type { Conversation } from '../types/api';
import { createDashboardElement, createDashboardLoadingElement } from '../components/PlannerDashboard';
import { PLANNER_DASHBOARD_CACHE_MS } from '../config';
import { setCurrentConversationForBlobs } from '../utils/thumbnails';

import {
  ensureInputAreaVisible,
  focusMessageInput,
  shouldAutoFocusInput,
} from '../components/MessageInput';

import { sendMessage } from './messaging';
import { updateConversationCost, updateAnonymousButtonState } from './toolbar';
import { hideNewMessagesAvailableBanner } from './sync-banner';

const log = createLogger('planner');

/**
 * Navigate to the planner view.
 * The planner reuses the existing messages container and input area.
 * Dashboard is rendered as a special element at the top that scrolls with messages.
 */
/**
 * Navigate to the planner view.
 * The planner reuses the existing messages container and input area.
 * Dashboard is rendered as a special element at the top that scrolls with messages.
 *
 * Uses the navigation token pattern for race condition prevention:
 * 1. Call startNavigation() to get a token before async operations
 * 2. After async completes, check isNavigationValid(token) before rendering
 * 3. If invalid, another navigation started - abort without rendering
 */
export async function navigateToPlanner(forceRefresh: boolean = false): Promise<void> {
  log.info('Navigating to planner', { forceRefresh });
  const store = useStore.getState();

  // Get navigation token to detect if user navigates away during async operations
  // See docs/features/agents.md section "Routing Race Condition Prevention"
  const navToken = store.startNavigation();

  // Clean up UI state from previous conversation (mirrors switchToConversation behavior)
  // This prevents stale state when switching to planner while another conversation is active
  setCurrentConversationForBlobs('planner-loading');
  cleanupNewerMessagesScrollListener();
  if (hasActiveStreamingContext()) {
    cleanupStreamingContext();
  }
  hideNewMessagesAvailableBanner();

  // Update state
  store.setIsPlannerView(true);

  // If coming from agents view, unhide the input area (agents view hides it)
  if (store.isAgentsView) {
    ensureInputAreaVisible();
  }

  store.setIsAgentsView(false); // Ensure agents view is off
  setActiveConversation(null);
  setPlannerActive(true);
  setPlannerHash();

  // Set a placeholder conversation immediately to prevent race condition
  // This will be replaced with the real conversation once loaded
  const placeholderConv: Conversation = {
    id: 'planner-loading',
    title: 'Planner',
    model: 'gemini-3-flash-preview',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    messages: [],
  };
  store.setCurrentConversation(placeholderConv);

  // Update header title and clear stale UI state
  updateChatTitle('Planner');
  renderModelDropdown(); // Update model selector to show planner's model
  updateConversationCost(null); // Clear cost display (planner has no cost yet)

  // Update anonymous button state (planner doesn't use anonymous mode)
  const anonymousBtn = getElementById<HTMLButtonElement>('anonymous-btn');
  if (anonymousBtn) {
    updateAnonymousButtonState(anonymousBtn, false);
  }

  // Get messages container
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (!messagesContainer) {
    log.error('Messages container not found');
    return;
  }

  // Clear messages and show loading state
  clearElement(messagesContainer);
  messagesContainer.appendChild(createDashboardLoadingElement());

  closeSidebar();

  // Load dashboard and conversation in parallel
  try {
    const cacheAge = Date.now() - (store.plannerDashboardLastFetch || 0);
    const needsDashboardRefresh = !store.plannerDashboard || cacheAge > PLANNER_DASHBOARD_CACHE_MS;

    const [dashboard, convResponse] = await Promise.all([
      needsDashboardRefresh ? planner.getDashboard(forceRefresh) : Promise.resolve(store.plannerDashboard!),
      planner.getConversation(),
    ]);

    // Check if user navigated away during the async fetch
    // This prevents a race condition where planner data renders on agents view
    // Uses navigation token pattern - if token changed, another navigation started
    if (!useStore.getState().isNavigationValid(navToken)) {
      log.info('User navigated away from planner during load, aborting render', { navToken });
      return;
    }

    // Update store
    if (needsDashboardRefresh) {
      store.setPlannerDashboard(dashboard);
    }
    store.setPlannerConversation(convResponse);

    // Replace placeholder with real planner conversation
    const plannerConv: Conversation = {
      id: convResponse.id,
      title: 'Planner',
      model: convResponse.model,
      created_at: convResponse.created_at || new Date().toISOString(),
      updated_at: convResponse.updated_at || new Date().toISOString(),
      messages: [],
    };
    store.setCurrentConversation(plannerConv);

    // Update model selector with the actual planner model (may differ from placeholder)
    renderModelDropdown();

    // Clear loading state and render dashboard + messages
    clearElement(messagesContainer);

    // Create dashboard element with refresh and reset callbacks
    const dashboardEl = createDashboardElement(dashboard, handlePlannerRefresh, handlePlannerReset);
    messagesContainer.appendChild(dashboardEl);

    // Render messages after dashboard
    if (convResponse.messages.length > 0) {
      convResponse.messages.forEach((msg) => {
        addMessageToUI(msg, messagesContainer);
      });
    }

    // For planner, scroll to top to show dashboard (different from normal chat)
    messagesContainer.scrollTop = 0;

    // Check scroll button visibility after rendering planner
    checkScrollButtonVisibility();

    // If was_reset is true, the conversation was auto-reset
    if (convResponse.was_reset) {
      toast.info('Planning session has been reset for a new day.');
    }

    // Trigger proactive analysis if conversation is empty
    if (convResponse.messages.length === 0) {
      await triggerProactiveAnalysis(convResponse);
    }

    // Focus input after successful render (respects iOS auto-focus preferences)
    if (shouldAutoFocusInput()) {
      focusMessageInput();
    }
  } catch (error) {
    log.error('Failed to load planner', { error });
    // Show error in the dashboard area
    clearElement(messagesContainer);
    const errorEl = document.createElement('div');
    errorEl.className = 'planner-dashboard-message';
    errorEl.innerHTML = `
      <div class="dashboard-error">
        <strong>Error:</strong> Failed to load your schedule. Please try again.
      </div>
    `;
    messagesContainer.appendChild(errorEl);
    toast.error('Failed to load planner.');
  }
}

/**
 * Trigger proactive analysis for the planner.
 * This sends an automatic first message to get LLM insights on the user's schedule.
 */
async function triggerProactiveAnalysis(convResponse: { id: string; model: string }): Promise<void> {
  log.info('Triggering proactive analysis for planner');
  const store = useStore.getState();

  // Set the planner conversation as current so sendMessage uses it
  const plannerConv: Conversation = {
    id: convResponse.id,
    title: 'Planner',
    model: convResponse.model,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    messages: [],
  };
  store.setCurrentConversation(plannerConv);

  // Create a synthetic user message for proactive analysis
  const proactiveMessage = 'Start my planning session';

  // Add the message to the textarea and send it
  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  if (textarea) {
    textarea.value = proactiveMessage;
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    await sendMessage();
  }
}

/**
 * Handle refresh button click in planner dashboard.
 */
async function handlePlannerRefresh(): Promise<void> {
  log.debug('Planner refresh clicked');
  const store = useStore.getState();

  // Invalidate frontend cache and re-navigate with force refresh
  store.invalidatePlannerCache();
  await navigateToPlanner(true); // Force backend to bypass cache too
}

/**
 * Leave the planner view and return to normal chat.
 */
export function leavePlannerView(): void {
  log.debug('Leaving planner view');
  const store = useStore.getState();

  store.setIsPlannerView(false);
  setPlannerActive(false);

  // Clear the planner hash
  clearConversationHash();

  // Clear current conversation (was planner)
  store.setCurrentConversation(null);

  // Reset the header title
  updateChatTitle('AI Chatbot');

  // Clear stale UI state from planner
  renderModelDropdown(); // Reset to default model display
  updateConversationCost(null); // Clear cost display

  // Update anonymous button state (reset to pending state)
  const anonymousBtn = getElementById<HTMLButtonElement>('anonymous-btn');
  if (anonymousBtn) {
    updateAnonymousButtonState(anonymousBtn, store.pendingAnonymousMode);
  }

  // Clear messages to show welcome state
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (messagesContainer) {
    messagesContainer.innerHTML = `
      <div class="welcome-message">
        <h2>Welcome to AI Chatbot</h2>
        <p>Start a conversation with Gemini AI</p>
      </div>
    `;
  }

  // Ensure input area is visible and focus input after leaving planner
  ensureInputAreaVisible();
  if (shouldAutoFocusInput()) {
    focusMessageInput();
  }
}

/**
 * Reset the planner conversation (clear all messages) and trigger fresh analysis.
 * Called when user clicks the reset button in the dashboard header.
 */
async function handlePlannerReset(): Promise<void> {
  const store = useStore.getState();

  try {
    // Reset conversation on server
    await planner.reset();

    // Clear the stored planner conversation
    store.setPlannerConversation(null);

    // Invalidate dashboard cache
    store.invalidatePlannerCache();

    toast.success('Planning session cleared.');

    // Re-navigate to planner (will fetch fresh data and trigger proactive analysis)
    await navigateToPlanner();
  } catch (error) {
    log.error('Failed to reset planner', { error });
    toast.error('Failed to clear planning session.');
  }
}
