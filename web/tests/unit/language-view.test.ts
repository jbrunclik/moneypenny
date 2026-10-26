/**
 * Language learning view: the programs list (served from the cache while
 * it is fresh, refetched when stale or forced, an error state on failure,
 * dropped when the user navigated away meanwhile), program CRUD from the
 * list, a program's chat (messages rendered, quick actions mounted, an
 * empty conversation started with the session-start message) and leaving
 * the view back to the welcome screen.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { LanguageProgram, Message } from '@/types/api';

type ProgramsCallbacks = [
  onAdd: (data: { name: string; emoji: string }) => void,
  onDelete: (id: string) => void,
  onSelect: (id: string) => void,
];

const h = vi.hoisted(() => ({
  api: {
    getPrograms: vi.fn(),
    createProgram: vi.fn(),
    deleteProgram: vi.fn(),
    getConversation: vi.fn(),
    reset: vi.fn(),
    updateQuickActions: vi.fn(),
  },
  toast: { success: vi.fn(), error: vi.fn() },
  sidebar: { setActiveConversation: vi.fn(), closeSidebar: vi.fn(), setLanguageActive: vi.fn() },
  messages: {
    addMessageToUI: vi.fn(),
    updateChatTitle: vi.fn(),
    hasActiveStreamingContext: vi.fn(() => false),
    cleanupStreamingContext: vi.fn(),
    cleanupNewerMessagesScrollListener: vi.fn(),
    lockOlderQuizBlocks: vi.fn(),
  },
  hash: { clearConversationHash: vi.fn(), setLanguageHash: vi.fn() },
  quick: { mountQuickActionsBar: vi.fn(), unmountQuickActionsBar: vi.fn(), openQuickActionsEditor: vi.fn() },
  dashboard: {
    lastCallbacks: null as ProgramsCallbacks | null,
    createLanguageProgramsElement: vi.fn(),
    renderLanguageProgramHeader: vi.fn(),
    createLanguageLoadingElement: vi.fn(),
  },
  input: {
    ensureInputAreaVisible: vi.fn(),
    hideInputArea: vi.fn(),
    focusMessageInput: vi.fn(),
    refocusMessageInputAfterSend: vi.fn(),
    shouldAutoFocusInput: vi.fn(() => false),
  },
  sendMessage: vi.fn(() => Promise.resolve()),
  renderChatHeader: vi.fn(),
  toolbar: { updateConversationCost: vi.fn(() => Promise.resolve()), updateAnonymousButtonState: vi.fn() },
}));

vi.mock('@/api/programs', () => ({ language: h.api }));
vi.mock('@/components/Toast', () => ({ toast: h.toast }));
vi.mock('@/components/Sidebar', () => h.sidebar);
vi.mock('@/components/messages', () => h.messages);
vi.mock('@/components/ModelSelector', () => ({ renderModelDropdown: vi.fn() }));
vi.mock('@/components/ScrollToBottom', () => ({ checkScrollButtonVisibility: vi.fn() }));
vi.mock('@/components/messages/turn-anchor', () => ({ resetTurnAnchor: vi.fn() }));
vi.mock('@/router/deeplink', () => h.hash);
vi.mock('@/core/quick-actions', () => h.quick);
vi.mock('@/components/LanguageDashboard', () => h.dashboard);
vi.mock('@/utils/thumbnail-blob-urls', () => ({ setCurrentConversationForBlobs: vi.fn() }));
vi.mock('@/components/MessageInput', () => h.input);
vi.mock('@/core/messaging', () => ({ sendMessage: h.sendMessage }));
vi.mock('@/components/ChatHeader', () => ({ renderChatHeader: h.renderChatHeader }));
vi.mock('@/components/WelcomeMessage', () => ({
  createWelcomeMessage: () => {
    const el = document.createElement('div');
    el.className = 'welcome';
    return el;
  },
}));
vi.mock('@/core/toolbar', () => h.toolbar);

import { leaveLanguageView, navigateToLanguage, navigateToLanguageProgram } from '@/core/language';
import { APP_NAME, LANGUAGE_PROGRAMS_CACHE_MS } from '@/config';
import { useStore } from '@/state/store';

function program(id: string, extra: Partial<LanguageProgram> = {}): LanguageProgram {
  return { id, name: `Program ${id}`, emoji: '🇩🇪', quick_actions: [], ...extra } as LanguageProgram;
}

function message(id: string): Message {
  return { id, role: 'assistant', content: id, created_at: '' } as Message;
}

function conversationResponse(messages: Message[] = []) {
  return { id: 'lang-conv', model: 'm', created_at: 'c', updated_at: 'u', messages };
}

const container = () => document.getElementById('messages') as HTMLElement;

/** The list callbacks handed to the programs element on its last render. */
function listCallbacks(): ProgramsCallbacks {
  const cb = h.dashboard.lastCallbacks;
  if (!cb) throw new Error('programs list not rendered');
  return cb;
}

