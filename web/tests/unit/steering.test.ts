/**
 * Mid-run steering: text sent while a turn streams goes into that turn. On
 * success it shows as a user bubble right above the reply still streaming
 * (or at the bottom when there is none), keeps the sync count in step,
 * clears the composer and its draft; on failure it toasts and keeps the
 * text. Steering the turn never read is moved after the reply and answered -
 * only in the conversation on screen.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const api = vi.hoisted(() => ({ interject: vi.fn<(id: string, text: string, clientId?: string) => Promise<void>>() }));
const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
const { getStreamingMessageElement, clearMessageInput, programmaticScrollToBottom, incrementLocalMessageCount } =
  vi.hoisted(() => ({
    getStreamingMessageElement: vi.fn<(convId: string) => HTMLElement | null>(),
    clearMessageInput: vi.fn(),
    programmaticScrollToBottom: vi.fn(),
    incrementLocalMessageCount: vi.fn(),
  }));

vi.mock('@/api/conversations', () => ({ conversations: api, messages: {} }));
vi.mock('@/components/Toast', () => ({ toast: toastMock }));
vi.mock('@/components/messages', () => ({
  // Renders the bubble the way the real one does: appended to the container
  addMessageToUI: (message: { id: string }, container: HTMLElement) => {
    const el = document.createElement('div');
    el.className = 'message user';
    el.dataset.messageId = message.id;
    container.appendChild(el);
  },
  getStreamingMessageElement,
}));
vi.mock('@/components/MessageInput', () => ({ clearMessageInput }));
vi.mock('@/utils/programmatic-scroll', () => ({ programmaticScrollToBottom }));
vi.mock('@/sync/SyncManager', () => ({ getSyncManager: () => ({ incrementLocalMessageCount }) }));

import { answerUnreadSteering, interjectIntoActiveTurn } from '@/core/steering';
import { useStore } from '@/state/store';
import type { Conversation, Message } from '@/types/api';

const CONV = 'conv-1';

function msg(id: string, role: Message['role']): Message {
  return { id, role, content: id, created_at: '2026-10-26T10:00:00Z' };
}

function conv(id: string): Conversation {
  return { id, title: id, model: 'm', created_at: '', updated_at: '' };
}

function bubble(id: string, extraClass = ''): HTMLElement {
  const el = document.createElement('div');
  el.className = `message ${extraClass}`.trim();
  el.dataset.messageId = id;
  return el;
}

function container(): HTMLElement {
  const el = document.getElementById('messages');
  if (!el) throw new Error('no #messages');
  return el;
}

function domOrder(): string[] {
  return [...container().children].map((el) => (el as HTMLElement).dataset.messageId ?? '');
}

function storeOrder(convId = CONV): string[] {
  return useStore
    .getState()
    .getMessages(convId)
    .map((m) => m.id);
}

beforeEach(() => {
  vi.clearAllMocks();
  api.interject.mockResolvedValue(undefined);
  getStreamingMessageElement.mockReturnValue(null);
  // jsdom has no layout: scrollIntoView does not exist
  Element.prototype.scrollIntoView = vi.fn();
  document.body.innerHTML = '<div id="messages"></div>';
  useStore.setState({
    messages: new Map(),
    messagesPagination: new Map(),
    conversationDrafts: {},
    currentConversation: null,
  });
});

describe('interjectIntoActiveTurn', () => {
  it('sends the text with the same id the user bubble gets', async () => {
    await interjectIntoActiveTurn(CONV, 'use metric units');

    const [convId, text, clientId] = api.interject.mock.calls[0] ?? [];
    expect(convId).toBe(CONV);
    expect(text).toBe('use metric units');
    expect(storeOrder()).toEqual([clientId]);
    expect(domOrder()).toEqual([clientId]);
  });

  it('adds the steering as a user message with the typed text', async () => {
    await interjectIntoActiveTurn(CONV, 'shorter please');

    const [message] = useStore.getState().getMessages(CONV);
    expect(message).toMatchObject({ role: 'user', content: 'shorter please' });
  });

  it('places the bubble above the reply that is still streaming', async () => {
    const reply = bubble('streaming', 'assistant');
    container().append(bubble('u1'), reply);
    getStreamingMessageElement.mockReturnValue(reply);

    await interjectIntoActiveTurn(CONV, 'focus on cost');

    const steeringId = storeOrder()[0];
    expect(domOrder()).toEqual(['u1', steeringId, 'streaming']);
    expect(programmaticScrollToBottom).not.toHaveBeenCalled();
  });

  it('appends the bubble and scrolls to the bottom when no reply is streaming', async () => {
    container().append(bubble('u1'));

    await interjectIntoActiveTurn(CONV, 'and in Czech');

    const steeringId = storeOrder()[0];
    expect(domOrder()).toEqual(['u1', steeringId]);
    expect(programmaticScrollToBottom).toHaveBeenCalledWith(container());
  });

  it('counts the persisted message so no false unread badge appears', async () => {
    await interjectIntoActiveTurn(CONV, 'one more thing');
    expect(incrementLocalMessageCount).toHaveBeenCalledWith(CONV, 1);
  });

  it('clears the composer and the conversation draft', async () => {
    useStore.getState().setConversationDraft(CONV, 'one more thing');

    await interjectIntoActiveTurn(CONV, 'one more thing');

    expect(clearMessageInput).toHaveBeenCalled();
    expect(useStore.getState().getConversationDraft(CONV)).toBe('');
    expect(toastMock.info).toHaveBeenCalledWith('Steering the current response…');
  });

  it('still records the steering when the messages view is not rendered', async () => {
    document.body.innerHTML = '';

    await interjectIntoActiveTurn(CONV, 'hidden view');

    expect(storeOrder()).toHaveLength(1);
    expect(clearMessageInput).toHaveBeenCalled();
  });

  it('keeps the text and shows an error when the server rejects it', async () => {
    api.interject.mockRejectedValue(new Error('409'));
    useStore.getState().setConversationDraft(CONV, 'too late');

    await interjectIntoActiveTurn(CONV, 'too late');

    expect(toastMock.error).toHaveBeenCalledWith('Failed to steer the response. Please wait for it to finish.');
    expect(storeOrder()).toEqual([]);
    expect(domOrder()).toEqual([]);
    expect(clearMessageInput).not.toHaveBeenCalled();
    expect(useStore.getState().getConversationDraft(CONV)).toBe('too late');
    expect(incrementLocalMessageCount).not.toHaveBeenCalled();
  });
});

describe('answerUnreadSteering', () => {
  function seed(): void {
    useStore.getState().appendMessage(CONV, msg('u1', 'user'));
    useStore.getState().appendMessage(CONV, msg('steer', 'user'));
    useStore.getState().appendMessage(CONV, msg('a1', 'assistant'));
    container().append(bubble('u1'), bubble('steer'), bubble('a1'));
  }

  function listenForAnswer(): Array<{ convId: string }> {
    const details: Array<{ convId: string }> = [];
    document.addEventListener(
      'message:answer-steering',
      (e) => details.push((e as CustomEvent<{ convId: string }>).detail),
      { once: true }
    );
    return details;
  }

  it('moves the steering after the reply in the store and on screen', () => {
    useStore.setState({ currentConversation: conv(CONV) });
    seed();

    answerUnreadSteering(CONV, 'steer');

    expect(storeOrder()).toEqual(['u1', 'a1', 'steer']);
    expect(domOrder()).toEqual(['u1', 'a1', 'steer']);
  });

  it('asks for a reply to the steering in the conversation on screen', () => {
    useStore.setState({ currentConversation: conv(CONV) });
    seed();
    const answered = listenForAnswer();

    answerUnreadSteering(CONV, 'steer');

    expect(answered).toEqual([{ convId: CONV }]);
  });

  it('still asks for a reply when the steering is not loaded', () => {
    useStore.setState({ currentConversation: conv(CONV) });
    useStore.getState().appendMessage(CONV, msg('a1', 'assistant'));
    const answered = listenForAnswer();

    answerUnreadSteering(CONV, 'missing');

    expect(storeOrder()).toEqual(['a1']);
    expect(answered).toEqual([{ convId: CONV }]);
  });

  it('leaves the steering last for the next turn in a conversation not on screen', () => {
    useStore.setState({ currentConversation: conv('other') });
    seed();
    const answered = listenForAnswer();

    answerUnreadSteering(CONV, 'steer');

    expect(storeOrder()).toEqual(['u1', 'steer', 'a1']);
    expect(domOrder()).toEqual(['u1', 'steer', 'a1']);
    expect(answered).toEqual([]);
  });
});
