/**
 * navigateToStorage: what the storage page loads (K/V namespaces only when
 * stale, memories always) and what it renders on success, a failed refresh
 * with a cache, and a failed load without one.
 */
import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest';

vi.mock('@/state/store', () => ({
  useStore: { getState: vi.fn(), setState: vi.fn(), subscribe: vi.fn(() => vi.fn()) },
}));

vi.mock('@/utils/logger', () => ({
  createLogger: () => ({ debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() }),
}));

vi.mock('@/api/kv-store', () => ({
  kvStore: { getNamespaces: vi.fn(), getKeys: vi.fn(), deleteKey: vi.fn(), clearNamespace: vi.fn() },
}));

vi.mock('@/api/memories', () => ({
  memories: {
    listWithLimit: vi.fn(),
    listDeleted: vi.fn(),
    delete: vi.fn(),
    setProtected: vi.fn(),
    restore: vi.fn(),
  },
}));

vi.mock('@/components/Toast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

vi.mock('@/components/Sidebar', () => ({
  setActiveConversation: vi.fn(),
  closeSidebar: vi.fn(),
}));

vi.mock('@/components/messages', () => ({
  updateChatTitle: vi.fn(),
  hasActiveStreamingContext: vi.fn(() => false),
  cleanupStreamingContext: vi.fn(),
  cleanupNewerMessagesScrollListener: vi.fn(),
}));

vi.mock('@/components/ModelSelector', () => ({ renderModelDropdown: vi.fn() }));
vi.mock('@/components/ChatHeader', () => ({ renderChatHeader: vi.fn() }));
vi.mock('@/components/WelcomeMessage', () => ({ createWelcomeMessage: vi.fn(() => document.createElement('div')) }));

vi.mock('@/utils/dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils/dom')>()),
  getElementById: vi.fn(),
  clearElement: vi.fn((el: HTMLElement) => el.replaceChildren()),
}));

vi.mock('@/router/deeplink', () => ({ clearConversationHash: vi.fn(), setStorageHash: vi.fn() }));
vi.mock('@/utils/thumbnail-blob-urls', () => ({ setCurrentConversationForBlobs: vi.fn() }));

vi.mock('@/config', () => ({ STORAGE_CACHE_MS: 60000, APP_NAME: 'Moneypenny' }));

vi.mock('@/components/KVStorePage', () => ({
  renderKVStorePage: vi.fn(() => {
    const el = document.createElement('div');
    el.className = 'kv-store-page';
    return el;
  }),
  renderKVStoreLoading: vi.fn(() => document.createElement('div')),
}));

vi.mock('@/components/MessageInput', () => ({
  ensureInputAreaVisible: vi.fn(),
  focusMessageInput: vi.fn(),
  shouldAutoFocusInput: vi.fn(() => false),
}));

vi.mock('@/core/toolbar', () => ({
  updateConversationCost: vi.fn(),
  updateAnonymousButtonState: vi.fn(),
}));

vi.mock('@/core/sync-banner', () => ({ hideNewMessagesAvailableBanner: vi.fn() }));

import { useStore } from '@/state/store';
import { kvStore } from '@/api/kv-store';
import { memories } from '@/api/memories';
import { getElementById } from '@/utils/dom';
import { renderKVStorePage } from '@/components/KVStorePage';
import { updateAnonymousButtonState } from '@/core/toolbar';
import { navigateToStorage } from '@/core/kv-store';

const NAMESPACES = { namespaces: [{ name: 'ns', key_count: 1 }] };
const MEMORY = { id: 'm1', content: 'likes tea' };

describe('navigateToStorage', () => {
  let messages: HTMLDivElement;
  let inputArea: HTMLDivElement;
  let mockStore: Record<string, unknown>;

  beforeEach(() => {
    vi.clearAllMocks();
    document.body.replaceChildren();
    messages = document.createElement('div');
    inputArea = document.createElement('div');
    inputArea.className = 'input-area';
    document.body.append(inputArea);
    (getElementById as Mock).mockImplementation((id: string) => {
      if (id === 'messages') return messages;
      if (id === 'anonymous-btn') return document.createElement('button');
      return null;
    });
    mockStore = {
      storageData: null,
      storageLastFetch: 0,
      startNavigation: vi.fn(() => 1),
      isNavigationValid: vi.fn(() => true),
      setActiveView: vi.fn(),
      setCurrentConversation: vi.fn(),
      setStorageData: vi.fn(),
      invalidateStorageCache: vi.fn(),
    };
    (useStore.getState as Mock).mockReturnValue(mockStore);
    (memories.listWithLimit as Mock).mockResolvedValue({ memories: [MEMORY], limit: 50 });
    (memories.listDeleted as Mock).mockResolvedValue([]);
  });

  it('fetches namespaces and memories when there is no cache, and renders them', async () => {
    (kvStore.getNamespaces as Mock).mockResolvedValue(NAMESPACES);

    await navigateToStorage();

    expect(mockStore.setStorageData).toHaveBeenCalledWith(NAMESPACES);
    expect(renderKVStorePage).toHaveBeenCalledWith(NAMESPACES, [MEMORY], expect.any(Object), {
      limit: 50,
      deletedMemories: [],
    });
    expect(messages.querySelector('.kv-store-page')).not.toBeNull();
    expect(messages.querySelector('.kv-store-stale-warning')).toBeNull();
    expect(inputArea.classList.contains('hidden')).toBe(true);
    expect(updateAnonymousButtonState).toHaveBeenCalledWith(expect.any(HTMLButtonElement), false);
  });

  it('uses fresh cached namespaces and still fetches memories', async () => {
    mockStore.storageData = NAMESPACES;
    mockStore.storageLastFetch = Date.now();

    await navigateToStorage();

    expect(kvStore.getNamespaces).not.toHaveBeenCalled();
    expect(memories.listWithLimit).toHaveBeenCalled();
    expect(renderKVStorePage).toHaveBeenCalledWith(NAMESPACES, [MEMORY], expect.any(Object), {
      limit: 50,
      deletedMemories: [],
    });
  });

  it('shows the cached page with a stale warning when a forced refresh fails', async () => {
    mockStore.storageData = NAMESPACES;
    mockStore.storageLastFetch = Date.now();
    (kvStore.getNamespaces as Mock).mockRejectedValue(new Error('down'));

    await navigateToStorage(true);

    // A failed refresh shows no memories (they were fetched together)
    expect(renderKVStorePage).toHaveBeenCalledWith(NAMESPACES, [], expect.any(Object), {
      limit: 0,
      deletedMemories: [],
    });
    expect(messages.querySelector('.kv-store-stale-warning')).not.toBeNull();
  });

  it('shows an error when the load fails without a cache', async () => {
    (kvStore.getNamespaces as Mock).mockRejectedValue(new Error('down'));

    await navigateToStorage();

    expect(renderKVStorePage).not.toHaveBeenCalled();
    expect(messages.querySelector('.kv-store-error')).not.toBeNull();
  });

  it('does not render when the user navigated away during the load', async () => {
    (kvStore.getNamespaces as Mock).mockResolvedValue(NAMESPACES);
    (mockStore.isNavigationValid as Mock).mockReturnValue(false);

    await navigateToStorage();

    expect(renderKVStorePage).not.toHaveBeenCalled();
  });
});