beforeEach(() => {
  vi.clearAllMocks();
  document.body.innerHTML = `
    <button id="anonymous-btn"></button>
    <div id="messages"></div>
    <textarea id="message-input"></textarea>`;
  h.dashboard.lastCallbacks = null;
  h.dashboard.createLanguageLoadingElement.mockImplementation(() => {
    const el = document.createElement('div');
    el.className = 'loading';
    return el;
  });
  h.dashboard.createLanguageProgramsElement.mockImplementation(
    (programs: LanguageProgram[], ...callbacks: ProgramsCallbacks) => {
      h.dashboard.lastCallbacks = callbacks;
      const el = document.createElement('div');
      el.className = 'programs';
      el.textContent = programs.map((p) => p.id).join(',');
      return el;
    }
  );
  h.api.getPrograms.mockResolvedValue([program('de')]);
  h.api.createProgram.mockResolvedValue(program('fr'));
  h.api.deleteProgram.mockResolvedValue(undefined);
  h.api.getConversation.mockResolvedValue(conversationResponse([message('m1')]));
  h.api.reset.mockResolvedValue({});
  useStore.getState().clearLanguageState();
  useStore.setState({ currentConversation: null, pendingAnonymousMode: false });
});

describe('programs list', () => {
  it('fetches the programs, caches them and renders the list', async () => {
    await navigateToLanguage();

    expect(h.api.getPrograms).toHaveBeenCalledTimes(1);
    expect(useStore.getState().languagePrograms?.map((p) => p.id)).toEqual(['de']);
    expect(container().querySelector('.programs')?.textContent).toBe('de');
    expect(useStore.getState().isLanguageView).toBe(true);
    expect(h.hash.setLanguageHash).toHaveBeenCalledWith();
    expect(h.input.hideInputArea).toHaveBeenCalled();
    expect(h.sidebar.setLanguageActive).toHaveBeenCalledWith(true);
  });

  it('serves a fresh cache without fetching', async () => {
    useStore.getState().setLanguagePrograms([program('cached')]);
    await navigateToLanguage();
    expect(h.api.getPrograms).not.toHaveBeenCalled();
    expect(container().querySelector('.programs')?.textContent).toBe('cached');
  });

  it('refetches a stale cache', async () => {
    useStore.getState().setLanguagePrograms([program('cached')]);
    useStore.setState({ languageProgramsLastFetch: Date.now() - LANGUAGE_PROGRAMS_CACHE_MS - 1 });
    await navigateToLanguage();
    expect(h.api.getPrograms).toHaveBeenCalledTimes(1);
    expect(container().querySelector('.programs')?.textContent).toBe('de');
  });

  it('refetches when forced', async () => {
    useStore.getState().setLanguagePrograms([program('cached')]);
    await navigateToLanguage(true);
    expect(h.api.getPrograms).toHaveBeenCalledTimes(1);
  });

  it('shows an error state when loading fails', async () => {
    h.api.getPrograms.mockRejectedValue(new Error('boom'));
    await navigateToLanguage();
    expect(container().textContent).toContain('Failed to load programs');
    expect(h.toast.error).toHaveBeenCalledWith('Failed to load language programs.');
  });

  it('does not render over a view the user navigated to meanwhile', async () => {
    let resolve: (p: LanguageProgram[]) => void = () => undefined;
    h.api.getPrograms.mockReturnValue(new Promise((r) => (resolve = r)));
    const pending = navigateToLanguage();
    useStore.getState().startNavigation();
    resolve([program('de')]);
    await pending;
    expect(container().querySelector('.programs')).toBeNull();
    expect(useStore.getState().languagePrograms).toBeNull();
  });

  it('adding a program refetches the list', async () => {
    await navigateToLanguage();
    h.api.getPrograms.mockResolvedValue([program('de'), program('fr')]);
    listCallbacks()[0]({ name: 'French', emoji: '🇫🇷' });
    await vi.waitFor(() => expect(container().querySelector('.programs')?.textContent).toBe('de,fr'));
    expect(h.api.createProgram).toHaveBeenCalledWith({ name: 'French', emoji: '🇫🇷' });
    expect(h.toast.success).toHaveBeenCalledWith('Program "French" created.');
  });

  it('reports a failed add', async () => {
    h.api.createProgram.mockRejectedValue(new Error('boom'));
    await navigateToLanguage();
    listCallbacks()[0]({ name: 'French', emoji: '🇫🇷' });
    await vi.waitFor(() => expect(h.toast.error).toHaveBeenCalledWith('Failed to create program.'));
  });

  it('deleting a program refetches the list', async () => {
    await navigateToLanguage();
    h.api.getPrograms.mockResolvedValue([]);
    listCallbacks()[1]('de');
    await vi.waitFor(() => expect(container().querySelector('.programs')?.textContent).toBe(''));
    expect(h.api.deleteProgram).toHaveBeenCalledWith('de');
    expect(h.toast.success).toHaveBeenCalledWith('Program deleted.');
  });

  it('reports a failed delete', async () => {
    h.api.deleteProgram.mockRejectedValue(new Error('boom'));
    await navigateToLanguage();
    listCallbacks()[1]('de');
    await vi.waitFor(() => expect(h.toast.error).toHaveBeenCalledWith('Failed to delete program.'));
  });

  it('selecting a program opens its chat', async () => {
    await navigateToLanguage();
    listCallbacks()[2]('de');
    await vi.waitFor(() => expect(h.api.getConversation).toHaveBeenCalledWith('de'));
  });
});

