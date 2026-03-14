/**
 * Language learning module.
 * Handles language learning programs navigation, CRUD, and conversation management.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { language } from '../api/client';
import { toast } from '../components/Toast';
import {
  setActiveConversation,
  closeSidebar,
  setLanguageActive,
} from '../components/Sidebar';
import {
  addMessageToUI,
  updateChatTitle,
  hasActiveStreamingContext,
  cleanupStreamingContext,
  cleanupNewerMessagesScrollListener,
  lockOlderQuizBlocks,
} from '../components/messages';
import { renderModelDropdown } from '../components/ModelSelector';
import { checkScrollButtonVisibility } from '../components/ScrollToBottom';
import { getElementById, clearElement } from '../utils/dom';
import {
  clearConversationHash,
  setLanguageHash,
} from '../router/deeplink';
import type { Conversation } from '../types/api';
import {
  createLanguageProgramsElement,
  createLanguageProgramHeader,
  createLanguageLoadingElement,
} from '../components/LanguageDashboard';
import { LANGUAGE_PROGRAMS_CACHE_MS } from '../config';
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

const log = createLogger('language');

// ============================================================================
// Programs List View
// ============================================================================

/**
 * Navigate to the language programs list view.
 * Uses the navigation token pattern for race condition prevention.
 */
export async function navigateToLanguage(forceRefresh: boolean = false): Promise<void> {
  log.info('Navigating to language', { forceRefresh });
  const store = useStore.getState();
  const navToken = store.startNavigation();

  // Clean up UI state
  setCurrentConversationForBlobs('language-loading');
  cleanupNewerMessagesScrollListener();
  if (hasActiveStreamingContext()) {
    cleanupStreamingContext();
  }
  hideNewMessagesAvailableBanner();

  // Update state — atomically clear all other views
  store.setActiveView('language');
  store.setLanguageCurrentProgram(null);

  setActiveConversation(null);
  setLanguageActive(true);
  setLanguageHash();

  // Set placeholder conversation
  const placeholderConv: Conversation = {
    id: 'language-loading',
    title: 'Language Learning',
    model: 'gemini-3-flash-preview',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    messages: [],
  };
  store.setCurrentConversation(placeholderConv);

  updateChatTitle('Language Learning');
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
  messagesContainer.appendChild(createLanguageLoadingElement());
  // Hide input for programs list view
  hideInputArea();
  closeSidebar();

  try {
    const cacheAge = Date.now() - (store.languageProgramsLastFetch || 0);
    const needsRefresh = !store.languagePrograms || cacheAge > LANGUAGE_PROGRAMS_CACHE_MS;

    const programs = await (
      needsRefresh || forceRefresh
        ? language.getPrograms()
        : Promise.resolve(store.languagePrograms!)
    );

    if (!useStore.getState().isNavigationValid(navToken)) {
      log.info('User navigated away from language during load, aborting render', { navToken });
      return;
    }

    if (needsRefresh || forceRefresh) {
      store.setLanguagePrograms(programs);
    }

    // Render programs list
    clearElement(messagesContainer);
    const programsEl = createLanguageProgramsElement(
      programs,
      handleAddProgram,
      handleDeleteProgram,
      handleSelectProgram,
    );
    messagesContainer.appendChild(programsEl);
    messagesContainer.scrollTop = 0;
    checkScrollButtonVisibility();
  } catch (error) {
    log.error('Failed to load language programs', { error });
    clearElement(messagesContainer);
    const errorEl = document.createElement('div');
    errorEl.className = 'language-programs-container';
    errorEl.innerHTML = '<div class="language-empty-state"><p>Failed to load programs. Please try again.</p></div>';
    messagesContainer.appendChild(errorEl);
    toast.error('Failed to load language programs.');
  }
}

// ============================================================================
// Program Chat View
// ============================================================================

/**
 * Navigate to a specific program's chat conversation.
 */
