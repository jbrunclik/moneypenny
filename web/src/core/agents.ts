/**
 * Agents module.
 * Handles agents navigation and command center management.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { agents } from '../api/client';
import { toast } from '../components/Toast';
import {
  setActiveConversation,
  closeSidebar,
  setAgentsActive,
  renderConversationsList,
} from '../components/Sidebar';
import {
  updateChatTitle,
  hasActiveStreamingContext,
  cleanupStreamingContext,
  cleanupNewerMessagesScrollListener,
} from '../components/messages';
import { renderModelDropdown } from '../components/ModelSelector';
import { getElementById, clearElement } from '../utils/dom';
import { WARNING_ICON } from '../utils/icons';
import {
  clearConversationHash,
  setAgentsHash,
} from '../router/deeplink';
import { setCurrentConversationForBlobs } from '../utils/thumbnails';
import { renderCommandCenter, renderCommandCenterLoading } from '../components/CommandCenter';
import { initAgentEditor, showAgentEditor } from '../components/AgentEditor';
import {
  ensureInputAreaVisible,
  focusMessageInput,
  shouldAutoFocusInput,
} from '../components/MessageInput';
import type { Agent } from '../types/api';

import { updateConversationCost, updateAnonymousButtonState } from './toolbar';
import { hideNewMessagesAvailableBanner } from './sync-banner';
import { COMMAND_CENTER_CACHE_MS } from '../config';

const log = createLogger('agents');

/**
 * Flag to prevent concurrent refresh operations.
 * Ensures only one refresh can be in progress at a time.
 */
let isRefreshing = false;

/**
 * Initialize the agents module.
 * Call this once during app initialization.
 */
export function initAgents(): void {
  initAgentEditor();

  // Subscribe to command center data changes to update sidebar badges
  useStore.subscribe(
    (state) => ({ unread: state.commandCenterData?.total_unread, waiting: state.commandCenterData?.agents_waiting }),
    () => {
      // Re-render sidebar when badge counts change
      renderConversationsList();
    },
    { equalityFn: (a, b) => a?.unread === b?.unread && a?.waiting === b?.waiting }
  );
}

/**
 * Navigate to the agents command center.
 * The command center is rendered in the messages container.
 */
/**
 * Navigate to the agents command center.
 * The command center is rendered in the messages container.
 *
 * Uses the navigation token pattern for race condition prevention:
 * 1. Call startNavigation() to get a token before async operations
 * 2. After async completes, check isNavigationValid(token) before rendering
 * 3. If invalid, another navigation started - abort without rendering
 */
