/**
 * The small startup modules that wire components to their handlers
 * (core/startup/{app-status,composer,message-events,message-scrolling,
 * message-ui,search}.ts). The boot order is app-startup.test.ts; this is
 * what each one connects, and that a failing handler is logged, not lost.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({
  log: { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() },
  onSend: null as (() => void) | null,
  beforeScrollToBottom: null as (() => Promise<void>) | null,
  onSearchResult: null as ((convId: string, messageId: string, index: number) => void) | null,
  hasNewer: false,
}));

vi.mock('@/utils/logger', () => ({ createLogger: () => h.log }));

// app-status
vi.mock('@/components/VersionBanner', () => ({ initVersionBanner: vi.fn() }));
vi.mock('@/components/settings/notifications', () => ({ setPushControls: vi.fn() }));
vi.mock('@/core/attention', () => ({ initAttention: vi.fn() }));
vi.mock('@/core/connectivity', () => ({ initConnectivity: vi.fn() }));
vi.mock('@/core/push', () => ({
  disablePush: vi.fn(),
  enablePush: vi.fn(),
  getPushState: vi.fn(),
  registerServiceWorker: vi.fn(async () => undefined),
  sendTestNotification: vi.fn(),
}));

// composer
vi.mock('@/components/FileUpload', () => ({ initFileUpload: vi.fn((onChange: () => void) => onChange()) }));
vi.mock('@/components/MessageInput', () => ({
  initMessageInput: vi.fn((onSend: () => void) => {
    h.onSend = onSend;
  }),
  renderFilePreview: vi.fn(),
  updateSendButtonState: vi.fn(),
}));
vi.mock('@/components/ModelSelector', () => ({ initModelSelector: vi.fn() }));
vi.mock('@/components/VoiceInput', () => ({ initVoiceInput: vi.fn() }));
vi.mock('@/core/active-requests', () => ({ handleStopStreaming: vi.fn() }));
vi.mock('@/core/messaging', () => ({ sendMessage: vi.fn(async () => undefined), sendUiMessage: vi.fn() }));
vi.mock('@/core/rerun', () => ({ initOutboxHandlers: vi.fn() }));

// message-events
vi.mock('@/core/conversation-actions', () => ({ deleteMessage: vi.fn(async () => undefined) }));
vi.mock('@/core/tts', () => ({ speakMessageInternal: vi.fn() }));

// message-scrolling
vi.mock('@/components/ScrollToBottom', () => ({
  initScrollToBottom: vi.fn(),
  setBeforeScrollToBottomCallback: vi.fn((cb: () => Promise<void>) => {
    h.beforeScrollToBottom = cb;
  }),
}));
vi.mock('@/components/messages', () => ({
  initOrientationChangeHandler: vi.fn(),
  cleanupNewerMessagesScrollListener: vi.fn(),
  loadAllRemainingNewerMessages: vi.fn(async () => undefined),
}));
vi.mock('@/components/messages/turn-anchor', () => ({ initTurnAnchorResizeHold: vi.fn() }));
vi.mock('@/core/header-autohide', () => ({ initHeaderAutoHide: vi.fn() }));

// message-ui
vi.mock('@/components/ClaimCard', () => ({ initClaimCard: vi.fn() }));
vi.mock('@/components/ClaimsSheet', () => ({ initClaimsSheet: vi.fn() }));
vi.mock('@/components/CompactionIndicator', () => ({ initCompactionIndicator: vi.fn() }));
vi.mock('@/components/CostHistoryPopup', () => ({ costHistoryPopup: { init: vi.fn() } }));
vi.mock('@/components/ImageGenPopup', () => ({ initImageGenPopup: vi.fn() }));
vi.mock('@/components/Lightbox', () => ({ initLightbox: vi.fn() }));
vi.mock('@/components/MessageCostPopup', () => ({ initMessageCostPopup: vi.fn() }));
vi.mock('@/components/QuizBlock', () => ({ renderQuizBlock: vi.fn() }));
vi.mock('@/components/SourcesPopup', () => ({ initSourcesPopup: vi.fn() }));
vi.mock('@/components/messages/action-row', () => ({ initActionRows: vi.fn() }));
vi.mock('@/components/messages/research-offer', () => ({ initResearchOffers: vi.fn() }));
vi.mock('@/components/messages/research-progress', () => ({ initResearchProgress: vi.fn() }));
vi.mock('@/components/messages/artifact-host', () => ({ setArtifactSender: vi.fn() }));
vi.mock('@/utils/markdown', () => ({ setQuizRenderer: vi.fn() }));
vi.mock('@/core/deep-research', () => ({ declineDeepResearch: vi.fn(), startDeepResearch: vi.fn() }));

// search
vi.mock('@/components/SearchInput', () => ({ initSearchInput: vi.fn() }));
vi.mock('@/components/Sidebar', () => ({ renderConversationsList: vi.fn() }));
vi.mock('@/components/SearchResults', () => ({
  subscribeToSearchChanges: vi.fn((onResult: typeof h.onSearchResult) => {
    h.onSearchResult = onResult;
  }),
}));
vi.mock('@/core/search', () => ({ handleSearchResultClick: vi.fn(async () => undefined) }));

vi.mock('@/state/store', () => ({
  useStore: {
    getState: () => ({
      currentConversation: { id: 'c1' },
      getMessagesPagination: () => ({ hasNewer: h.hasNewer }),
    }),
  },
}));

import { initAppStatus } from '@/core/startup/app-status';
import { initComposer } from '@/core/startup/composer';
import { initMessageEvents } from '@/core/startup/message-events';
import { initMessageScrolling } from '@/core/startup/message-scrolling';
import { initMessageUi } from '@/core/startup/message-ui';
import { initSearch } from '@/core/startup/search';
import { setPushControls } from '@/components/settings/notifications';
import { disablePush, enablePush, getPushState, registerServiceWorker, sendTestNotification } from '@/core/push';
import { renderFilePreview, updateSendButtonState, initMessageInput } from '@/components/MessageInput';
import { handleStopStreaming } from '@/core/active-requests';
import { sendMessage, sendUiMessage } from '@/core/messaging';
import { deleteMessage } from '@/core/conversation-actions';
import { speakMessageInternal } from '@/core/tts';
import { cleanupNewerMessagesScrollListener, loadAllRemainingNewerMessages } from '@/components/messages';
import { initTurnAnchorResizeHold } from '@/components/messages/turn-anchor';
import { renderQuizBlock } from '@/components/QuizBlock';
import { setQuizRenderer } from '@/utils/markdown';
import { initClaimCard } from '@/components/ClaimCard';
import { setArtifactSender } from '@/components/messages/artifact-host';
import { initResearchOffers } from '@/components/messages/research-offer';
import { declineDeepResearch, startDeepResearch } from '@/core/deep-research';
import { handleSearchResultClick } from '@/core/search';

const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(() => {
  vi.clearAllMocks();
  h.hasNewer = false;
});

describe('initAppStatus', () => {
  it('gives the settings the push controls and keeps an existing subscription alive', () => {
    initAppStatus();
    expect(setPushControls).toHaveBeenCalledWith({
      getState: getPushState,
      enable: enablePush,
      disable: disablePush,
      sendTest: sendTestNotification,
    });
    expect(registerServiceWorker).toHaveBeenCalled();
  });
});

describe('initComposer', () => {
  it('sends from the input and stops with the stop handler', () => {
    initComposer();
    expect(initMessageInput).toHaveBeenCalledWith(expect.any(Function), handleStopStreaming);
    h.onSend?.();
    expect(sendMessage).toHaveBeenCalled();
  });

  it('logs a failed send instead of leaving it unhandled', async () => {
    vi.mocked(sendMessage).mockRejectedValueOnce(new Error('offline'));
    initComposer();
    h.onSend?.();
    await settle();
    expect(h.log.error).toHaveBeenCalledWith('Failed to send message', expect.anything());
  });

  it('refreshes the preview and the send button when attachments change', () => {
    initComposer();
    expect(renderFilePreview).toHaveBeenCalled();
    expect(updateSendButtonState).toHaveBeenCalled();
  });
});

describe('initMessageEvents', () => {
  it('deletes and reads aloud on the message action events', () => {
    initMessageEvents();
    window.dispatchEvent(new CustomEvent('message:delete', { detail: { messageId: 'm1' } }));
    expect(deleteMessage).toHaveBeenCalledWith('m1');
    window.dispatchEvent(new CustomEvent('message:speak', { detail: { messageId: 'm2', language: 'cs' } }));
    expect(speakMessageInternal).toHaveBeenCalledWith('m2', 'cs');
  });
});

describe('initMessageScrolling', () => {
  it('holds the turn anchor on the message list', () => {
    const list = document.createElement('div');
    list.id = 'messages';
    document.body.appendChild(list);
    initMessageScrolling();
    expect(initTurnAnchorResizeHold).toHaveBeenCalledWith(list);
    list.remove();
  });

  it('loads the missing newer messages before scrolling to the bottom of a partial view', async () => {
    initMessageScrolling();
    h.hasNewer = true;
    await h.beforeScrollToBottom?.();
    expect(loadAllRemainingNewerMessages).toHaveBeenCalledWith('c1');
    expect(cleanupNewerMessagesScrollListener).toHaveBeenCalled();
  });

  it('loads nothing when the view already ends at the newest message', async () => {
    initMessageScrolling();
    await h.beforeScrollToBottom?.();
    expect(loadAllRemainingNewerMessages).not.toHaveBeenCalled();
  });
});

describe('initMessageUi', () => {
  it('connects the message widgets to sending and deep research', () => {
    initMessageUi();
    expect(setQuizRenderer).toHaveBeenCalledWith(renderQuizBlock);
    expect(initClaimCard).toHaveBeenCalledWith({ send: sendUiMessage });
    expect(setArtifactSender).toHaveBeenCalledWith(sendUiMessage);
    expect(initResearchOffers).toHaveBeenCalledWith({ start: startDeepResearch, decline: declineDeepResearch });
  });
});

describe('initSearch', () => {
  it('opens a picked result, logging a failure', async () => {
    initSearch();
    h.onSearchResult?.('c1', 'm1', 2);
    expect(handleSearchResultClick).toHaveBeenCalledWith('c1', 'm1', 2);
    vi.mocked(handleSearchResultClick).mockRejectedValueOnce(new Error('gone'));
    h.onSearchResult?.('c2', 'm2', 0);
    await settle();
    expect(h.log.error).toHaveBeenCalledWith('Failed to open search result', expect.anything());
  });
});
