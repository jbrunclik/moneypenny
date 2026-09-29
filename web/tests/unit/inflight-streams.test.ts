/**
 * Unit tests for in-flight stream persistence (reload-resume bookkeeping)
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  INFLIGHT_STREAM_MAX_AGE_MS,
  clearAllInflightStreams,
  clearInflightStream,
  persistInflightStream,
  readInflightStream,
} from '@/core/inflight-streams';

const KEY = 'inflight-streams';

describe('inflight-streams', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-29T12:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('round-trips an entry per conversation', () => {
    persistInflightStream('c1', 'm1');
    persistInflightStream('c2', 'm2');
    expect(readInflightStream('c1')).toEqual({ messageId: 'm1', ts: Date.now() });
    expect(readInflightStream('c2')?.messageId).toBe('m2');
    expect(readInflightStream('c3')).toBeNull();
  });

  it('clearing one conversation keeps concurrent streams', () => {
    persistInflightStream('c1', 'm1');
    persistInflightStream('c2', 'm2');
    clearInflightStream('c1');
    expect(readInflightStream('c1')).toBeNull();
    expect(readInflightStream('c2')?.messageId).toBe('m2');
  });

  it('removes the storage key once the map is empty', () => {
    persistInflightStream('c1', 'm1');
    clearInflightStream('c1');
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it('expires entries older than the max age', () => {
    persistInflightStream('c1', 'm1');
    vi.advanceTimersByTime(INFLIGHT_STREAM_MAX_AGE_MS);
    expect(readInflightStream('c1')?.messageId).toBe('m1');
    vi.advanceTimersByTime(1);
    expect(readInflightStream('c1')).toBeNull();
  });

  it('prunes expired entries on write', () => {
    persistInflightStream('old', 'm1');
    vi.advanceTimersByTime(INFLIGHT_STREAM_MAX_AGE_MS + 1);
    persistInflightStream('new', 'm2');
    const stored = JSON.parse(localStorage.getItem(KEY) ?? '{}') as Record<string, unknown>;
    expect(Object.keys(stored)).toEqual(['new']);
  });

  it('clearAll drops every entry', () => {
    persistInflightStream('c1', 'm1');
    persistInflightStream('c2', 'm2');
    clearAllInflightStreams();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it('treats corrupt storage as empty', () => {
    localStorage.setItem(KEY, '{not json');
    expect(readInflightStream('c1')).toBeNull();
    localStorage.setItem(KEY, JSON.stringify({ c1: { ts: Date.now() } }));
    expect(readInflightStream('c1')).toBeNull();
  });
});
