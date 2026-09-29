/**
 * "Model busy - retrying" status during transient-error backoff.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  addStreamingMessage,
  cleanupStreamingContext,
  updateStreamingRetryStatus,
  updateStreamingThinking,
  updateStreamingToolStart,
} from '@/components/messages/streaming';

function note(): HTMLElement | null {
  return document.querySelector('.streaming-retry-status');
}

describe('streaming retry status', () => {
  beforeEach(() => {
    // jsdom has no layout/scrolling
    Element.prototype.scrollTo = vi.fn() as unknown as typeof Element.prototype.scrollTo;
    cleanupStreamingContext();
    document.body.innerHTML = '<div id="messages"></div>';
    addStreamingMessage('conv-1');
  });

  it('shows the attempt inside the thinking indicator', () => {
    updateStreamingRetryStatus(2, 3);
    expect(note()?.textContent).toContain('retrying (attempt 2 of 3)');
    expect(note()?.closest('.thinking-indicator')).not.toBeNull();
  });

  it('updates in place rather than stacking', () => {
    updateStreamingRetryStatus(1, 3);
    updateStreamingRetryStatus(2, 3);
    expect(document.querySelectorAll('.streaming-retry-status')).toHaveLength(1);
  });

  it('clears once the model makes progress', () => {
    updateStreamingRetryStatus(1, 3);
    updateStreamingThinking('Looking into it');
    expect(note()).toBeNull();

    updateStreamingRetryStatus(1, 3);
    updateStreamingToolStart('web_search');
    expect(note()).toBeNull();
  });

  it('survives indicator re-renders while still retrying', () => {
    updateStreamingRetryStatus(1, 3);
    // A re-render of the trace must not wipe the status line
    const indicator = document.querySelector('.thinking-indicator-content');
    if (indicator) indicator.innerHTML = '<div class="thinking-trace"></div>';
    expect(note()).not.toBeNull();
  });
});