export async function navigateToAgents(forceRefresh: boolean = false): Promise<void> {
  log.info('Navigating to agents', { forceRefresh });
  const store = useStore.getState();

  // Get navigation token to detect if user navigates away during async operations
  // See docs/features/agents.md section "Routing Race Condition Prevention"
  const navToken = store.startNavigation();

  // Clean up UI state from previous conversation
  setCurrentConversationForBlobs('agents-loading');
  cleanupNewerMessagesScrollListener();
  if (hasActiveStreamingContext()) {
    cleanupStreamingContext();
  }
  hideNewMessagesAvailableBanner();

  // Update state
  store.setIsAgentsView(true);
  store.setIsPlannerView(false); // Ensure planner view is off
  setActiveConversation(null);
  setAgentsActive(true);
  setAgentsHash();

  // Clear current conversation
  store.setCurrentConversation(null);

  // Update header title and clear stale UI state
  updateChatTitle('Command Center');
  renderModelDropdown(); // Update model selector (will show default since no conversation)
  updateConversationCost(null); // Clear cost display

  // Update anonymous button state (agents view doesn't use anonymous mode)
  const anonymousBtn = getElementById<HTMLButtonElement>('anonymous-btn');
  if (anonymousBtn) {
    updateAnonymousButtonState(anonymousBtn, false);
  }

  // Hide input area and scroll button (agents view is not a chat)
  const inputArea = document.querySelector<HTMLDivElement>('.input-area');
  if (inputArea) {
    inputArea.classList.add('hidden');
  }
  const scrollToBottomBtn = document.querySelector<HTMLButtonElement>('.scroll-to-bottom');
  if (scrollToBottomBtn) {
    scrollToBottomBtn.classList.add('hidden');
  }

  // Get messages container
  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (!messagesContainer) {
    log.error('Messages container not found');
    return;
  }

  // Clear messages and show loading state
  clearElement(messagesContainer);
  messagesContainer.appendChild(renderCommandCenterLoading());

  closeSidebar();

  // Load command center data
  const cacheAge = Date.now() - (store.commandCenterLastFetch || 0);
  const needsRefresh = !store.commandCenterData || cacheAge > COMMAND_CENTER_CACHE_MS || forceRefresh;

  let commandCenterData = store.commandCenterData;
  let fetchFailed = false;

  if (needsRefresh) {
    try {
      commandCenterData = await agents.getCommandCenter();
      store.setCommandCenterData(commandCenterData);
    } catch (error) {
      log.error('Failed to fetch command center data', { error });
      fetchFailed = true;
      // Keep using cached data if available
    }
  }

  // Check if user navigated away during the async fetch
  // This prevents a race condition where agents data renders on planner view
  // Uses navigation token pattern - if token changed, another navigation started
  if (!useStore.getState().isNavigationValid(navToken)) {
    log.info('User navigated away from agents during load, aborting render', { navToken });
    return;
  }

  // Clear loading state
  clearElement(messagesContainer);

  if (!commandCenterData) {
    // No cached data and fetch failed (or never fetched)
    const errorEl = document.createElement('div');
    errorEl.className = 'command-center-error';
    errorEl.innerHTML = `
      <div class="error-message">
        <strong>Error:</strong> Failed to load agents. Please try again.
      </div>
    `;
    messagesContainer.appendChild(errorEl);
    toast.error('Failed to load agents.');
    return;
  }

  // Render command center (with stale warning if fetch failed)
  const commandCenterEl = renderCommandCenter(
    commandCenterData,
    handleAgentsRefresh,
    handleApproval,
    handleAgentSelect,
    handleAgentRun,
    handleAgentEdit,
    handleNewAgent,
  );

  // Add stale data warning banner if fetch failed but we have cached data
  if (fetchFailed) {
    const warningBanner = document.createElement('div');
    warningBanner.className = 'command-center-stale-warning';
    warningBanner.innerHTML = `
      <span class="warning-icon">${WARNING_ICON}</span>
      <span>Unable to refresh. Showing cached data.</span>
      <button class="btn-retry">Retry</button>
    `;
    warningBanner.querySelector('.btn-retry')?.addEventListener('click', () => {
      navigateToAgents(true);
    });
    // Insert warning at the beginning of the command center
    commandCenterEl.insertBefore(warningBanner, commandCenterEl.firstChild);
    toast.warning('Showing cached data - could not refresh.');
  }

  messagesContainer.appendChild(commandCenterEl);

  // Scroll to top
  messagesContainer.scrollTop = 0;
}

/**
 * Handle refresh button click in command center.
 * Prevents concurrent refresh operations to avoid race conditions.
 */
async function handleAgentsRefresh(): Promise<void> {
  // Prevent concurrent refreshes
  if (isRefreshing) {
    log.debug('Refresh skipped - already in progress');
    return;
  }

  log.debug('Agents refresh clicked');
  isRefreshing = true;

  try {
    const store = useStore.getState();
    store.invalidateCommandCenterCache();
    await navigateToAgents(true);
  } finally {
    isRefreshing = false;
  }
}

/**
 * Handle approval decision (approve or reject).
 */
async function handleApproval(approvalId: string, approved: boolean): Promise<void> {
  log.debug('Approval decision', { approvalId, approved });

  try {
    if (approved) {
      await agents.approveRequest(approvalId);
      toast.success('Request approved.');
    } else {
      await agents.rejectRequest(approvalId);
      toast.info('Request rejected.');
    }

    // Refresh command center
    await navigateToAgents(true);

    // Also refresh sidebar to update badges
    renderConversationsList();
  } catch (error) {
    log.error('Failed to process approval', { error });
    toast.error('Failed to process approval.');
  }
}

