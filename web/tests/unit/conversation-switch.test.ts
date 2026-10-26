/**
 * switchToConversation: tears down what the previous conversation left
 * (blob URLs, the newer-page listener, and a streaming bubble that belongs
 * to a different conversation - switching back to the streaming one keeps
 * it), makes the conversation current, renders it and its header (agent
 * conversations get the agent header), restores an in-flight stream or
 * batch request, kicks off the journal resume and lost-reply checks, and
 * marks it read with the server's total count (not the loaded page size).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { ArtifactRef, CommandCenterResponse, Conversation, Message } from '@/types/api';

const m = vi.hoisted(() => ({
  offerLostReplyRetry: vi.fn(),
  resumeInflightStreamIfAny: vi.fn(() => Promise.resolve()),
  followRemoteStream: vi.fn(() => Promise.resolve()),
  readInflightStream: vi.fn<(id: string) => unknown>(() => null),
  resumeInflightBatchIfAny: vi.fn(() => Promise.resolve()),
  renderConversationsList: vi.fn(),
  setActiveConversation: vi.fn(),
  closeSidebar: vi.fn(),
  renderMessages: vi.fn(),
  updateChatTitle: vi.fn(),
  setupOlderMessagesScrollListener: vi.fn(),
  cleanupNewerMessagesScrollListener: vi.fn(),
  showLoadingIndicator: vi.fn(),
  restoreStreamingMessage: vi.fn(),
  hasActiveStreamingContext: vi.fn(() => false),
  getStreamingContextConversationId: vi.fn<() => string | null>(() => null),
  cleanupStreamingContext: vi.fn(),
  getStreamingMessageElement: vi.fn<(id: string) => HTMLElement | null>(() => null),
  addLiveArtifact: vi.fn(),
  focusMessageInput: vi.fn(),
  ensureInputAreaVisible: vi.fn(),
  restoreDraftForConversation: vi.fn(),
  shouldAutoFocusInput: vi.fn(() => false),
  renderModelDropdown: vi.fn(),
  enableScrollOnImageLoad: vi.fn(),
  setCurrentConversationForBlobs: vi.fn(),
  setConversationHash: vi.fn(),
  markConversationRead: vi.fn(),
  renderAgentConversationHeader: vi.fn(),
  renderChatHeader: vi.fn(),
  renderChatHeaderForConversation: vi.fn(),
  updateConversationCost: vi.fn(() => Promise.resolve()),
  updateAnonymousButtonState: vi.fn(),
  navigateToAgents: vi.fn(() => Promise.resolve()),
  handleAgentEditById: vi.fn(() => Promise.resolve()),
  log: { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

vi.mock('@/utils/logger', () => ({ createLogger: () => m.log }));

vi.mock('@/core/stream-resume', () => ({
  offerLostReplyRetry: m.offerLostReplyRetry,
  resumeInflightStreamIfAny: m.resumeInflightStreamIfAny,
  followRemoteStream: m.followRemoteStream,
}));
vi.mock('@/core/inflight-streams', () => ({ readInflightStream: m.readInflightStream }));
vi.mock('@/core/batch-resume', () => ({ resumeInflightBatchIfAny: m.resumeInflightBatchIfAny }));
vi.mock('@/components/Sidebar', () => ({
  renderConversationsList: m.renderConversationsList,
  setActiveConversation: m.setActiveConversation,
  closeSidebar: m.closeSidebar,
}));
vi.mock('@/components/messages', () => ({
  renderMessages: m.renderMessages,
  updateChatTitle: m.updateChatTitle,
  setupOlderMessagesScrollListener: m.setupOlderMessagesScrollListener,
  cleanupNewerMessagesScrollListener: m.cleanupNewerMessagesScrollListener,
  showLoadingIndicator: m.showLoadingIndicator,
  restoreStreamingMessage: m.restoreStreamingMessage,
  hasActiveStreamingContext: m.hasActiveStreamingContext,
  getStreamingContextConversationId: m.getStreamingContextConversationId,
  cleanupStreamingContext: m.cleanupStreamingContext,
  getStreamingMessageElement: m.getStreamingMessageElement,
}));
vi.mock('@/components/messages/artifacts', () => ({ addLiveArtifact: m.addLiveArtifact }));
vi.mock('@/components/MessageInput', () => ({
  focusMessageInput: m.focusMessageInput,
  ensureInputAreaVisible: m.ensureInputAreaVisible,
  restoreDraftForConversation: m.restoreDraftForConversation,
  shouldAutoFocusInput: m.shouldAutoFocusInput,
}));
vi.mock('@/components/ModelSelector', () => ({ renderModelDropdown: m.renderModelDropdown }));
vi.mock('@/components/messages/image-load-scroll', () => ({
  enableScrollOnImageLoad: m.enableScrollOnImageLoad,
}));
vi.mock('@/utils/thumbnail-blob-urls', () => ({
  setCurrentConversationForBlobs: m.setCurrentConversationForBlobs,
}));
vi.mock('@/router/deeplink', () => ({ setConversationHash: m.setConversationHash }));
vi.mock('@/sync/SyncManager', () => ({
  getSyncManager: () => ({ markConversationRead: m.markConversationRead }),
}));
vi.mock('@/components/AgentConversationHeader', () => ({
  renderAgentConversationHeader: m.renderAgentConversationHeader,
}));
vi.mock('@/components/ChatHeader', () => ({ renderChatHeader: m.renderChatHeader }));
vi.mock('@/core/conversation-header', () => ({
  renderChatHeaderForConversation: m.renderChatHeaderForConversation,
}));
vi.mock('@/core/toolbar', () => ({
  updateConversationCost: m.updateConversationCost,
  updateAnonymousButtonState: m.updateAnonymousButtonState,
}));
vi.mock('@/core/agents', () => ({
  navigateToAgents: m.navigateToAgents,
  handleAgentEditById: m.handleAgentEditById,
}));

import { useStore } from '@/state/store';
import { switchToConversation } from '@/core/conversation-switch';
import { initNavigation } from '@/core/startup/navigation';

function msg(id: string): Message {
  return { id, role: 'user', content: id, created_at: '2026-10-01T00:00:00Z' };
}

function conv(overrides: Partial<Conversation> = {}): Conversation {
  return {
    id: 'c1',
    title: 'Chat',
    model: 'm',
    created_at: '',
    updated_at: '',
    messages: [msg('m1'), msg('m2')],
    ...overrides,
  };
}

describe('switchToConversation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStore.setState(useStore.getInitialState(), true);
    document.body.innerHTML = '';
  });

  it('makes the conversation current and renders it with its header and URL', () => {
    const c = conv();
    switchToConversation(c);

    expect(useStore.getState().currentConversation).toEqual(c);
    expect(m.setActiveConversation).toHaveBeenCalledWith('c1');
    expect(m.updateChatTitle).toHaveBeenCalledWith('Chat');
    expect(m.renderChatHeaderForConversation).toHaveBeenCalledWith(c);
    expect(m.setConversationHash).toHaveBeenCalledWith('c1');
    expect(m.renderMessages).toHaveBeenCalledWith(c.messages, {});
    expect(m.restoreDraftForConversation).toHaveBeenCalledWith('c1');
    expect(m.renderAgentConversationHeader).not.toHaveBeenCalled();
  });

  it('frees the previous conversation before showing the new one', () => {
    switchToConversation(conv({ id: 'c2' }));

    expect(m.setCurrentConversationForBlobs).toHaveBeenCalledWith('c2');
    expect(m.cleanupNewerMessagesScrollListener).toHaveBeenCalled();
    const blobsOrder = m.setCurrentConversationForBlobs.mock.invocationCallOrder[0] ?? 0;
    const renderOrder = m.renderMessages.mock.invocationCallOrder[0] ?? 0;
    expect(blobsOrder).toBeLessThan(renderOrder);
  });

  it('cleans up the streaming bubble of a different conversation', () => {
    m.hasActiveStreamingContext.mockReturnValue(true);
    m.getStreamingContextConversationId.mockReturnValue('other');

    switchToConversation(conv());

    expect(m.cleanupStreamingContext).toHaveBeenCalled();
  });

  it('keeps the streaming bubble when switching back to the streaming conversation', () => {
    m.hasActiveStreamingContext.mockReturnValue(true);
    m.getStreamingContextConversationId.mockReturnValue('c1');

    switchToConversation(conv());

    expect(m.cleanupStreamingContext).not.toHaveBeenCalled();
  });

  it('listens for older pages only for a persisted conversation', () => {
    switchToConversation(conv());
    expect(m.setupOlderMessagesScrollListener).toHaveBeenCalledWith('c1');

    m.setupOlderMessagesScrollListener.mockClear();
    switchToConversation(conv({ id: 'temp-1' }));
    expect(m.setupOlderMessagesScrollListener).not.toHaveBeenCalled();
  });

  it("passes the server's pending-approval status to the renderer", () => {
    switchToConversation(conv({ has_pending_approval: true }));
    expect(m.renderMessages).toHaveBeenCalledWith(expect.any(Array), { hasPendingApproval: true });
  });

  it('renders a conversation without messages as empty', () => {
    const noMessages = conv();
    delete noMessages.messages;
    switchToConversation(noMessages);
    expect(m.renderMessages).toHaveBeenCalledWith([], {});
    expect(m.resumeInflightBatchIfAny).toHaveBeenCalledWith('c1', []);
  });

  describe('agent conversations', () => {
    it('hide the regular header and show the agent header with its name', () => {
      useStore.setState({
        commandCenterData: { agents: [{ id: 'a1', name: 'Watcher' }] } as unknown as CommandCenterResponse,
      });
      switchToConversation(conv({ is_agent: true, agent_id: 'a1' }));

      expect(m.renderChatHeader).toHaveBeenCalledWith(null);
      expect(m.renderChatHeaderForConversation).not.toHaveBeenCalled();
      expect(m.renderAgentConversationHeader).toHaveBeenCalledWith('Watcher', expect.any(Function), expect.any(Function));
    });

    it('fall back to the conversation title when the agent is unknown', () => {
      switchToConversation(conv({ is_agent: true, agent_id: 'a9', title: 'Agent chat' }));
      expect(m.renderAgentConversationHeader).toHaveBeenCalledWith(
        'Agent chat',
        expect.any(Function),
        expect.any(Function)
      );
    });

    it("wire the header's back and edit actions set at startup", () => {
      initNavigation();
      switchToConversation(conv({ is_agent: true, agent_id: 'a1' }));
      const [, onBack, onEdit] = m.renderAgentConversationHeader.mock.lastCall as [string, () => void, () => void];

      onBack();
      onEdit();

      expect(m.navigateToAgents).toHaveBeenCalled();
      expect(m.handleAgentEditById).toHaveBeenCalledWith('a1');
    });

    it('log instead of throwing when startup has not set the header actions', async () => {
      vi.resetModules();
      const fresh = await import('@/core/conversation-switch');
      fresh.switchToConversation(conv({ is_agent: true, agent_id: 'a1' }));
      const [, onBack, onEdit] = m.renderAgentConversationHeader.mock.lastCall as [string, () => void, () => void];

      expect(() => {
        onBack();
        onEdit();
      }).not.toThrow();

      expect(m.navigateToAgents).not.toHaveBeenCalled();
      expect(m.handleAgentEditById).not.toHaveBeenCalled();
      expect(m.log.debug).toHaveBeenCalledWith('Agent header actions not set');
    });
  });

  describe('in-flight requests', () => {
    it('restores a streaming reply with its content and the artifacts made while away', () => {
      const bubble = document.createElement('div');
      m.getStreamingMessageElement.mockReturnValue(bubble);
      const art = { artifact_id: 'x' } as unknown as ArtifactRef;
      useStore.getState().setActiveRequest('c1', {
        conversationId: 'c1',
        type: 'stream',
        content: 'Partial',
        artifacts: [art],
      });

      switchToConversation(conv());

      expect(m.restoreStreamingMessage).toHaveBeenCalledWith('c1', 'Partial', undefined);
      expect(m.addLiveArtifact).toHaveBeenCalledWith(bubble, art);
      expect(m.showLoadingIndicator).not.toHaveBeenCalled();
    });

    it('shows the loading indicator for a batch request', () => {
      useStore.getState().setActiveRequest('c1', { conversationId: 'c1', type: 'batch' });

      switchToConversation(conv());

      expect(m.showLoadingIndicator).toHaveBeenCalled();
      expect(m.restoreStreamingMessage).not.toHaveBeenCalled();
    });

    it('restores the active request before trying the journal resume', () => {
      useStore.getState().setActiveRequest('c1', { conversationId: 'c1', type: 'stream', content: '' });

      switchToConversation(conv({ streaming_message_id: 's1' }));

      expect(m.resumeInflightStreamIfAny).toHaveBeenCalledWith('c1', 's1');
      const restoreOrder = m.restoreStreamingMessage.mock.invocationCallOrder[0] ?? Infinity;
      const resumeOrder = m.resumeInflightStreamIfAny.mock.invocationCallOrder[0] ?? 0;
      expect(restoreOrder).toBeLessThan(resumeOrder);
    });

    it('follows a reply another device is streaming, anchored like a send', () => {
      switchToConversation(conv({ streaming_message_id: 's1' }));
      expect(m.followRemoteStream).toHaveBeenCalledWith('c1', 's1', { anchor: true });
    });

    it('leaves a reply this device owns to the journal resume', () => {
      m.readInflightStream.mockReturnValueOnce({ conversationId: 'c1' });
      switchToConversation(conv({ streaming_message_id: 's1' }));
      expect(m.followRemoteStream).not.toHaveBeenCalled();
    });

    it('checks for a lost reply and a pending batch reply, following nothing idle', () => {
      const c = conv();
      switchToConversation(c);

      expect(m.followRemoteStream).not.toHaveBeenCalled();
      expect(m.offerLostReplyRetry).toHaveBeenCalledWith(c);
      expect(m.resumeInflightBatchIfAny).toHaveBeenCalledWith('c1', c.messages);
      expect(m.restoreStreamingMessage).not.toHaveBeenCalled();
    });
  });

  describe('chrome after the switch', () => {
    it('marks the conversation read with the total count from pagination', () => {
      switchToConversation(conv(), 40);
      expect(m.markConversationRead).toHaveBeenCalledWith('c1', 40);
      expect(m.renderConversationsList).toHaveBeenCalled();
    });

    it('falls back to the loaded message count without a total', () => {
      switchToConversation(conv());
      expect(m.markConversationRead).toHaveBeenCalledWith('c1', 2);
    });

    it('refreshes the model dropdown, closes the sidebar and loads the cost', () => {
      switchToConversation(conv());
      expect(m.renderModelDropdown).toHaveBeenCalled();
      expect(m.closeSidebar).toHaveBeenCalled();
      expect(m.ensureInputAreaVisible).toHaveBeenCalled();
      expect(m.updateConversationCost).toHaveBeenCalledWith('c1');
    });

    it('focuses the composer only where auto-focus is wanted', () => {
      switchToConversation(conv());
      expect(m.focusMessageInput).not.toHaveBeenCalled();

      m.shouldAutoFocusInput.mockReturnValue(true);
      switchToConversation(conv());
      expect(m.focusMessageInput).toHaveBeenCalled();
    });

    it("shows the conversation's anonymous mode on the toolbar button", () => {
      document.body.innerHTML = '<button id="anonymous-btn"></button>';
      useStore.getState().setAnonymousMode('c1', true);

      switchToConversation(conv());

      expect(m.updateAnonymousButtonState).toHaveBeenCalledWith(document.getElementById('anonymous-btn'), true);
    });
  });
});
