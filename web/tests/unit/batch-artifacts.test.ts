import { describe, expect, it } from 'vitest';
import { toAssistantMessage } from '@/core/batch-send';
import type { ChatResponse } from '@/types/api';

describe('batch reply mapping', () => {
  it('keeps the reply’s artifacts, as the streamed done does', () => {
    const response = {
      id: 'm1',
      role: 'assistant',
      content: 'Here it is.',
      created_at: '2026-10-11T12:00:00',
      artifacts: [{ id: 'a', version: 1, title: 'Tips' }],
    } as ChatResponse;
    expect(toAssistantMessage(response).artifacts).toEqual([{ id: 'a', version: 1, title: 'Tips' }]);
  });

  it('keeps the fallback model, so the reply shows its note', () => {
    const response = {
      id: 'm1',
      role: 'assistant',
      content: 'Hi',
      created_at: '2026-11-26T12:00:00',
      model_fallback: 'gemini-4-hydrogen',
    } as ChatResponse;
    expect(toAssistantMessage(response).model_fallback).toBe('gemini-4-hydrogen');
  });

  it('keeps why the reply stopped, so a re-render shows the same note', () => {
    const response = {
      id: 'm1',
      role: 'assistant',
      content: 'Partial',
      created_at: '2026-10-11T12:00:00',
      stopped_early: null,
      stop_reason: 'user',
    } as ChatResponse;
    expect(toAssistantMessage(response).stop_reason).toBe('user');
  });
});
