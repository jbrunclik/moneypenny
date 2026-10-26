/**
 * Characterization tests for app startup (core/init.ts and the startup
 * modules it calls): the ORDER of the startup steps, the initial-route
 * dispatch, the sync callbacks and the window events init() wires up.
 *
 * Every collaborator is mocked to record its call into `calls`, so the
 * expected sequences below pin today's startup order. A step that moves
 * must keep its place in these lists.
 */
import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest';
import { useStore } from '@/state/store';

const h = vi.hoisted(() => {
  const calls: string[] = [];
  // Arguments of each step's latest call (kept here: mock call history is
  // cleared between tests)
  const lastArgs = new Map<string, unknown[]>();
  const rec = (name: string, result?: unknown) =>
    vi.fn((...args: unknown[]) => {
      calls.push(name);
      lastArgs.set(name, args);
      return result;
    });
  const recAsync = (name: string, result?: unknown) => rec(name, Promise.resolve(result));
  return { calls, lastArgs, rec, recAsync };
});
const { calls } = h;

/** The arguments a startup step was last called with. */
function argsOf(name: string): unknown[] {
  const args = h.lastArgs.get(name);
  if (!args) throw new Error(`${name} was not called`);
  return args;
}

vi.mock('@/core/error-reporting', () => ({ initErrorReporting: h.rec('initErrorReporting') }));
vi.mock('@/utils/theme', () => ({
  initializeTheme: h.rec('initializeTheme', { scheme: 'light', effectiveTheme: 'light' }),
}));
vi.mock('@/utils/avatar', () => ({ installAvatarFallback: h.rec('installAvatarFallback') }));
vi.mock('@/components/Toast', () => ({
  initToast: h.rec('initToast'),
  toast: { info: h.rec('toast.info'), error: h.rec('toast.error') },
}));
vi.mock('@/components/Modal', () => ({ initModal: h.rec('initModal') }));
vi.mock('@/utils/popupEscapeHandler', () => ({
  initPopupEscapeListener: h.rec('initPopupEscapeListener'),
}));
vi.mock('@/components/MessageInput', () => ({
  initMessageInput: h.rec('initMessageInput'),
  updateSendButtonState: h.rec('updateSendButtonState'),
}));
vi.mock('@/core/rerun', () => ({ initOutboxHandlers: h.rec('initOutboxHandlers') }));
vi.mock('@/components/ModelSelector', () => ({
  initModelSelector: h.rec('initModelSelector'),
  renderModelDropdown: h.rec('renderModelDropdown'),
}));
vi.mock('@/components/FileUpload', () => ({ initFileUpload: h.rec('initFileUpload') }));
vi.mock('@/components/VoiceInput', () => ({ initVoiceInput: h.rec('initVoiceInput') }));
vi.mock('@/components/Lightbox', () => ({ initLightbox: h.rec('initLightbox') }));
vi.mock('@/components/SourcesPopup', () => ({ initSourcesPopup: h.rec('initSourcesPopup') }));
vi.mock('@/components/ClaimCard', () => ({ initClaimCard: h.rec('initClaimCard') }));
vi.mock('@/components/ClaimsSheet', () => ({ initClaimsSheet: h.rec('initClaimsSheet') }));
vi.mock('@/components/messages/research-offer', () => ({
  initResearchOffers: h.rec('initResearchOffers'),
}));
vi.mock('@/components/messages/research-progress', () => ({
  initResearchProgress: h.rec('initResearchProgress'),
}));
vi.mock('@/components/messages/action-row', () => ({ initActionRows: h.rec('initActionRows') }));
vi.mock('@/components/ImageGenPopup', () => ({ initImageGenPopup: h.rec('initImageGenPopup') }));
vi.mock('@/components/MessageCostPopup', () => ({
  initMessageCostPopup: h.rec('initMessageCostPopup'),
}));
vi.mock('@/components/CostHistoryPopup', () => ({
  costHistoryPopup: { init: h.rec('costHistoryPopup.init') },
  getCostHistoryPopupHtml: () => '<div id="cost-history-popup"></div>',
}));
vi.mock('@/components/CompactionIndicator', () => ({
  initCompactionIndicator: h.rec('initCompactionIndicator'),
  getCompactionPopupHtml: () => '<div id="compaction-popup"></div>',
}));
vi.mock('@/core/agents', () => ({
  initAgents: h.rec('initAgents'),
  navigateToAgents: h.recAsync('navigateToAgents'),
}));
vi.mock('@/components/ScrollToBottom', () => ({
  initScrollToBottom: h.rec('initScrollToBottom'),
  setBeforeScrollToBottomCallback: h.rec('setBeforeScrollToBottomCallback'),
}));
vi.mock('@/components/messages/turn-anchor', () => ({
  initTurnAnchorResizeHold: h.rec('initTurnAnchorResizeHold'),
}));
vi.mock('@/core/header-autohide', () => ({ initHeaderAutoHide: h.rec('initHeaderAutoHide') }));
vi.mock('@/components/messages', () => ({
  renderMessages: h.rec('renderMessages'),
  updateChatTitle: h.rec('updateChatTitle'),
  initOrientationChangeHandler: h.rec('initOrientationChangeHandler'),
  showConversationLoader: h.rec('showConversationLoader'),
  cleanupOlderMessagesScrollListener: h.rec('cleanupOlderMessagesScrollListener'),
  cleanupNewerMessagesScrollListener: h.rec('cleanupNewerMessagesScrollListener'),
  loadAllRemainingNewerMessages: h.recAsync('loadAllRemainingNewerMessages'),
}));
vi.mock('@/core/keyboard-viewport', () => ({
  initKeyboardViewportPinning: h.rec('initKeyboardViewportPinning'),
  initKbDebugToggle: h.rec('initKbDebugToggle'),
}));
vi.mock('@/core/composer-height', () => ({ initComposerHeight: h.rec('initComposerHeight') }));
vi.mock('@/core/quick-actions', () => ({ initQuickActions: h.rec('initQuickActions') }));
vi.mock('@/core/attention', () => ({ initAttention: h.rec('initAttention') }));
vi.mock('@/core/connectivity', () => ({ initConnectivity: h.rec('initConnectivity') }));
vi.mock('@/components/VersionBanner', () => ({ initVersionBanner: h.rec('initVersionBanner') }));
vi.mock('@/core/push', () => ({
  registerServiceWorker: h.recAsync('registerServiceWorker'),
  resyncPushSubscription: h.recAsync('resyncPushSubscription'),
}));
vi.mock('@/components/SearchInput', () => ({ initSearchInput: h.rec('initSearchInput') }));
vi.mock('@/components/SearchResults', () => ({
  subscribeToSearchChanges: h.rec('subscribeToSearchChanges'),
}));
vi.mock('@/core/tts', () => ({
  initTTSVoices: h.rec('initTTSVoices'),
  speakMessageInternal: h.rec('speakMessage'),
}));
vi.mock('@/core/events', () => ({ setupEventListeners: h.rec('setupEventListeners') }));
vi.mock('@/components/SidebarSelection', () => ({
  initSidebarSelection: h.rec('initSidebarSelection'),
}));
vi.mock('@/core/gestures', () => ({ setupTouchGestures: h.rec('setupTouchGestures') }));
vi.mock('@/core/toolbar', () => ({
  initToolbarButtons: h.rec('initToolbarButtons'),
  updateConversationCost: h.recAsync('updateConversationCost'),
}));
vi.mock('@/router/deeplink', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/router/deeplink')>()),
  initDeepLinking: h.rec('initDeepLinking', null),
  cleanupDeepLinking: h.rec('cleanupDeepLinking'),
  clearConversationHash: h.rec('clearConversationHash'),
  pushEmptyHash: h.rec('pushEmptyHash'),
}));
vi.mock('@/auth/google', () => ({
  checkAuth: h.recAsync('checkAuth', true),
  initGoogleSignIn: h.recAsync('initGoogleSignIn'),
  renderGoogleButton: h.rec('renderGoogleButton'),
}));
vi.mock('@/api/conversations', () => ({
  conversations: {
    list: h.recAsync('conversations.list', { conversations: [], pagination: { has_more: false } }),
  },
}));
vi.mock('@/api/app', () => ({
  models: { list: h.recAsync('models.list', { models: [], default: 'm' }) },
  config: { getUploadConfig: h.recAsync('config.getUploadConfig', {}) },
}));
vi.mock('@/api/integrations', () => ({
  todoist: { getStatus: h.recAsync('todoist.getStatus', { connected: false }) },
  calendar: { getStatus: h.recAsync('calendar.getStatus', { connected: false }) },
}));
vi.mock('@/components/Sidebar', () => ({
  renderConversationsList: h.rec('renderConversationsList'),
  renderUserInfo: h.rec('renderUserInfo'),
  cleanupInfiniteScroll: h.rec('cleanupInfiniteScroll'),
  loadArchivedConversations: h.recAsync('loadArchivedConversations'),
  initSidebarTimeRefresh: h.rec('initSidebarTimeRefresh'),
}));
vi.mock('@/components/SpendBanner', () => ({
  refreshSpendWarning: h.recAsync('refreshSpendWarning'),
}));
vi.mock('@/sync/SyncManager', () => {
  const manager = {
    start: h.recAsync('syncManager.start'),
    fullSync: h.recAsync('syncManager.fullSync'),
    incrementalSync: h.recAsync('syncManager.incrementalSync'),
  };
  return {
    initSyncManager: h.rec('initSyncManager', manager),
    stopSyncManager: h.rec('stopSyncManager'),
    getSyncManager: () => manager,
  };
});
vi.mock('@/components/ChatHeader', () => ({ renderChatHeader: h.rec('renderChatHeader') }));
vi.mock('@/core/messaging', () => ({
  sendMessage: h.recAsync('sendMessage'),
  sendUiMessage: h.recAsync('sendUiMessage', true),
}));
vi.mock('@/core/active-requests', () => ({
  handleStopStreaming: h.rec('handleStopStreaming'),
  abortAllStreamingRequests: h.rec('abortAllStreamingRequests'),
}));
vi.mock('@/core/search', () => ({ handleSearchResultClick: h.recAsync('handleSearchResultClick') }));
vi.mock('@/core/conversation-deeplink', () => ({
  loadDeepLinkedConversation: h.recAsync('loadDeepLinkedConversation'),
  handleDeepLinkNavigation: h.rec('handleDeepLinkNavigation'),
}));
vi.mock('@/core/conversation-actions', () => ({
  deleteMessage: h.recAsync('deleteMessage'),
  bulkDeleteConversations: h.recAsync('bulkDeleteConversations'),
}));
vi.mock('@/core/archive', () => ({
  navigateToArchive: h.rec('navigateToArchive'),
  leaveArchiveView: h.rec('leaveArchiveView'),
}));
vi.mock('@/core/trash', () => ({
  navigateToTrash: h.rec('navigateToTrash'),
  leaveTrashView: h.rec('leaveTrashView'),
  loadTrashedConversations: h.recAsync('loadTrashedConversations'),
}));
vi.mock('@/core/planner', () => ({
  navigateToPlanner: h.recAsync('navigateToPlanner'),
  leavePlannerView: h.rec('leavePlannerView'),
}));
vi.mock('@/core/sports', () => ({
  navigateToSports: h.recAsync('navigateToSports'),
  navigateToSportsProgram: h.recAsync('navigateToSportsProgram'),
}));
vi.mock('@/core/language', () => ({
  navigateToLanguage: h.recAsync('navigateToLanguage'),
  navigateToLanguageProgram: h.recAsync('navigateToLanguageProgram'),
}));
vi.mock('@/core/kv-store', () => ({ navigateToStorage: h.recAsync('navigateToStorage') }));
vi.mock('@/core/remote-merge', () => ({ mergeExternalChanges: h.recAsync('mergeExternalChanges') }));

