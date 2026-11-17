/**
 * Unit tests for background-attention signals: tab title counter and
 * PWA app badge when turns finish while the tab is hidden.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { initAttention, notifyTurnFinished, titleFor, _resetAttention } from '@/core/attention';
import { useStore } from '@/state/store';

function setHidden(hidden: boolean): void {
  Object.defineProperty(document, 'hidden', { value: hidden, configurable: true });
}

describe('attention signals', () => {
  let setBadge: ReturnType<typeof vi.fn>;
  let clearBadge: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    _resetAttention();
    useStore.setState({ currentConversation: null });
    document.title = 'Moneypenny';
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
    expect(document.title).toBe('(1) Moneypenny');
    expect(setBadge).toHaveBeenCalledWith(1);
  });

  it('accumulates a count across multiple finishes', () => {
    setHidden(true);
    notifyTurnFinished();
    notifyTurnFinished();
    expect(document.title).toBe('(2) Moneypenny');
    expect(setBadge).toHaveBeenLastCalledWith(2);
  });

  it('does nothing while the tab is visible', () => {
    notifyTurnFinished();
    expect(document.title).toBe('Moneypenny');
    expect(setBadge).not.toHaveBeenCalled();
  });

  it('clears title and badge when the tab becomes visible', () => {
    setHidden(true);
    notifyTurnFinished();
    setHidden(false);
    document.dispatchEvent(new Event('visibilitychange'));
    expect(document.title).toBe('Moneypenny');
    expect(clearBadge).toHaveBeenCalled();
  });

  it('names the window after the open conversation, counter first', () => {
    useStore.setState({ currentConversation: { id: 'c1', title: 'Trip to Vienna' } as never });
    expect(document.title).toBe('Trip to Vienna · Moneypenny');

    setHidden(true);
    notifyTurnFinished();
    expect(document.title).toBe('(1) Trip to Vienna · Moneypenny');

    useStore.setState({ currentConversation: null });
    expect(document.title).toBe('(1) Moneypenny');
  });

  it('leaves an anonymous chat unnamed', () => {
    useStore.setState({
      currentConversation: { id: 'c2', title: 'Private matter' } as never,
      anonymousModeByConversation: new Map([['c2', true]]),
    });
    expect(document.title).toBe('Moneypenny');
    useStore.setState({ anonymousModeByConversation: new Map() });
  });

  it('shows only the app name without a title', () => {
    expect(titleFor('  ')).toBe('Moneypenny');
    expect(titleFor(undefined)).toBe('Moneypenny');
  });
});
