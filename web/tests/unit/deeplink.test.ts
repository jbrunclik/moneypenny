/**
 * Unit tests for deep linking module
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  parseHash,
  getConversationIdFromHash,
  setConversationHash,
  clearConversationHash,
  initDeepLinking,
  cleanupDeepLinking,
  isValidConversationId,
  setPlannerHash,
} from '@/router/deeplink';

describe('parseHash', () => {
  it('parses empty hash as home', () => {
    expect(parseHash('')).toEqual({ type: 'home' });
    expect(parseHash('#')).toEqual({ type: 'home' });
    expect(parseHash('#/')).toEqual({ type: 'home' });
  });

  it('parses conversation hash', () => {
    const result = parseHash('#/conversations/conv-123-abc');
    expect(result).toEqual({
      type: 'conversation',
      conversationId: 'conv-123-abc',
    });
  });

  it('parses conversation hash without leading #', () => {
    const result = parseHash('/conversations/conv-123-abc');
    expect(result).toEqual({
      type: 'conversation',
      conversationId: 'conv-123-abc',
    });
  });

  it('parses UUID conversation ID', () => {
    const result = parseHash('#/conversations/550e8400-e29b-41d4-a716-446655440000');
    expect(result).toEqual({
      type: 'conversation',
      conversationId: '550e8400-e29b-41d4-a716-446655440000',
    });
  });

  it('ignores temp conversation IDs', () => {
    const result = parseHash('#/conversations/temp-12345678');
    expect(result).toEqual({ type: 'home' });
  });

  it('returns unknown for invalid paths', () => {
    expect(parseHash('#/invalid')).toEqual({ type: 'unknown' });
    expect(parseHash('#/conversations/')).toEqual({ type: 'unknown' });
    expect(parseHash('#/conversations/id/extra')).toEqual({ type: 'unknown' });
  });

  it('parses planner hash', () => {
    expect(parseHash('#/planner')).toEqual({ type: 'planner' });
    expect(parseHash('/planner')).toEqual({ type: 'planner' });
  });

  it('returns unknown for planner with extra path', () => {
    expect(parseHash('#/planner/extra')).toEqual({ type: 'unknown' });
  });
});

describe('getConversationIdFromHash', () => {
  const originalLocation = window.location;

  beforeEach(() => {
    // Reset location mock
    delete (window as Record<string, unknown>).location;
    (window as Record<string, unknown>).location = {
      ...originalLocation,
      hash: '',
    };
  });

  afterEach(() => {
    (window as Record<string, unknown>).location = originalLocation;
  });

  it('returns conversation ID from hash', () => {
    window.location.hash = '#/conversations/conv-123';
    expect(getConversationIdFromHash()).toBe('conv-123');
  });

  it('returns null for empty hash', () => {
    window.location.hash = '';
    expect(getConversationIdFromHash()).toBeNull();
  });

  it('returns null for temp conversation', () => {
    window.location.hash = '#/conversations/temp-123';
    expect(getConversationIdFromHash()).toBeNull();
  });

  it('returns null for invalid hash', () => {
    window.location.hash = '#/invalid';
    expect(getConversationIdFromHash()).toBeNull();
  });
});

describe('setConversationHash', () => {
  const originalLocation = window.location;
  let pushStateSpy: ReturnType<typeof vi.spyOn>;
  let replaceStateSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    // Reset location mock
    delete (window as Record<string, unknown>).location;
    (window as Record<string, unknown>).location = {
      ...originalLocation,
      hash: '',
      pathname: '/',
    };
    pushStateSpy = vi.spyOn(history, 'pushState');
    replaceStateSpy = vi.spyOn(history, 'replaceState');
  });

  afterEach(() => {
    (window as Record<string, unknown>).location = originalLocation;
    pushStateSpy.mockRestore();
    replaceStateSpy.mockRestore();
  });

  it('sets hash for valid conversation ID', () => {
    setConversationHash('conv-123');
    expect(pushStateSpy).toHaveBeenCalledWith(null, '', '#/conversations/conv-123');
  });

  it('uses replaceState when replace option is true', () => {
    setConversationHash('conv-123', { replace: true });
    expect(replaceStateSpy).toHaveBeenCalledWith(null, '', '#/conversations/conv-123');
    expect(pushStateSpy).not.toHaveBeenCalled();
  });

  it('clears hash when null is passed', () => {
    window.location.hash = '#/conversations/conv-123';
    setConversationHash(null);
    expect(pushStateSpy).toHaveBeenCalledWith(null, '', '/');
  });

  it('skips temp conversation IDs', () => {
    setConversationHash('temp-12345');
    expect(pushStateSpy).not.toHaveBeenCalled();
    expect(replaceStateSpy).not.toHaveBeenCalled();
  });

  it('does not update if hash is unchanged', () => {
    window.location.hash = '#/conversations/conv-123';
    setConversationHash('conv-123');
    expect(pushStateSpy).not.toHaveBeenCalled();
    expect(replaceStateSpy).not.toHaveBeenCalled();
  });
});

describe('clearConversationHash', () => {
  let replaceStateSpy: ReturnType<typeof vi.spyOn>;
  const originalLocation = window.location;

  beforeEach(() => {
    delete (window as Record<string, unknown>).location;
    (window as Record<string, unknown>).location = {
      ...originalLocation,
      hash: '#/conversations/conv-123',
      pathname: '/',
    };
    replaceStateSpy = vi.spyOn(history, 'replaceState');
  });

  afterEach(() => {
    (window as Record<string, unknown>).location = originalLocation;
    replaceStateSpy.mockRestore();
  });

  it('clears hash using replaceState', () => {
    clearConversationHash();
    expect(replaceStateSpy).toHaveBeenCalledWith(null, '', '/');
  });
});

describe('setPlannerHash', () => {
  const originalLocation = window.location;
  let pushStateSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    delete (window as Record<string, unknown>).location;
    (window as Record<string, unknown>).location = {
      ...originalLocation,
      hash: '',
      pathname: '/',
    };
    pushStateSpy = vi.spyOn(history, 'pushState');
  });

  afterEach(() => {
    (window as Record<string, unknown>).location = originalLocation;
    pushStateSpy.mockRestore();
  });

  it('sets hash to planner route', () => {
    setPlannerHash();
    expect(pushStateSpy).toHaveBeenCalledWith(null, '', '#/planner');
  });

  it('does not update if already on planner hash', () => {
    window.location.hash = '#/planner';
    setPlannerHash();
    expect(pushStateSpy).not.toHaveBeenCalled();
  });
});

describe('initDeepLinking and cleanupDeepLinking', () => {
  const originalLocation = window.location;
  let addEventListenerSpy: ReturnType<typeof vi.spyOn>;
  let removeEventListenerSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    delete (window as Record<string, unknown>).location;
    (window as Record<string, unknown>).location = {
      ...originalLocation,
      hash: '',
    };
    addEventListenerSpy = vi.spyOn(window, 'addEventListener');
    removeEventListenerSpy = vi.spyOn(window, 'removeEventListener');
  });

  afterEach(() => {
    cleanupDeepLinking();
    (window as Record<string, unknown>).location = originalLocation;
    addEventListenerSpy.mockRestore();
    removeEventListenerSpy.mockRestore();
  });

  it('returns null conversationId when no conversation in hash', () => {
    const callback = vi.fn();
    const result = initDeepLinking(callback);
    expect(result).toEqual({ conversationId: null, isPlanner: false, isAgents: false });
  });

  it('returns conversation ID when present in hash', () => {
    window.location.hash = '#/conversations/conv-123';
    const callback = vi.fn();
    const result = initDeepLinking(callback);
    expect(result).toEqual({ conversationId: 'conv-123', isPlanner: false, isAgents: false });
  });

  it('returns planner route info when on planner hash', () => {
    window.location.hash = '#/planner';
    const callback = vi.fn();
    const result = initDeepLinking(callback);
    expect(result).toEqual({ conversationId: null, isPlanner: true, isAgents: false });
  });

  it('registers hashchange listener', () => {
    const callback = vi.fn();
    initDeepLinking(callback);
    expect(addEventListenerSpy).toHaveBeenCalledWith('hashchange', expect.any(Function));
  });

  it('cleanupDeepLinking removes listener', () => {
    const callback = vi.fn();
    initDeepLinking(callback);
    cleanupDeepLinking();
    expect(removeEventListenerSpy).toHaveBeenCalledWith('hashchange', expect.any(Function));
  });
});

describe('isValidConversationId', () => {
  it('returns true for valid UUIDs', () => {
    expect(isValidConversationId('550e8400-e29b-41d4-a716-446655440000')).toBe(true);
  });

  it('returns true for alphanumeric IDs', () => {
    expect(isValidConversationId('conv-123-abc')).toBe(true);
    expect(isValidConversationId('ABC123')).toBe(true);
  });

  it('returns false for empty string', () => {
    expect(isValidConversationId('')).toBe(false);
  });

  it('returns false for very long IDs', () => {
    const longId = 'a'.repeat(101);
    expect(isValidConversationId(longId)).toBe(false);
  });

  it('returns false for IDs with invalid characters', () => {
    expect(isValidConversationId('conv/123')).toBe(false);
    expect(isValidConversationId('conv 123')).toBe(false);
    expect(isValidConversationId('conv@123')).toBe(false);
    expect(isValidConversationId('<script>')).toBe(false);
  });
});

describe('hashchange event handling', () => {
  const originalLocation = window.location;

  beforeEach(() => {
    delete (window as Record<string, unknown>).location;
    (window as Record<string, unknown>).location = {
      ...originalLocation,
      hash: '',
    };
  });

  afterEach(() => {
    cleanupDeepLinking();
    (window as Record<string, unknown>).location = originalLocation;
  });

  it('calls callback with conversation ID on hashchange', async () => {
    const callback = vi.fn();
    initDeepLinking(callback);

    // Simulate hash change to a conversation
    window.location.hash = '#/conversations/conv-456';
    window.dispatchEvent(new HashChangeEvent('hashchange'));

    // Wait for async handling
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(callback).toHaveBeenCalledWith('conv-456', false, false);
  });

  it('calls callback with null for non-conversation hash', async () => {
    const callback = vi.fn();
    initDeepLinking(callback);

    // Simulate hash change to home
    window.location.hash = '';
    window.dispatchEvent(new HashChangeEvent('hashchange'));

    // Wait for async handling
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(callback).toHaveBeenCalledWith(null, false, false);
  });

  it('calls callback with isPlanner=true for planner hash', async () => {
    const callback = vi.fn();
    initDeepLinking(callback);

    // Simulate hash change to planner
    window.location.hash = '#/planner';
    window.dispatchEvent(new HashChangeEvent('hashchange'));

    // Wait for async handling
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(callback).toHaveBeenCalledWith(null, true, false);
  });

  it('ignores hashchange during programmatic updates', async () => {
    const callback = vi.fn();
    initDeepLinking(callback);

    // Programmatically set hash
    setConversationHash('conv-789');

    // The programmatic change should be ignored
    // Wait for the ignore flag to clear
    await new Promise((resolve) => setTimeout(resolve, 10));

    // Callback should not have been called (programmatic changes are ignored)
    expect(callback).not.toHaveBeenCalledWith('conv-789', false, false);
  });
});

