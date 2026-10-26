/**
 * Deep-research stream events: the progress model lives on the streaming
 * state (events before the plan are ignored), the panel is drawn only while
 * the conversation is on screen, and the plan starts one ticker that redraws
 * the elapsed time every second into the current streaming bubble - skipped
 * while another conversation is shown, stopped for good once the turn's
 * active request ends.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

const ui = vi.hoisted(() => ({
  getStreamingMessageElement: vi.fn<(convId: string) => HTMLElement | null>(),
  renderResearchProgress: vi.fn(),
  tickResearchProgress: vi.fn(),
}));

vi.mock('@/components/messages', () => ({ getStreamingMessageElement: ui.getStreamingMessageElement }));
vi.mock('@/components/messages/research-progress', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/components/messages/research-progress')>();
  return {
    ...actual,
    renderResearchProgress: ui.renderResearchProgress,
    tickResearchProgress: ui.tickResearchProgress,
  };
});

import { useStore } from '@/state/store';
import { handleResearchEvent } from '@/core/research-stream';
import type { StreamingState } from '@/core/stream-session';
import type { Conversation } from '@/types/api';

const PLAN = { type: 'research_plan', items: ['Prices', 'Reviews'] };

function streamingState(messageId: string | null = 'a1'): StreamingState {
  return {
    messageEl: document.createElement('div'),
    expectedAssistantMessageId: messageId,
  } as unknown as StreamingState;
}

function open(id: string): void {
  const conv: Conversation = { id, title: id, model: 'm', created_at: '', updated_at: '' };
  useStore.getState().setCurrentConversation(conv);
}

describe('handleResearchEvent', () => {
  let bubble: HTMLElement;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    useStore.setState(useStore.getInitialState(), true);
    bubble = document.createElement('div');
    ui.getStreamingMessageElement.mockReturnValue(bubble);
    useStore.getState().setActiveRequest('c1', { conversationId: 'c1', type: 'stream' });
    open('c1');
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  it('ignores research events that arrive before the plan', () => {
    const state = streamingState();
    handleResearchEvent({ type: 'research_progress', index: 0 }, state, 'c1', true);
    expect(state.research).toBeUndefined();
    expect(ui.renderResearchProgress).not.toHaveBeenCalled();
  });

  it('builds the progress from the plan and draws it into the streaming message', () => {
    const state = streamingState();
    handleResearchEvent(PLAN, state, 'c1', true);
    expect(state.research?.items).toEqual(['Prices', 'Reviews']);
    expect(ui.renderResearchProgress).toHaveBeenCalledWith(state.messageEl, state.research, {
      convId: 'c1',
      messageId: 'a1',
    });
  });

  it('keeps the progress but draws nothing for a conversation that is not shown', () => {
    const state = streamingState();
    handleResearchEvent(PLAN, state, 'c1', false);
    expect(state.research).toBeDefined();
    expect(ui.renderResearchProgress).not.toHaveBeenCalled();
  });

  it('ticks the elapsed time every second into the current streaming bubble', () => {
    const state = streamingState(null);
    handleResearchEvent(PLAN, state, 'c1', true);

    vi.advanceTimersByTime(3000);

    expect(ui.tickResearchProgress).toHaveBeenCalledTimes(3);
    expect(ui.tickResearchProgress).toHaveBeenLastCalledWith(bubble, state.research, { convId: 'c1', messageId: '' });
    expect(ui.getStreamingMessageElement).toHaveBeenCalledWith('c1');
  });

  it('starts only one ticker however many plan events arrive', () => {
    const state = streamingState();
    handleResearchEvent(PLAN, state, 'c1', true);
    handleResearchEvent(PLAN, state, 'c1', true);

    vi.advanceTimersByTime(1000);

    expect(ui.tickResearchProgress).toHaveBeenCalledTimes(1);
  });

  it('skips ticks while another conversation is shown, and resumes on return', () => {
    const state = streamingState();
    handleResearchEvent(PLAN, state, 'c1', true);

    open('c2');
    vi.advanceTimersByTime(2000);
    expect(ui.tickResearchProgress).not.toHaveBeenCalled();

    open('c1');
    vi.advanceTimersByTime(1000);
    expect(ui.tickResearchProgress).toHaveBeenCalledTimes(1);
  });

  it('skips a tick when the bubble is not in the DOM', () => {
    ui.getStreamingMessageElement.mockReturnValue(null);
    handleResearchEvent(PLAN, streamingState(), 'c1', true);
    vi.advanceTimersByTime(1000);
    expect(ui.tickResearchProgress).not.toHaveBeenCalled();
  });

  it('stops ticking for good once the turn ends', () => {
    const state = streamingState();
    handleResearchEvent(PLAN, state, 'c1', true);

    useStore.getState().removeActiveRequest('c1');
    vi.advanceTimersByTime(1000);
    useStore.getState().setActiveRequest('c1', { conversationId: 'c1', type: 'stream' });
    vi.advanceTimersByTime(3000);

    expect(ui.tickResearchProgress).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('stops ticking once the progress is cleared from the state', () => {
    const state = streamingState();
    handleResearchEvent(PLAN, state, 'c1', true);
    state.research = undefined;

    vi.advanceTimersByTime(1000);

    expect(ui.tickResearchProgress).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
});
