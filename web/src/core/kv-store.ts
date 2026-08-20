/**
 * K/V Store navigation module.
 * Handles navigating to and from the storage management page.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { kvStore, memories } from '../api/client';
import { toast } from '../components/Toast';
import {
  setActiveConversation,
  closeSidebar,
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
import { clearConversationHash, setStorageHash } from '../router/deeplink';
import { setCurrentConversationForBlobs } from '../utils/thumbnails';
import type { KVStoreCallbacks } from '../components/KVStorePage';
import type { Memory } from '../types/api';
import {
  ensureInputAreaVisible,
  focusMessageInput,
  shouldAutoFocusInput,
} from '../components/MessageInput';

import { renderChatHeader } from '../components/ChatHeader';
import { renderWelcomeMessageHtml } from '../components/WelcomeMessage';
import { updateConversationCost, updateAnonymousButtonState } from './toolbar';
import { hideNewMessagesAvailableBanner } from './sync-banner';
import { STORAGE_CACHE_MS } from '../config';

const log = createLogger('kv-store');

/** Flag to prevent concurrent refresh operations. */
let isRefreshing = false;

/**
 * Navigate to the storage management page.
 */
export async function navigateToStorage(forceRefresh: boolean = false): Promise<void> {
  log.info('Navigating to storage', { forceRefresh });
  const store = useStore.getState();

  // Get navigation token to detect if user navigates away during async operations
  const navToken = store.startNavigation();

  // Clean up UI state from previous conversation
  setCurrentConversationForBlobs('storage-loading');
  cleanupNewerMessagesScrollListener();
  if (hasActiveStreamingContext()) {
    cleanupStreamingContext();
  }
  hideNewMessagesAvailableBanner();

  // Update state — atomically clear all other views
  store.setActiveView('storage');
  setActiveConversation(null);
  setStorageHash();

  // Clear current conversation
  store.setCurrentConversation(null);

  // Update header title and clear stale UI state
  updateChatTitle('Storage');
  renderModelDropdown();
  updateConversationCost(null);
  renderChatHeader(null);

  // Update anonymous button state
  const anonymousBtn = getElementById<HTMLButtonElement>('anonymous-btn');
  if (anonymousBtn) {
    updateAnonymousButtonState(anonymousBtn, false);
  }

  // Hide input area and scroll button (storage view is not a chat)
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
  const { renderKVStorePage, renderKVStoreLoading } = await import(
    '../components/KVStorePage'
  );
  messagesContainer.appendChild(renderKVStoreLoading());

  closeSidebar();

  // Load storage data and memories in parallel
  const cacheAge = Date.now() - (store.storageLastFetch || 0);
  const needsRefresh = !store.storageData || cacheAge > STORAGE_CACHE_MS || forceRefresh;

  let storageData = store.storageData;
  let memoriesData: Memory[] = [];
  let deletedMemories: Memory[] = [];
  let memoryLimit = 0;
  let fetchFailed = false;

  if (needsRefresh) {
    try {
      const [kvData, memData, deletedData] = await Promise.all([
        kvStore.getNamespaces(),
        memories.listWithLimit(),
        memories.listDeleted(),
      ]);
      storageData = kvData;
      memoriesData = memData.memories;
      memoryLimit = memData.limit;
      deletedMemories = deletedData;
      store.setStorageData(storageData);
    } catch (error) {
      log.error('Failed to fetch storage data', { error });
      fetchFailed = true;
    }
  } else {
    // Still need to fetch memories even if KV data is cached
    try {
      const [memData, deletedData] = await Promise.all([
        memories.listWithLimit(),
        memories.listDeleted(),
      ]);
      memoriesData = memData.memories;
      memoryLimit = memData.limit;
      deletedMemories = deletedData;
    } catch (error) {
      log.error('Failed to fetch memories', { error });
    }
  }

  // Check if user navigated away during the async fetch
  if (!useStore.getState().isNavigationValid(navToken)) {
    log.info('User navigated away from storage during load, aborting render', { navToken });
    return;
  }

  // Clear loading state
  clearElement(messagesContainer);

  if (!storageData) {
    const errorEl = document.createElement('div');
    errorEl.className = 'kv-store-error';
    errorEl.innerHTML = `
      <div class="error-message">
        <strong>Error:</strong> Failed to load storage data. Please try again.
      </div>
    `;
    messagesContainer.appendChild(errorEl);
    toast.error('Failed to load storage data.');
    return;
  }

  // Build callbacks
  const callbacks: KVStoreCallbacks = {
    onRefresh: handleStorageRefresh,
    onNamespaceExpand: async (namespace: string) => {
      return await kvStore.getKeys(namespace);
    },
    onDeleteKey: async (namespace: string, key: string) => {
      await kvStore.deleteKey(namespace, key);
      toast.success('Key deleted.');
      store.invalidateStorageCache();
    },
    onClearNamespace: async (namespace: string) => {
      await kvStore.clearNamespace(namespace);
      toast.success('Namespace cleared.');
      store.invalidateStorageCache();
    },
    onDeleteMemory: async (memoryId: string) => {
      await memories.delete(memoryId);
      toast.success('Memory deleted.');
    },
    onSetMemoryProtected: async (memoryId: string, isProtected: boolean) => {
      await memories.setProtected(memoryId, isProtected);
      toast.success(isProtected ? 'Memory protected.' : 'Protection removed.');
    },
    onRestoreMemory: async (memoryId: string) => {
      await memories.restore(memoryId);
      toast.success('Memory restored.');
    },
  };

  // Render storage page
  const storageEl = renderKVStorePage(storageData, memoriesData, callbacks, {
    limit: memoryLimit,
    deletedMemories,
  });

  // Add stale data warning banner if fetch failed but we have cached data
  if (fetchFailed) {
    const warningBanner = document.createElement('div');
    warningBanner.className = 'kv-store-stale-warning';
    warningBanner.innerHTML = `
      <span class="warning-icon">${WARNING_ICON}</span>
      <span>Unable to refresh. Showing cached data.</span>
      <button class="btn-retry">Retry</button>
    `;
    warningBanner.querySelector('.btn-retry')?.addEventListener('click', () => {
      navigateToStorage(true);
    });
    storageEl.insertBefore(warningBanner, storageEl.firstChild);
    toast.warning('Showing cached data - could not refresh.');
  }

  messagesContainer.appendChild(storageEl);
  messagesContainer.scrollTop = 0;
}

