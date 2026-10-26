/**
 * processStreamEvent: each live-stream event reaches its handler, UI updates
 * only for the visible conversation, and an error event ends the stream.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const ui = vi.hoisted(() => ({
  updateStreamingMessage: vi.fn(),
  updateStreamingThinking: vi.fn(),
  updateStreamingToolStart: vi.fn(),
  updateStreamingToolDetail: vi.fn(),
  updateStreamingToolEnd: vi.fn(),
  updateStreamingRetryStatus: vi.fn(),
  getStreamingMessageElement: vi.fn(() => null),
  updateUserMessageId: vi.fn(),
}));
const sync = vi.hoisted(() => ({ noteOwnMessageSaved: vi.fn() }));
const extras = vi.hoisted(() => ({
  showGroundingChecking: vi.fn(),
  notifyModelFallback: vi.fn(),
  handleResearchEvent: vi.fn(),
  addLiveArtifact: vi.fn(),
  acknowledgeServerStop: vi.fn(),
}));

vi.mock('@/components/messages', () => ui);
vi.mock('@/sync/SyncManager', () => ({ getSyncManager: () => sync }));
vi.mock('@/components/messages/grounding', () => ({ showGroundingChecking: extras.showGroundingChecking }));
vi.mock('@/core/model-fallback', () => ({ notifyModelFallback: extras.notifyModelFallback }));
vi.mock('@/core/research-stream', () => ({ handleResearchEvent: extras.handleResearchEvent }));
vi.mock('@/components/messages/artifacts', () => ({ addLiveArtifact: extras.addLiveArtifact }));
vi.mock('@/core/inflight-streams', () => ({ persistInflightStream: vi.fn() }));
vi.mock('@/core/stream-session', () => ({ acknowledgeServerStop: extras.acknowledgeServerStop }));

import { useStore } from '@/state/store';
import { ApiError } from '@/api/http';
import { processStreamEvent } from '@/core/stream-events';
import type { StreamingState } from '@/core/stream-session';
import { createThinkingState } from '@/core/thinking-state';

function makeState(): StreamingState {
  return {
    messageEl: document.createElement('div'),
    fullContent: '',
    thinkingState: createThinkingState(),
  } as unknown as StreamingState;
}

const conversation = (id: string) => ({ id, title: 'T', model: 'm', created_at: '', updated_at: '' }) as never;

describe('processStreamEvent', () => {
  let state: StreamingState;

  beforeEach(() => {
    vi.clearAllMocks();
    useStore.setState({ currentConversation: conversation('c1') });
    state = makeState();
  });

  it('appends tokens and renders them in the visible conversation', () => {
    processStreamEvent({ type: 'token', text: 'Hel' }, state, 'c1', 'temp-1');
    processStreamEvent({ type: 'token', text: 'lo' }, state, 'c1', 'temp-1');

    expect(state.fullContent).toBe('Hello');
    expect(state.thinkingState.isThinking).toBe(false);
    expect(ui.updateStreamingMessage).toHaveBeenLastCalledWith(state.messageEl, 'Hello');
  });

  it('keeps tokens off the DOM for a background conversation', () => {
    processStreamEvent({ type: 'token', text: 'Hi' }, state, 'other', 'temp-1');

    expect(state.fullContent).toBe('Hi');
    expect(ui.updateStreamingMessage).not.toHaveBeenCalled();
  });

  it('routes trace and research events to their handlers', () => {
    processStreamEvent({ type: 'tool_end', tool: 'search' }, state, 'c1', 'temp-1');
    expect(ui.updateStreamingToolEnd).toHaveBeenCalledWith('search');

    processStreamEvent({ type: 'research_plan', items: [] }, state, 'c1', 'temp-1');
    expect(extras.handleResearchEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'research_plan' }),
      state,
      'c1',
      true
    );
  });

  it('notes an own saved message, but not a followed stream\'s', () => {
    processStreamEvent({ type: 'user_message_saved', user_message_id: 'u1' }, state, 'c1', 'temp-1');
    expect(ui.updateUserMessageId).toHaveBeenCalledWith('temp-1', 'u1');
    expect(sync.noteOwnMessageSaved).toHaveBeenCalledWith('c1');

    sync.noteOwnMessageSaved.mockClear();
    state.remoteFollow = true;
    processStreamEvent({ type: 'user_message_saved', user_message_id: 'u2' }, state, 'c1', 'temp-1');
    expect(sync.noteOwnMessageSaved).not.toHaveBeenCalled();
  });

  it('shows notices only in the visible conversation', () => {
    processStreamEvent({ type: 'model_fallback', to: 'lite' }, state, 'c1', 'temp-1');
    processStreamEvent({ type: 'grounding_started' }, state, 'c1', 'temp-1');
    processStreamEvent({ type: 'retry', attempt: 2, max_retries: 3 }, state, 'c1', 'temp-1');
    expect(extras.notifyModelFallback).toHaveBeenCalledWith('lite');
    expect(extras.showGroundingChecking).toHaveBeenCalledWith(state.messageEl);
    expect(ui.updateStreamingRetryStatus).toHaveBeenCalledWith(2, 3);

    vi.clearAllMocks();
    processStreamEvent({ type: 'model_fallback', to: 'lite' }, state, 'other', 'temp-1');
    processStreamEvent({ type: 'grounding_started' }, state, 'other', 'temp-1');
    processStreamEvent({ type: 'retry', attempt: 2 }, state, 'other', 'temp-1');
    expect(extras.notifyModelFallback).not.toHaveBeenCalled();
    expect(extras.showGroundingChecking).not.toHaveBeenCalled();
    expect(ui.updateStreamingRetryStatus).not.toHaveBeenCalled();
  });

  it('acknowledges a server stop', () => {
    expect(processStreamEvent({ type: 'stopping' }, state, 'c1', 'temp-1')).toEqual({});
    expect(extras.acknowledgeServerStop).toHaveBeenCalledWith(state);
  });

  it('keeps an artifact with the turn and shows it live', () => {
    const addSpy = vi.spyOn(useStore.getState(), 'addActiveRequestArtifact');
    processStreamEvent({ type: 'artifact', id: 'a1', version: 2, title: 'Chart' }, state, 'c1', 'temp-1');

    const ref = { id: 'a1', version: 2, title: 'Chart' };
    expect(addSpy).toHaveBeenCalledWith('c1', ref);
    expect(extras.addLiveArtifact).toHaveBeenCalledWith(state.messageEl, ref);

    extras.addLiveArtifact.mockClear();
    processStreamEvent({ type: 'artifact', id: 'a1' }, state, 'c1', 'temp-1');
    expect(extras.addLiveArtifact).not.toHaveBeenCalled();
  });

  it('turns an error event into an ApiError and drops an empty bubble', () => {
    const parent = document.createElement('div');
    parent.appendChild(state.messageEl);

    const result = processStreamEvent(
      { type: 'error', message: 'Too slow', code: 'TIMEOUT', retryable: true },
      state,
      'c1',
      'temp-1'
    );

    expect(result.error).toBeInstanceOf(ApiError);
    expect(result.error).toMatchObject({ message: 'Too slow', status: 408, isTimeout: true, retryable: true });
    expect(state.serverError).toBe(true);
    expect(parent.children).toHaveLength(0);
  });

  it('ignores unknown and approval events without ending the stream', () => {
    expect(processStreamEvent({ type: 'approval_required', approval_id: 'x' }, state, 'c1', 'temp-1')).toEqual({});
    expect(processStreamEvent({ type: 'mystery' }, state, 'c1', 'temp-1')).toEqual({});
  });
});
