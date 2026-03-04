/**
 * Sports module.
 * Handles sports training programs navigation, CRUD, and conversation management.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { sports } from '../api/client';
import { toast } from '../components/Toast';
import {
  setActiveConversation,
  closeSidebar,
  setSportsActive,
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
  setSportsHash,
} from '../router/deeplink';
import type { Conversation } from '../types/api';
import {
  createSportsProgramsElement,
  createSportsProgramHeader,
  createSportsLoadingElement,
} from '../components/SportsDashboard';
import { SPORTS_PROGRAMS_CACHE_MS } from '../config';
import { setCurrentConversationForBlobs } from '../utils/thumbnails';
import {
  ensureInputAreaVisible,
  hideInputArea,
  focusMessageInput,
  shouldAutoFocusInput,
} from '../components/MessageInput';
import { sendMessage } from './messaging';
import { updateConversationCost, updateAnonymousButtonState } from './toolbar';
import { hideNewMessagesAvailableBanner } from './sync-banner';

const log = createLogger('sports');

// ============================================================================
// Programs List View
// ============================================================================

/**
 * Navigate to the sports programs list view.
 * Uses the navigation token pattern for race condition prevention.
 */
export async function navigateToSports(forceRefresh: boolean = false): Promise<void> {
  log.info('Navigating to sports', { forceRefresh });
  const store = useStore.getState();
  const navToken = store.startNavigation();

  // Clean up UI state
  setCurrentConversationForBlobs('sports-loading');
  cleanupNewerMessagesScrollListener();
  if (hasActiveStreamingContext()) {
    cleanupStreamingContext();
  }
  hideNewMessagesAvailableBanner();

  // Update state — atomically clear all other views
  store.setActiveView('sports');
  store.setSportsCurrentProgram(null);

  setActiveConversation(null);
  setSportsActive(true);
  setSportsHash();

  // Set placeholder conversation
  const placeholderConv: Conversation = {
    id: 'sports-loading',
    title: 'Sports Training',
    model: 'gemini-3-flash-preview',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    messages: [],
  };
  store.setCurrentConversation(placeholderConv);

  updateChatTitle('Sports Training');
  renderModelDropdown();
  updateConversationCost(null);

  const anonymousBtn = getElementById<HTMLButtonElement>('anonymous-btn');
  if (anonymousBtn) {
    updateAnonymousButtonState(anonymousBtn, false);
  }

  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (!messagesContainer) {
    log.error('Messages container not found');
    return;
  }

  // Show loading
  clearElement(messagesContainer);
  messagesContainer.appendChild(createSportsLoadingElement());
  // Hide input for programs list view
  hideInputArea();
  closeSidebar();

  try {
    const cacheAge = Date.now() - (store.sportsProgramsLastFetch || 0);
    const needsRefresh = !store.sportsPrograms || cacheAge > SPORTS_PROGRAMS_CACHE_MS;

    const programs = await (
      needsRefresh || forceRefresh
        ? sports.getPrograms()
        : Promise.resolve(store.sportsPrograms!)
    );

    if (!useStore.getState().isNavigationValid(navToken)) {
      log.info('User navigated away from sports during load, aborting render', { navToken });
      return;
    }

    if (needsRefresh || forceRefresh) {
      store.setSportsPrograms(programs);
    }

    // Render programs list
    clearElement(messagesContainer);
    const programsEl = createSportsProgramsElement(
      programs,
      handleAddProgram,
      handleDeleteProgram,
      handleSelectProgram,
    );
    messagesContainer.appendChild(programsEl);
    messagesContainer.scrollTop = 0;
    checkScrollButtonVisibility();
  } catch (error) {
    log.error('Failed to load sports programs', { error });
    clearElement(messagesContainer);
    const errorEl = document.createElement('div');
    errorEl.className = 'sports-programs-container';
    errorEl.innerHTML = '<div class="sports-empty-state"><p>Failed to load programs. Please try again.</p></div>';
    messagesContainer.appendChild(errorEl);
    toast.error('Failed to load sports programs.');
  }
}

// ============================================================================
// Program Chat View
// ============================================================================

/**
 * Navigate to a specific program's chat conversation.
 */