/**
 * Handle refresh button click.
 */
async function handleStorageRefresh(): Promise<void> {
  if (isRefreshing) {
    log.debug('Refresh skipped - already in progress');
    return;
  }

  log.debug('Storage refresh clicked');
  isRefreshing = true;

  try {
    const store = useStore.getState();
    store.invalidateStorageCache();
    await navigateToStorage(true);
  } finally {
    isRefreshing = false;
  }
}

/**
 * Leave the storage view and return to normal chat.
 * @param clearMessages - Whether to clear messages and show welcome state (default: true)
 */
export function leaveStorageView(clearMessages: boolean = true): void {
  log.debug('Leaving storage view', { clearMessages });
  const store = useStore.getState();

  store.setActiveView('chat');

  // Show input area and scroll button
  ensureInputAreaVisible();

  // Update anonymous button state
  const anonymousBtn = getElementById<HTMLButtonElement>('anonymous-btn');
  if (anonymousBtn) {
    updateAnonymousButtonState(anonymousBtn, store.pendingAnonymousMode);
  }

  // Only clear UI state if not navigating to a conversation
  if (clearMessages) {
    clearConversationHash();
    store.setCurrentConversation(null);
    updateChatTitle('AI Chatbot');
    renderModelDropdown();
    updateConversationCost(null);
    renderChatHeader(null);

    const messagesContainer = getElementById<HTMLDivElement>('messages');
    if (messagesContainer) {
      messagesContainer.innerHTML = renderWelcomeMessageHtml();
    }

    if (shouldAutoFocusInput()) {
      focusMessageInput();
    }
  }
}
