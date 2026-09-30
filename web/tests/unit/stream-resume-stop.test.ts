/**
 * A server-side Stop on a reload-resumed turn whose done never arrived: the
 * grace abort must keep the partial bubble, like the live stream does.
 */
import { describe, it, expect, vi } from 'vitest';

vi.mock('@/components/messages', () => ({
  addStreamingMessage: vi.fn(),
  getStreamingMessageElement: vi.fn(() => null),
  cleanupStreamingContext: vi.fn(),
}));
vi.mock('@/components/Toast', () => ({ toast: { info: vi.fn(), warning: vi.fn(), error: vi.fn() } }));
vi.mock('@/components/MessageInput', () => ({ hideUploadProgress: vi.fn(), showUploadProgress: vi.fn() }));

// jsdom's DOMException is not `instanceof Error` (browsers' is), which the
// AbortError checks rely on - install a browser-like one for this test
class BrowserDOMException extends Error {
  constructor(message: string, name: string) {
    super(message);
    this.name = name;
  }
}
vi.stubGlobal('DOMException', BrowserDOMException);

import { createStreamingState } from '@/core/stream-session';
import { deliverResumedTurn } from '@/core/stream-resume';

function abortedState(stopRequested: boolean) {
  const el = document.createElement('div');
  document.body.appendChild(el);
  const controller = new AbortController();
  controller.abort();
  const state = createStreamingState(el, {
    expectedAssistantMessageId: 'm1',
    activeAbortController: controller,
    stopRequested,
  });
  return { state, el };
}

describe('deliverResumedTurn abort', () => {
  it('keeps the partial when a server-side stop was requested', async () => {
    const { state, el } = abortedState(true);
    expect(await deliverResumedTurn(state, 'c1', 'm1', el)).toBe('stopped');
    expect(el.isConnected).toBe(true);
    expect(el.classList.contains('message-incomplete')).toBe(true);
  });

  it('still removes the bubble for a plain client-side abort', async () => {
    const { state, el } = abortedState(false);
    expect(await deliverResumedTurn(state, 'c1', 'm1', el)).toBe('stopped');
    expect(el.isConnected).toBe(false);
  });
});