export async function navigateToSportsProgram(programId: string): Promise<void> {
  log.info('Navigating to sports program', { programId });
  const store = useStore.getState();
  const navToken = store.startNavigation();

  store.setActiveView('sports');
  store.setSportsCurrentProgram(programId);
  setSportsHash(programId);

  // Show input area for chat
  ensureInputAreaVisible();

  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (!messagesContainer) return;

  clearElement(messagesContainer);
  messagesContainer.appendChild(createSportsLoadingElement());

  try {
    const convResponse = await sports.getConversation(programId);

    if (!useStore.getState().isNavigationValid(navToken)) {
      log.info('User navigated away from sports program during load', { navToken });
      return;
    }

    // Find program data (fetch if not cached, e.g. on page reload)
    let programs = store.sportsPrograms;
    if (!programs) {
      programs = await sports.getPrograms();
      useStore.getState().setSportsPrograms(programs);
    }
    const program = programs.find(p => p.id === programId);
    const programName = program?.name || 'Training';

    // Set conversation
    const sportsConv: Conversation = {
      id: convResponse.id,
      title: programName,
      model: convResponse.model,
      created_at: convResponse.created_at,
      updated_at: convResponse.updated_at,
      messages: [],
    };
    store.setCurrentConversation(sportsConv);
    setCurrentConversationForBlobs(convResponse.id);
    updateChatTitle(programName);
    renderModelDropdown();
    updateConversationCost(convResponse.id);

    // Render header + messages
    clearElement(messagesContainer);

    if (program) {
      messagesContainer.classList.add('has-sticky-header');
      const headerEl = createSportsProgramHeader(
        program,
        () => navigateToSports(),
        () => handleProgramReset(programId),
      );
      messagesContainer.appendChild(headerEl);
    }

    if (convResponse.messages.length > 0) {
      convResponse.messages.forEach((msg) => {
        addMessageToUI(msg, messagesContainer);
      });
      // Scroll to bottom to show latest messages
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    checkScrollButtonVisibility();

    // Trigger proactive first message if conversation is empty
    if (convResponse.messages.length === 0) {
      await triggerSportsAnalysis(convResponse);
    }

    if (shouldAutoFocusInput()) {
      focusMessageInput();
    }
  } catch (error) {
    log.error('Failed to load sports conversation', { error });
    toast.error('Failed to load training conversation.');
  }
}

/**
 * Trigger initial training session analysis.
 */
async function triggerSportsAnalysis(convResponse: { id: string; model: string }): Promise<void> {
  log.info('Triggering proactive analysis for sports');
  const store = useStore.getState();

  const sportsConv: Conversation = {
    id: convResponse.id,
    title: 'Training',
    model: convResponse.model,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    messages: [],
  };
  store.setCurrentConversation(sportsConv);

  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  if (textarea) {
    textarea.value = 'Start my training session';
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    await sendMessage();
  }
}

// ============================================================================
// CRUD Operations
// ============================================================================

async function handleAddProgram(data: { name: string; emoji: string }): Promise<void> {
  try {
    await sports.createProgram(data);
    toast.success(`Program "${data.name}" created.`);
    const store = useStore.getState();
    store.invalidateSportsCache();
    await navigateToSports(true);
  } catch (error) {
    log.error('Failed to create program', { error });
    toast.error('Failed to create program.');
  }
}

async function handleDeleteProgram(id: string): Promise<void> {
  try {
    await sports.deleteProgram(id);
    toast.success('Program deleted.');
    const store = useStore.getState();
    store.invalidateSportsCache();
    await navigateToSports(true);
  } catch (error) {
    log.error('Failed to delete program', { error });
    toast.error('Failed to delete program.');
  }
}

function handleSelectProgram(id: string): void {
  navigateToSportsProgram(id);
}

async function handleProgramReset(programId: string): Promise<void> {
  try {
    await sports.reset(programId);
    toast.success('Training conversation cleared.');
    await navigateToSportsProgram(programId);
  } catch (error) {
    log.error('Failed to reset sports conversation', { error });
    toast.error('Failed to reset conversation.');
  }
}

// ============================================================================
// Leave View
// ============================================================================

/**
 * Leave the sports view and return to normal chat.
 */
export function leaveSportsView(): void {
  log.debug('Leaving sports view');
  const store = useStore.getState();

  store.setActiveView('chat');
  store.setSportsCurrentProgram(null);
  setSportsActive(false);
  clearConversationHash();
  store.setCurrentConversation(null);

  updateChatTitle('AI Chatbot');
  renderModelDropdown();
  updateConversationCost(null);

  const anonymousBtn = getElementById<HTMLButtonElement>('anonymous-btn');
  if (anonymousBtn) {
    updateAnonymousButtonState(anonymousBtn, store.pendingAnonymousMode);
  }

  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (messagesContainer) {
    messagesContainer.innerHTML = `
      <div class="welcome-message">
        <h2>Welcome to AI Chatbot</h2>
        <p>Start a conversation with Gemini AI</p>
      </div>
    `;
  }

  ensureInputAreaVisible();
  if (shouldAutoFocusInput()) {
    focusMessageInput();
  }
}