export async function navigateToLanguageProgram(programId: string): Promise<void> {
  log.info('Navigating to language program', { programId });
  const store = useStore.getState();
  const navToken = store.startNavigation();

  store.setActiveView('language');
  store.setLanguageCurrentProgram(programId);
  setLanguageHash(programId);

  // Show input area for chat
  ensureInputAreaVisible();

  const messagesContainer = getElementById<HTMLDivElement>('messages');
  if (!messagesContainer) return;

  clearElement(messagesContainer);
  messagesContainer.appendChild(createLanguageLoadingElement());

  try {
    const convResponse = await language.getConversation(programId);

    if (!useStore.getState().isNavigationValid(navToken)) {
      log.info('User navigated away from language program during load', { navToken });
      return;
    }

    // Find program data (fetch if not cached, e.g. on page reload)
    let programs = store.languagePrograms;
    if (!programs) {
      programs = await language.getPrograms();
      useStore.getState().setLanguagePrograms(programs);
    }
    const program = programs.find(p => p.id === programId);
    const programName = program?.name || 'Language';

    // Set conversation
    const languageConv: Conversation = {
      id: convResponse.id,
      title: programName,
      model: convResponse.model,
      created_at: convResponse.created_at,
      updated_at: convResponse.updated_at,
      messages: [],
    };
    store.setCurrentConversation(languageConv);
    setCurrentConversationForBlobs(convResponse.id);
    updateChatTitle(programName);
    renderModelDropdown();
    updateConversationCost(convResponse.id);

    // Render header + messages
    clearElement(messagesContainer);

    if (program) {
      messagesContainer.classList.add('has-sticky-header');
      const headerEl = createLanguageProgramHeader(
        program,
        () => navigateToLanguage(),
        () => handleProgramReset(programId),
      );
      messagesContainer.appendChild(headerEl);
    }

    if (convResponse.messages.length > 0) {
      convResponse.messages.forEach((msg) => {
        addMessageToUI(msg, messagesContainer);
      });
      lockOlderQuizBlocks(messagesContainer);
      // Scroll to bottom to show latest messages
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    checkScrollButtonVisibility();

    // Trigger proactive first message if conversation is empty
    if (convResponse.messages.length === 0) {
      await triggerLanguageStart(convResponse);
    }

    if (shouldAutoFocusInput()) {
      focusMessageInput();
    }
  } catch (error) {
    log.error('Failed to load language conversation', { error });
    toast.error('Failed to load language conversation.');
  }
}

/**
 * Trigger the first message in an empty language conversation.
 * The LLM decides whether to assess (new learner) or start a lesson (returning learner)
 * based on KV data presence in its system prompt.
 */
async function triggerLanguageStart(convResponse: { id: string; model: string }): Promise<void> {
  log.info('Triggering proactive start for language');
  const store = useStore.getState();

  const languageConv: Conversation = {
    id: convResponse.id,
    title: 'Language',
    model: convResponse.model,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    messages: [],
  };
  store.setCurrentConversation(languageConv);

  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  if (textarea) {
    textarea.value = "Let's start!";
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    await sendMessage();
  }
}

// ============================================================================
// CRUD Operations
// ============================================================================

async function handleAddProgram(data: { name: string; emoji: string }): Promise<void> {
  try {
    await language.createProgram(data);
    toast.success(`Program "${data.name}" created.`);
    const store = useStore.getState();
    store.invalidateLanguageCache();
    await navigateToLanguage(true);
  } catch (error) {
    log.error('Failed to create program', { error });
    toast.error('Failed to create program.');
  }
}

async function handleDeleteProgram(id: string): Promise<void> {
  try {
    await language.deleteProgram(id);
    toast.success('Program deleted.');
    const store = useStore.getState();
    store.invalidateLanguageCache();
    await navigateToLanguage(true);
  } catch (error) {
    log.error('Failed to delete program', { error });
    toast.error('Failed to delete program.');
  }
}

function handleSelectProgram(id: string): void {
  navigateToLanguageProgram(id);
}

async function handleProgramReset(programId: string): Promise<void> {
  try {
    await language.reset(programId);
    toast.success('Language conversation cleared.');
    await navigateToLanguageProgram(programId);
  } catch (error) {
    log.error('Failed to reset language conversation', { error });
    toast.error('Failed to reset conversation.');
  }
}

// ============================================================================
// Leave View
// ============================================================================

/**
 * Leave the language view and return to normal chat.
 */
export function leaveLanguageView(): void {
  log.debug('Leaving language view');
  const store = useStore.getState();

  store.setActiveView('chat');
  store.setLanguageCurrentProgram(null);
  setLanguageActive(false);
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
