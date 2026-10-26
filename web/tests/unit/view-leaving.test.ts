/**
 * Opening a conversation from a feature view: selectConversation and
 * createConversation leave the agents view (keeping the main area for the
 * conversation) or the sports view first, then make 'chat' the active view.
 * From a chat nothing is left. The leavers are wired at startup
 * (core/startup/navigation.ts); unwired, leaving logs instead of throwing.
 * Real store; the views' leave functions are mocked to record the call.
 */
import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest';
import type { ConversationDetailResponse } from '@/types/api';

const m = vi.hoisted(() => ({
  leaveAgentsView: vi.fn(),
  leaveSportsView: vi.fn(),
  getConversation: vi.fn(),
  log: { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

vi.mock('@/utils/logger', () => ({ createLogger: () => m.log }));
vi.mock('@/core/agents', () => ({
  leaveAgentsView: m.leaveAgentsView,
  navigateToAgents: vi.fn(() => Promise.resolve()),
  handleAgentEditById: vi.fn(() => Promise.resolve()),
}));
vi.mock('@/core/sports', () => ({ leaveSportsView: m.leaveSportsView }));
vi.mock('@/core/conversation-switch', () => ({
  switchToConversation: vi.fn(),
  setAgentHeaderActions: vi.fn(),
}));
vi.mock('@/core/kv-store', () => ({ leaveStorageView: vi.fn() }));
vi.mock('@/core/toolbar', () => ({
  updateConversationCost: vi.fn(() => Promise.resolve()),
  updateAnonymousButtonState: vi.fn(),
}));
vi.mock('@/core/header-autohide', () => ({ revealHeader: vi.fn() }));
vi.mock('@/core/conversation-header', () => ({ renderChatHeaderForConversation: vi.fn() }));
vi.mock('@/core/outbox', () => ({
  reconcileOutboxWithServer: (_id: string, messages: unknown[]) => messages,
}));
vi.mock('@/api/conversations', () => ({ conversations: { get: m.getConversation } }));
vi.mock('@/sync/SyncManager', () => ({ getSyncManager: () => null }));
vi.mock('@/router/deeplink', () => ({ pushEmptyHash: vi.fn() }));
vi.mock('@/components/Sidebar', () => ({
  renderConversationsList: vi.fn(),
  setActiveConversation: vi.fn(),
  closeSidebar: vi.fn(),
  setPlannerActive: vi.fn(),
}));
vi.mock('@/components/messages', () => ({
  renderMessages: vi.fn(),
  showConversationLoader: vi.fn(),
  hideConversationLoader: vi.fn(),
  updateChatTitle: vi.fn(),
  cleanupOlderMessagesScrollListener: vi.fn(),
  cleanupNewerMessagesScrollListener: vi.fn(),
}));
vi.mock('@/components/MessageInput', () => ({
  beginDraftForLoadingConversation: vi.fn(),
  endDraftForLoadingConversation: vi.fn(),
  focusMessageInput: vi.fn(),
  ensureInputAreaVisible: vi.fn(),
  restoreDraftForConversation: vi.fn(),
  shouldAutoFocusInput: vi.fn(() => false),
  updateSendButtonState: vi.fn(),
}));
vi.mock('@/components/ModelSelector', () => ({ renderModelDropdown: vi.fn() }));

import { useStore } from '@/state/store';
import { createConversation, selectConversation } from '@/core/conversation';
import { initNavigation } from '@/core/startup/navigation';

function detail(id: string): ConversationDetailResponse {
  return {
    id,
    title: 'Chat',
    model: 'm',
    created_at: '',
    updated_at: '',
    messages: [],
    message_pagination: { total_count: 0, has_more: false },
  } as unknown as ConversationDetailResponse;
}

function expectChatView(): void {
  const { isAgentsView, isSportsView, isPlannerView, isStorageView } = useStore.getState();
  expect({ isAgentsView, isSportsView, isPlannerView, isStorageView }).toEqual({
    isAgentsView: false,
    isSportsView: false,
    isPlannerView: false,
    isStorageView: false,
  });
}

describe('opening a conversation from a feature view', () => {
  beforeAll(() => {
    initNavigation();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    useStore.setState({ conversations: [], currentConversation: null });
    useStore.getState().setActiveView('chat');
    m.getConversation.mockImplementation((id: string) => Promise.resolve(detail(id)));
  });

  it('selecting one leaves the agents view without clearing the main area', async () => {
    useStore.getState().setActiveView('agents');

    await selectConversation('c1');

    expect(m.leaveAgentsView).toHaveBeenCalledWith(false);
    expect(m.leaveSportsView).not.toHaveBeenCalled();
    expectChatView();
  });

  it('selecting one leaves the sports view', async () => {
    useStore.getState().setActiveView('sports');

    await selectConversation('c1');

    expect(m.leaveSportsView).toHaveBeenCalledTimes(1);
    expect(m.leaveAgentsView).not.toHaveBeenCalled();
    expectChatView();
  });

  it('a new chat leaves the sports view', () => {
    useStore.getState().setActiveView('sports');

    createConversation();

    expect(m.leaveSportsView).toHaveBeenCalledTimes(1);
    expectChatView();
  });

  it('a new chat leaves the agents view', () => {
    useStore.getState().setActiveView('agents');

    createConversation();

    expect(m.leaveAgentsView).toHaveBeenCalledWith(false);
    expectChatView();
  });

  it('leaves nothing from a chat', async () => {
    await selectConversation('c1');

    expect(m.leaveAgentsView).not.toHaveBeenCalled();
    expect(m.leaveSportsView).not.toHaveBeenCalled();
  });
});

describe('leaving a feature view before startup wired the leavers', () => {
  it('logs at debug and still switches to the chat view', async () => {
    vi.resetModules();
    const fresh = await import('@/core/conversation');
    const { useStore: freshStore } = await import('@/state/store');
    freshStore.getState().setActiveView('sports');
    vi.clearAllMocks();

    expect(() => fresh.createConversation()).not.toThrow();

    expect(m.leaveSportsView).not.toHaveBeenCalled();
    expect(m.log.debug).toHaveBeenCalledWith('View leavers not set', { view: 'sports' });
    expect(freshStore.getState().isSportsView).toBe(false);
  });
});