/**
 * Handle agent selection (navigate to agent's conversation).
 */
async function handleAgentSelect(agentId: string): Promise<void> {
  log.debug('Agent selected', { agentId });

  try {
    const agent = await agents.get(agentId);
    if (agent.conversation_id) {
      // Import selectConversation to navigate to the agent's conversation
      const { selectConversation } = await import('./conversation');
      await selectConversation(agent.conversation_id);
    } else {
      toast.error('Agent has no conversation.');
    }
  } catch (error) {
    log.error('Failed to select agent', { error });
    toast.error('Failed to load agent conversation.');
  }
}

/**
 * Handle manual agent run trigger.
 * Shows immediate feedback and runs the agent.
 */
async function handleAgentRun(agentId: string, agentName: string): Promise<void> {
  log.debug('Agent run triggered', { agentId, agentName });

  // Show immediate loading feedback with agent name
  const loadingToast = toast.loading(`Running "${agentName}"...`);

  try {
    const result = await agents.run(agentId);

    // Dismiss loading toast and show success
    loadingToast.dismiss();
    toast.success(result.message || 'Agent completed.');

    // Refresh command center
    await navigateToAgents(true);
  } catch (error) {
    log.error('Failed to run agent', { error });

    // Dismiss loading toast and show error
    loadingToast.dismiss();
    toast.error('Failed to run agent.');
  }
}

/**
 * Handle new agent creation.
 * Opens the agent editor modal to create a new agent.
 */
async function handleNewAgent(): Promise<void> {
  log.debug('New agent button clicked');

  const result = await showAgentEditor();
  if (result) {
    log.info('Agent created', { agentId: result.id });
    // Refresh command center to show the new agent
    await navigateToAgents(true);
    renderConversationsList();
  }
}

/**
 * Handle agent edit.
 * Opens the agent editor modal with existing agent data.
 */
async function handleAgentEdit(agent: Agent): Promise<void> {
  log.debug('Edit agent clicked', { agentId: agent.id });

  // Fetch full agent details including system_prompt
  try {
    const fullAgent = await agents.get(agent.id);
    const result = await showAgentEditor(fullAgent);
    if (result) {
      log.info('Agent updated', { agentId: result.id });
      // Refresh command center to show the updated agent
      await navigateToAgents(true);
      renderConversationsList();
    }
  } catch (error) {
    log.error('Failed to load agent for editing', { error });
    toast.error('Failed to load agent.');
  }
}

/**
 * Leave the agents view and return to normal chat.
 * @param clearMessages - Whether to clear messages and show welcome state (default: true)
 *                        Pass false when navigating to a specific conversation.
 */
export function leaveAgentsView(clearMessages: boolean = true): void {
  log.debug('Leaving agents view', { clearMessages });
  const store = useStore.getState();

  store.setIsAgentsView(false);
  setAgentsActive(false);

  // Show input area and scroll button (were hidden in agents view)
  ensureInputAreaVisible();

  // Update anonymous button state
  const anonymousBtn = getElementById<HTMLButtonElement>('anonymous-btn');
  if (anonymousBtn) {
    updateAnonymousButtonState(anonymousBtn, store.pendingAnonymousMode);
  }

  // Only clear UI state if not navigating to a conversation
  if (clearMessages) {
    // Clear the agents hash
    clearConversationHash();

    // Clear current conversation (was in agents view)
    store.setCurrentConversation(null);

    // Reset the header title
    updateChatTitle('AI Chatbot');

    // Clear stale UI state
    renderModelDropdown();
    updateConversationCost(null);

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

    // Focus input after leaving agents view (respects iOS auto-focus preferences)
    if (shouldAutoFocusInput()) {
      focusMessageInput();
    }
  }
}
