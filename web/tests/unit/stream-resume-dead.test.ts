/**
 * A turn whose worker died (a restart mid-turn): the resume endpoint answers
 * RESUME_FAILED - nothing was saved and nothing will be. Oct 2026: the client
 * then polled for a minute and dropped the bubble without a word, the chat
 * ending on the user's question with no way to retry. It must offer the
 * re-run right away, as for a turn the server reported failed.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/components/messages', () => ({
  addStreamingMessage: vi.fn(),
  getStreamingMessageElement: vi.fn(() => null),
  cleanupStreamingContext: vi.fn(),
}));
vi.mock('@/components/Toast', () => ({ toast: { info: vi.fn(), warning: vi.fn(), error: vi.fn() } }));
vi.mock('@/components/MessageInput', () => ({ hideUploadProgress: vi.fn(), showUploadProgress: vi.fn() }));
vi.mock('@/core/stream-recovery', () => ({
  markStreamForRecovery: vi.fn(),
  clearPendingRecovery: vi.fn(),
  attemptRecovery: vi.fn(async () => false),
}));
vi.mock('@/api/chat', () => ({
  chat: {

    resumeStream: vi.fn(async function* () {
      yield { type: 'error', code: 'RESUME_FAILED', message: 'The stream made no progress and appears to be dead.' };
    }),
  },
}));

import { toast } from '@/components/Toast';
import { attemptRecovery } from '@/core/stream-recovery';
import { useStore } from '@/state/store';
import { createStreamingState, registerStreamRequest } from '@/core/stream-session';
import { deliverResumedTurn, handleMissingDoneEvent, offerLostReplyRetry } from '@/core/stream-resume';

function deadTurnState() {
  const el = document.createElement('div');
  document.body.appendChild(el);
  const state = createStreamingState(el, {
    expectedAssistantMessageId: 'm1',
    activeAbortController: new AbortController(),
  });
  return { state, el };
}

function retryActionOfLastErrorToast(): { label: string; onClick: () => void } | undefined {
  const calls = vi.mocked(toast.error).mock.calls;
  const options = calls[calls.length - 1]?.[1] as { action?: { label: string; onClick: () => void } } | undefined;
  return options?.action;
}

describe('a dead turn offers a retry', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStore.getState().setCurrentConversation({
      id: 'c1',
      title: 'Chat',
      model: 'm',
      created_at: '2026-10-13T17:35:17',
      updated_at: '2026-10-13T17:35:17',
      messages: [],
    });
  });

  it('after a reload: drops the bubble and offers Retry, no poll recovery', async () => {
    const { state, el } = deadTurnState();

    expect(await deliverResumedTurn(state, 'c1', 'm1', el)).toBe(false);

    expect(el.isConnected).toBe(false);
    expect(attemptRecovery).not.toHaveBeenCalled();
    const retry = retryActionOfLastErrorToast();
    expect(retry?.label).toBe('Retry');
    const dispatched = vi.fn();
    document.addEventListener('message:retry-reply', dispatched);
    retry?.onClick();
    expect(dispatched).toHaveBeenCalledOnce();
  });

  it('another device’s dead turn: just drops the bubble', async () => {
    const { state, el } = deadTurnState();

    expect(await deliverResumedTurn(state, 'c1', 'm1', el, { remote: true })).toBe(false);

    expect(el.isConnected).toBe(false);
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('a live stream that ended without done: offers Retry, no poll recovery', async () => {
    const { state, el } = deadTurnState();

    await handleMissingDoneEvent(state, 'c1', 'temp-user');

    expect(el.isConnected).toBe(false);
    expect(attemptRecovery).not.toHaveBeenCalled();
    expect(retryActionOfLastErrorToast()?.label).toBe('Retry');
  });
});

describe('opening a chat whose last turn died', () => {
  const conv = {
    id: 'c2',
    title: 'Chat',
    model: 'm',
    created_at: '2026-10-13T17:35:17',
    updated_at: '2026-10-13T17:35:17',
    messages: [],
  };

  beforeEach(() => vi.clearAllMocks());

  it('offers Retry when the server reports the reply lost', () => {
    offerLostReplyRetry({ ...conv, lost_reply: true });
    expect(retryActionOfLastErrorToast()?.label).toBe('Retry');
  });

  it('says nothing for a chat whose reply is not lost', () => {
    offerLostReplyRetry({ ...conv, lost_reply: false });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('says nothing while this tab is already answering it', () => {
    registerStreamRequest('c2', 'req-1', new AbortController());
    offerLostReplyRetry({ ...conv, lost_reply: true });
    expect(toast.error).not.toHaveBeenCalled();
  });
});
