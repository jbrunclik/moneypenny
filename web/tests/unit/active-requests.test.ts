/**
 * Unit tests for active request (abort handle) tracking
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import {
  abortAllStreamingRequests,
  abortStreamingRequest,
  handleStopStreaming,
  setStopHandler,
  swapAbortController,
  trackRequest,
  untrackRequest,
} from '@/core/active-requests';
import { persistInflightStream, readInflightStream } from '@/core/inflight-streams';

describe('active-requests', () => {
  beforeEach(() => {
    abortAllStreamingRequests();
    localStorage.clear();
    useStore.setState({ currentConversation: null });
  });

  it('aborts only the stream of the given conversation', () => {
    const a = new AbortController();
    const b = new AbortController();
    trackRequest('r1', { conversationId: 'c1', type: 'stream', abortController: a });
    trackRequest('r2', { conversationId: 'c2', type: 'stream', abortController: b });

    expect(abortStreamingRequest('c1')).toBe(true);
    expect(a.signal.aborted).toBe(true);
    expect(b.signal.aborted).toBe(false);
  });

  it('ignores batch and untracked requests', () => {
    trackRequest('r1', { conversationId: 'c1', type: 'batch' });
    const s = new AbortController();
    trackRequest('r2', { conversationId: 'c2', type: 'stream', abortController: s });
    untrackRequest('r2');
    expect(abortStreamingRequest('c1')).toBe(false);
    expect(abortStreamingRequest('c2')).toBe(false);
    expect(s.signal.aborted).toBe(false);
  });

  it('stop targets the swapped-in controller of a resumed reader', () => {
    const initial = new AbortController();
    const resumed = new AbortController();
    trackRequest('r1', { conversationId: 'c1', type: 'stream', abortController: initial });
    swapAbortController('c1', resumed);
    useStore.setState({ currentConversation: { id: 'c1' } as never });

    handleStopStreaming();
    expect(resumed.signal.aborted).toBe(true);
    expect(initial.signal.aborted).toBe(false);
  });

  it('abortAll aborts every request and drops resume entries', () => {
    const a = new AbortController();
    trackRequest('r1', { conversationId: 'c1', type: 'stream', abortController: a });
    persistInflightStream('c1', 'm1');

    abortAllStreamingRequests();
    expect(a.signal.aborted).toBe(true);
    expect(readInflightStream('c1')).toBeNull();
    expect(abortStreamingRequest('c1')).toBe(false);
  });

  it('marks the conversation stopping once a graceful stop is accepted', () => {
    trackRequest('r1', { conversationId: 'c1', type: 'stream', abortController: new AbortController() });
    useStore.getState().setActiveRequest('c1', { conversationId: 'c1', type: 'stream' });
    setStopHandler('c1', () => true);
    useStore.setState({ currentConversation: { id: 'c1' } as never });

    handleStopStreaming();

    expect(useStore.getState().getActiveRequest('c1')?.stopping).toBe(true);
  });

  it('does not mark stopping when Stop falls back to aborting', () => {
    trackRequest('r1', { conversationId: 'c1', type: 'stream', abortController: new AbortController() });
    useStore.getState().setActiveRequest('c1', { conversationId: 'c1', type: 'stream' });
    setStopHandler('c1', () => false);
    useStore.setState({ currentConversation: { id: 'c1' } as never });

    handleStopStreaming();

    expect(useStore.getState().getActiveRequest('c1')?.stopping).toBeFalsy();
  });

  it('lets the stream stop gracefully when its handler accepts', () => {
    const controller = new AbortController();
    trackRequest('r1', { conversationId: 'c1', type: 'stream', abortController: controller });
    const handler = vi.fn(() => true);
    setStopHandler('c1', handler);
    useStore.setState({ currentConversation: { id: 'c1' } as never });

    handleStopStreaming();

    expect(handler).toHaveBeenCalledTimes(1);
    expect(controller.signal.aborted).toBe(false);
  });

  it('aborts immediately when the turn has not started', () => {
    const controller = new AbortController();
    trackRequest('r1', { conversationId: 'c1', type: 'stream', abortController: controller });
    setStopHandler('c1', () => false);
    useStore.setState({ currentConversation: { id: 'c1' } as never });

    handleStopStreaming();

    expect(controller.signal.aborted).toBe(true);
  });
});
