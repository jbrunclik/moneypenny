/**
 * Server-side Stop from the client: the stop request names the turn, a grace
 * timer aborts the reader if the server never answers, and the server's
 * "stopping" acknowledgment cancels that timer (long tools emit no events).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

const { stop } = vi.hoisted(() => ({ stop: vi.fn(() => Promise.resolve()) }));
vi.mock('@/api/conversations', () => ({ conversations: { stop } }));
vi.mock('@/components/messages', () => ({
  addStreamingMessage: vi.fn(),
  cleanupStreamingContext: vi.fn(),
}));
vi.mock('@/components/MessageInput', () => ({
  hideUploadProgress: vi.fn(),
  showUploadProgress: vi.fn(),
}));

import { STOP_DONE_GRACE_MS } from '@/config';
import {
  acknowledgeServerStop,
  createStreamingState,
  requestServerStop,
} from '@/core/stream-session';

function liveState(messageId: string | null) {
  const controller = new AbortController();
  const state = createStreamingState(document.createElement('div'), {
    expectedAssistantMessageId: messageId,
    activeAbortController: controller,
  });
  return { state, controller };
}

describe('server-side stop', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    stop.mockClear();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('asks the server to stop THIS turn and keeps reading', () => {
    const { state, controller } = liveState('msg-1');
    expect(requestServerStop('c1', state)).toBe(true);
    expect(stop).toHaveBeenCalledWith('c1', 'msg-1');
    expect(controller.signal.aborted).toBe(false);
  });

  it('cannot stop server-side before the server acked the turn', () => {
    const { state } = liveState(null);
    expect(requestServerStop('c1', state)).toBe(false);
    expect(stop).not.toHaveBeenCalled();
  });

  it('a second Stop click does not send another request', () => {
    const { state } = liveState('msg-1');
    requestServerStop('c1', state);
    requestServerStop('c1', state);
    expect(stop).toHaveBeenCalledTimes(1);
  });

  it('aborts the reader when no answer arrives within the grace period', () => {
    const { state, controller } = liveState('msg-1');
    requestServerStop('c1', state);
    vi.advanceTimersByTime(STOP_DONE_GRACE_MS + 1);
    expect(controller.signal.aborted).toBe(true);
  });

  it('the server acknowledgment cancels the grace abort', () => {
    const { state, controller } = liveState('msg-1');
    requestServerStop('c1', state);
    acknowledgeServerStop(state);
    vi.advanceTimersByTime(STOP_DONE_GRACE_MS * 3);
    expect(controller.signal.aborted).toBe(false);
  });
});