import { init } from '@/core/init';
import { checkAuth } from '@/auth/google';
import { mergeExternalChanges } from '@/core/remote-merge';
import { deleteMessage } from '@/core/conversation-actions';
import { speakMessageInternal } from '@/core/tts';
import { handleSearchResultClick } from '@/core/search';
import { sendMessage } from '@/core/messaging';
import { loadAllRemainingNewerMessages } from '@/components/messages';
import { navigateToSportsProgram } from '@/core/sports';
import { loadDeepLinkedConversation } from '@/core/conversation-deeplink';
import type { SyncManagerCallbacks } from '@/sync/sync-state';
import type { Conversation } from '@/types/api';

/** Let every queued promise continuation run. */
async function flush(): Promise<void> {
  for (let i = 0; i < 20; i++) await Promise.resolve();
}

const COMPONENT_STEPS = [
  'initToast',
  'initModal',
  'initPopupEscapeListener',
  'initMessageInput',
  'initOutboxHandlers',
  'initModelSelector',
  'initFileUpload',
  'initVoiceInput',
  'initLightbox',
  'initSourcesPopup',
  'initClaimCard',
  'initClaimsSheet',
  'initResearchOffers',
  'initResearchProgress',
  'initActionRows',
  'initImageGenPopup',
  'initMessageCostPopup',
  'costHistoryPopup.init',
  'initCompactionIndicator',
  'initAgents',
  'initScrollToBottom',
  'initTurnAnchorResizeHold',
  'initHeaderAutoHide',
  'setBeforeScrollToBottomCallback',
  'initOrientationChangeHandler',
  'initKeyboardViewportPinning',
  'initComposerHeight',
  'initQuickActions',
  'initKbDebugToggle',
  'initAttention',
  'initConnectivity',
  'initVersionBanner',
  'registerServiceWorker',
  'initSearchInput',
  'subscribeToSearchChanges',
  'initTTSVoices',
  'setupEventListeners',
  'initSidebarSelection',
  'setupTouchGestures',
  'initToolbarButtons',
  'initDeepLinking',
  'checkAuth',
];

