/**
 * Unit tests for background-attention signals: tab title counter and
 * PWA app badge when turns finish while the tab is hidden.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { initAttention, notifyTurnFinished, _resetAttention } from '@/core/attention';

function setHidden(hidden: boolean): void {
  Object.defineProperty(document, 'hidden', { value: hidden, configurable: true });
}

describe('attention signals', () => {
  let setBadge: ReturnType<typeof vi.fn>;
  let clearBadge: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    _resetAttention();
    document.title = 'AI Chatbot';
    setHidden(false);
    setBadge = vi.fn().mockResolvedValue(undefined);
    clearBadge = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'setAppBadge', { value: setBadge, configurable: true });
    Object.defineProperty(navigator, 'clearAppBadge', { value: clearBadge, configurable: true });
    initAttention();
  });

  it('prefixes the title and sets the app badge when hidden', () => {
    setHidden(true);
    notifyTurnFinished();
    expect(document.title).toBe('(1) AI Chatbot');
    expect(setBadge).toHaveBeenCalledWith(1);
  });

  it('accumulates a count across multiple finishes', () => {
    setHidden(true);
    notifyTurnFinished();
    notifyTurnFinished();
    expect(document.title).toBe('(2) AI Chatbot');
    expect(setBadge).toHaveBeenLastCalledWith(2);
  });

  it('does nothing while the tab is visible', () => {
    notifyTurnFinished();
    expect(document.title).toBe('AI Chatbot');
    expect(setBadge).not.toHaveBeenCalled();
  });

  it('clears title and badge when the tab becomes visible', () => {
    setHidden(true);
    notifyTurnFinished();
    setHidden(false);
    document.dispatchEvent(new Event('visibilitychange'));
    expect(document.title).toBe('AI Chatbot');
    expect(clearBadge).toHaveBeenCalled();
  });
});
