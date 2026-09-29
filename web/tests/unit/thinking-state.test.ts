/**
 * Unit tests for the per-stream thinking/tool trace state
 */
import { describe, it, expect } from 'vitest';
import {
  createThinkingState,
  deepCopyThinkingState,
  updateLocalThinkingState,
} from '@/core/thinking-state';

describe('thinking-state', () => {
  it('starts thinking with an empty trace', () => {
    expect(createThinkingState()).toEqual({
      isThinking: true,
      thinkingText: '',
      activeTool: null,
      activeToolDetail: undefined,
      completedTools: [],
      trace: [],
    });
  });

  it('keeps a single thinking item, updated in place', () => {
    const state = createThinkingState();
    updateLocalThinkingState(state, 'thinking', 'first');
    updateLocalThinkingState(state, 'thinking', 'second');
    expect(state.trace).toEqual([
      { type: 'thinking', label: 'thinking', detail: 'second', completed: false },
    ]);
    expect(state.thinkingText).toBe('second');
    expect(state.isThinking).toBe(true);
  });

  it('inserts tools before the thinking item and completes it', () => {
    const state = createThinkingState();
    updateLocalThinkingState(state, 'thinking', 'planning');
    updateLocalThinkingState(state, 'tool_start', 'web_search', 'cats', { query: 'cats' } as never);
    expect(state.trace.map((i) => i.type)).toEqual(['tool', 'thinking']);
    expect(state.trace[1].completed).toBe(true);
    expect(state.trace[0]).toMatchObject({ label: 'web_search', detail: 'cats', completed: false });
    expect(state.activeTool).toBe('web_search');
    expect(state.isThinking).toBe(false);
  });

  it('updates detail of the running tool and completes it on end', () => {
    const state = createThinkingState();
    updateLocalThinkingState(state, 'tool_start', 'fetch', 'a');
    updateLocalThinkingState(state, 'tool_detail', 'fetch', undefined, undefined);
    updateLocalThinkingState(state, 'tool_detail', 'fetch', 'b');
    expect(state.trace[0].detail).toBe('b');
    expect(state.activeToolDetail).toBe('b');

    updateLocalThinkingState(state, 'tool_end', 'fetch');
    updateLocalThinkingState(state, 'tool_end', 'fetch');
    expect(state.trace[0].completed).toBe(true);
    expect(state.completedTools).toEqual(['fetch']);
    expect(state.activeTool).toBeNull();
    expect(state.activeToolDetail).toBeUndefined();
  });

  it('deep copies so later mutations do not leak into a snapshot', () => {
    const state = createThinkingState();
    updateLocalThinkingState(state, 'tool_start', 'fetch', 'a');
    const copy = deepCopyThinkingState(state);
    updateLocalThinkingState(state, 'tool_end', 'fetch');
    expect(copy.trace[0].completed).toBe(false);
    expect(copy.completedTools).toEqual([]);
  });
});