describe('program chat', () => {
  beforeEach(() => {
    useStore.getState().setLanguagePrograms([program('de', { name: 'German' })]);
  });

  it('renders the conversation with the program header and quick actions', async () => {
    await navigateToLanguageProgram('de');

    expect(useStore.getState().currentConversation).toMatchObject({ id: 'lang-conv', title: 'German' });
    expect(useStore.getState().languageCurrentProgram).toBe('de');
    expect(h.hash.setLanguageHash).toHaveBeenCalledWith('de');
    expect(h.messages.addMessageToUI).toHaveBeenCalledTimes(1);
    expect(h.messages.lockOlderQuizBlocks).toHaveBeenCalled();
    expect(h.messages.updateChatTitle).toHaveBeenCalledWith('German');
    expect(h.dashboard.renderLanguageProgramHeader).toHaveBeenCalled();
    expect(h.quick.mountQuickActionsBar).toHaveBeenCalledWith(
      expect.objectContaining({ namespace: 'language', programId: 'de' })
    );
    expect(h.sendMessage).not.toHaveBeenCalled();
  });

  it('fetches the programs when none are cached (page reload)', async () => {
    useStore.getState().clearLanguageState();
    h.api.getPrograms.mockResolvedValue([program('de', { name: 'Deutsch' })]);
    await navigateToLanguageProgram('de');
    expect(h.api.getPrograms).toHaveBeenCalledTimes(1);
    expect(h.messages.updateChatTitle).toHaveBeenCalledWith('Deutsch');
  });

  it('falls back to a plain header for an unknown program', async () => {
    await navigateToLanguageProgram('xx');
    expect(h.messages.updateChatTitle).toHaveBeenCalledWith('Language');
    expect(h.renderChatHeader).toHaveBeenCalledWith(null);
    expect(h.quick.unmountQuickActionsBar).toHaveBeenCalled();
  });

  it('starts an empty conversation with the session-start message', async () => {
    h.api.getConversation.mockResolvedValue(conversationResponse([]));
    h.sendMessage.mockImplementation(() => {
      expect((document.getElementById('message-input') as HTMLTextAreaElement).value).toBe(
        '[System: session-start]'
      );
      return Promise.resolve();
    });
    await navigateToLanguageProgram('de');
    expect(h.sendMessage).toHaveBeenCalledTimes(1);
  });

  it('saving quick actions updates the cached program', async () => {
    await navigateToLanguageProgram('de');
    const updated = program('de', {
      name: 'German',
      quick_actions: [{ id: 'q1', emoji: '🧠', label: 'Quiz', body: 'Quiz me', fields: [] }],
    });
    h.api.updateQuickActions.mockResolvedValue(updated);
    const options = h.quick.mountQuickActionsBar.mock.calls[0]?.[0] as {
      save: (actions: unknown[]) => Promise<unknown>;
    };
    expect(await options.save(updated.quick_actions)).toEqual(updated.quick_actions);
    expect(useStore.getState().languagePrograms?.[0]).toBe(updated);
  });

  it('resetting clears the conversation and reloads it', async () => {
    await navigateToLanguageProgram('de');
    const onReset = h.dashboard.renderLanguageProgramHeader.mock.calls[0]?.[2] as () => void;
    onReset();
    await vi.waitFor(() => expect(h.api.getConversation).toHaveBeenCalledTimes(2));
    expect(h.api.reset).toHaveBeenCalledWith('de');
    expect(h.toast.success).toHaveBeenCalledWith('Language conversation cleared.');
  });

  it('reports a failed load', async () => {
    h.api.getConversation.mockRejectedValue(new Error('boom'));
    await navigateToLanguageProgram('de');
    expect(h.toast.error).toHaveBeenCalledWith('Failed to load language conversation.');
  });

  it('drops a load the user navigated away from', async () => {
    let resolve: (c: unknown) => void = () => undefined;
    h.api.getConversation.mockReturnValue(new Promise((r) => (resolve = r)));
    const pending = navigateToLanguageProgram('de');
    useStore.getState().startNavigation();
    resolve(conversationResponse([message('m1')]));
    await pending;
    expect(h.messages.addMessageToUI).not.toHaveBeenCalled();
    expect(useStore.getState().currentConversation).toBeNull();
  });
});

describe('leaving the view', () => {
  it('returns to the chat view with the welcome screen', async () => {
    await navigateToLanguage();
    useStore.setState({ pendingAnonymousMode: true });
    leaveLanguageView();

    const state = useStore.getState();
    expect(state.isLanguageView).toBe(false);
    expect(state.languageCurrentProgram).toBeNull();
    expect(state.currentConversation).toBeNull();
    expect(h.sidebar.setLanguageActive).toHaveBeenLastCalledWith(false);
    expect(h.hash.clearConversationHash).toHaveBeenCalled();
    expect(h.messages.updateChatTitle).toHaveBeenLastCalledWith(APP_NAME);
    expect(h.toolbar.updateAnonymousButtonState).toHaveBeenLastCalledWith(expect.anything(), true);
    expect(container().querySelector('.welcome')).not.toBeNull();
    expect(h.input.ensureInputAreaVisible).toHaveBeenCalled();
  });
});