/** loadInitialData up to the route step (no trash-route skip). */
const DATA_STEPS = [
  'resyncPushSubscription',
  'conversations.list',
  'models.list',
  'config.getUploadConfig',
  'todoist.getStatus',
  'calendar.getStatus',
  'renderConversationsList',
  'renderUserInfo',
  'refreshSpendWarning',
  'renderModelDropdown',
  'initSidebarTimeRefresh',
  'loadArchivedConversations',
  'loadTrashedConversations',
];

const SYNC_AND_FINALLY_STEPS = [
  'initSyncManager',
  'syncManager.start',
  'updateSendButtonState',
  'renderConversationsList',
];

function syncCallbacks(): SyncManagerCallbacks {
  return argsOf('initSyncManager')[0] as SyncManagerCallbacks;
}

async function loginAt(hash: string): Promise<void> {
  window.location.hash = hash;
  calls.length = 0;
  window.dispatchEvent(new Event('auth:login'));
  await flush();
}

function conv(over: Partial<Conversation>): Conversation {
  return {
    id: 'c1',
    title: 'T',
    model: 'm',
    created_at: '2026-10-26T00:00:00Z',
    updated_at: '2026-10-26T00:00:00Z',
    ...over,
  };
}

describe('app startup (signed in)', () => {
  beforeAll(async () => {
    window.location.hash = '';
    document.body.innerHTML = '<div id="app"></div>';
    calls.length = 0;
    await init();
    await flush();
  });

  beforeEach(() => {
    useStore.setState({ currentConversation: null, isPlannerView: false });
  });

  it('runs the startup steps in order', () => {
    expect(calls).toEqual([
      'initErrorReporting',
      'initializeTheme',
      'installAvatarFallback',
      ...COMPONENT_STEPS,
      ...DATA_STEPS,
      ...SYNC_AND_FINALLY_STEPS,
    ]);
  });

  it('renders the app shell with the login overlay hidden', () => {
    for (const id of [
      'sidebar',
      'new-chat-btn',
      'conversations-list',
      'messages',
      'message-input',
      'send-btn',
      'lightbox',
      'sources-popup',
      'imagegen-popup',
      'message-cost-popup',
      'cost-history-popup',
      'compaction-popup',
      'settings-popup',
      'login-overlay',
      'google-login-btn',
    ]) {
      expect(document.getElementById(id), id).not.toBeNull();
    }
    expect(document.getElementById('login-overlay')?.classList.contains('hidden')).toBe(true);
    expect(document.querySelector('#messages .welcome-message, #messages *')).not.toBeNull();
  });

  it('sends from the composer and stops streaming via the handlers it passes', async () => {
    const [onSend, onStop] = argsOf('initMessageInput') as [() => void, () => void];
    onSend();
    await flush();
    expect(sendMessage).toHaveBeenCalled();
    expect(onStop).toBeTypeOf('function');
  });

  it('opens a search result through the search subscription', async () => {
    const [onResult] = argsOf('subscribeToSearchChanges') as [
      (convId: string, messageId: string, resultIndex: number) => void,
    ];
    onResult('c1', 'm1', 2);
    await flush();
    expect(handleSearchResultClick).toHaveBeenCalledWith('c1', 'm1', 2);
  });

  it('loads remaining newer messages before scroll-to-bottom only when there are some', async () => {
    const [beforeScroll] = argsOf('setBeforeScrollToBottomCallback') as [() => Promise<void>];
    useStore.setState({ currentConversation: conv({ id: 'c1' }) });
    useStore.setState({ messagesPagination: new Map() });
    await beforeScroll();
    expect(loadAllRemainingNewerMessages).not.toHaveBeenCalled();

    useStore.setState({
      messagesPagination: new Map([
        ['c1', { hasOlder: false, hasNewer: true, isLoadingOlder: false, isLoadingNewer: false }],
      ]) as never,
    });
    calls.length = 0;
    await beforeScroll();
    expect(calls).toEqual(['loadAllRemainingNewerMessages', 'cleanupNewerMessagesScrollListener']);
  });

  it('routes message:delete and message:speak window events', () => {
    window.dispatchEvent(new CustomEvent('message:delete', { detail: { messageId: 'm1' } }));
    expect(deleteMessage).toHaveBeenCalledWith('m1');
    window.dispatchEvent(
      new CustomEvent('message:speak', { detail: { messageId: 'm2', language: 'cs' } }),
    );
    expect(speakMessageInternal).toHaveBeenCalledWith('m2', 'cs');
  });

  it('exposes the E2E sync helpers on window', async () => {
    calls.length = 0;
    await window.__testFullSync();
    await window.__testIncrementalSync();
    expect(calls).toEqual(['syncManager.fullSync', 'syncManager.incrementalSync']);
  });

  describe('sync callbacks', () => {
    it('reset the UI when the current conversation is deleted elsewhere', () => {
      useStore.setState({ currentConversation: conv({ id: 'c1' }) });
      calls.length = 0;
      syncCallbacks().onCurrentConversationDeleted?.();
      expect(useStore.getState().currentConversation).toBeNull();
      expect(calls).toEqual([
        'renderMessages',
        'updateChatTitle',
        'renderChatHeader',
        'updateConversationCost',
        'clearConversationHash',
      ]);
    });

    it('merge external updates into the LIVE current conversation', () => {
      vi.mocked(mergeExternalChanges).mockClear();
      useStore.setState({ currentConversation: conv({ id: 'live' }) });
      syncCallbacks().onCurrentConversationExternalUpdate(1);
      expect(mergeExternalChanges).toHaveBeenCalledWith('live');
    });

    it('re-render the list and title, and reload archive/trash counts', () => {
      calls.length = 0;
      const cb = syncCallbacks();
      cb.onConversationsUpdated?.();
      cb.onCurrentConversationRenamed?.('New title');
      cb.onArchiveOrTrashChanged?.({ archive: true, trash: false });
      cb.onArchiveOrTrashChanged?.({ archive: false, trash: true });
      expect(calls).toEqual([
        'renderConversationsList',
        'updateChatTitle',
        'loadArchivedConversations',
        'loadTrashedConversations',
      ]);
    });

    it('handle planner delete/reset/update only while the planner is open (live state)', () => {
      const cb = syncCallbacks();
      vi.mocked(mergeExternalChanges).mockClear();
      calls.length = 0;
      cb.onPlannerDeleted?.();
      cb.onPlannerReset?.();
      cb.onPlannerExternalUpdate?.(1);
      expect(calls).toEqual([]);

      useStore.setState({ isPlannerView: true, currentConversation: conv({ id: 'planner' }) });
      cb.onPlannerDeleted?.();
      cb.onPlannerReset?.();
      cb.onPlannerExternalUpdate?.(1);
      expect(calls).toEqual([
        'toast.info',
        'leavePlannerView',
        'pushEmptyHash',
        'toast.info',
        'navigateToPlanner',
        'mergeExternalChanges',
      ]);
      expect(mergeExternalChanges).toHaveBeenCalledWith('planner');
    });

    it('merge agent conversation updates only for an agent conversation', () => {
      const cb = syncCallbacks();
      vi.mocked(mergeExternalChanges).mockClear();
      useStore.setState({ currentConversation: conv({ id: 'plain' }) });
      cb.onAgentConversationExternalUpdate?.(1);
      expect(mergeExternalChanges).not.toHaveBeenCalled();
      useStore.setState({ currentConversation: conv({ id: 'agent', is_agent: true }) });
      cb.onAgentConversationExternalUpdate?.(1);
      expect(mergeExternalChanges).toHaveBeenCalledWith('agent');
    });
  });

  describe('auth:login reloads data for the route in the hash, before sync starts', () => {
    it.each([
      ['#/planner', 'navigateToPlanner'],
      ['#/agents', 'navigateToAgents'],
      ['#/storage', 'navigateToStorage'],
      ['#/sports', 'navigateToSports'],
      ['#/language', 'navigateToLanguage'],
      ['#/archive', 'navigateToArchive'],
    ])('%s -> %s', async (hash, step) => {
      await loginAt(hash);
      expect(calls).toEqual([...DATA_STEPS, step, ...SYNC_AND_FINALLY_STEPS]);
    });

    it('#/trash skips the trash-count fetch (the view loads it)', async () => {
      await loginAt('#/trash');
      expect(calls).toEqual([
        ...DATA_STEPS.filter((s) => s !== 'loadTrashedConversations'),
        'navigateToTrash',
        ...SYNC_AND_FINALLY_STEPS,
      ]);
    });

    it('opens a sports program from the hash', async () => {
      await loginAt('#/sports/gym');
      expect(navigateToSportsProgram).toHaveBeenCalledWith('gym');
      expect(calls).toContain('navigateToSportsProgram');
    });

    it('opens a deep-linked conversation', async () => {
      await loginAt('#/conversations/abc-123');
      expect(loadDeepLinkedConversation).toHaveBeenCalledWith('abc-123');
      expect(calls).toEqual([...DATA_STEPS, 'loadDeepLinkedConversation', ...SYNC_AND_FINALLY_STEPS]);
    });

    it('home starts sync without navigating', async () => {
      await loginAt('');
      expect(calls).toEqual([...DATA_STEPS, ...SYNC_AND_FINALLY_STEPS]);
    });
  });

  it('auth:logout tears down streams, sync and routing, then shows sign-in', async () => {
    calls.length = 0;
    window.dispatchEvent(new Event('auth:logout'));
    await flush();
    expect(calls).toEqual([
      'abortAllStreamingRequests',
      'stopSyncManager',
      'cleanupInfiniteScroll',
      'cleanupOlderMessagesScrollListener',
      'cleanupNewerMessagesScrollListener',
      'clearConversationHash',
      'cleanupDeepLinking',
      'renderConversationsList',
      'renderMessages',
      'initGoogleSignIn',
      'renderGoogleButton',
      'initDeepLinking',
    ]);
    expect(document.getElementById('login-overlay')?.classList.contains('hidden')).toBe(false);
  });
});

describe('app startup (signed out, booting into a route)', () => {
  it('shows the loader and the sign-in button instead of loading data', async () => {
    window.location.hash = '#/planner';
    document.body.innerHTML = '<div id="app"></div>';
    vi.mocked(checkAuth).mockImplementationOnce(() => {
      calls.push('checkAuth');
      return Promise.resolve(false);
    });
    calls.length = 0;
    await init();
    await flush();
    expect(calls).toEqual([
      'initErrorReporting',
      'initializeTheme',
      'installAvatarFallback',
      'showConversationLoader',
      ...COMPONENT_STEPS,
      'clearConversationHash',
      'initGoogleSignIn',
      'renderGoogleButton',
    ]);
    expect(document.getElementById('login-overlay')?.classList.contains('hidden')).toBe(false);
    // The boot loader replaced the welcome screen
    expect(document.querySelector('#messages .welcome-message')).toBeNull();
  });
});
