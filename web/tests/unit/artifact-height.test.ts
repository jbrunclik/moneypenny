import { afterEach, describe, expect, it, vi } from 'vitest';
import { getCachedHeight, heightCacheKey, setCachedHeight } from '@/components/messages/artifact-height';

const REF = { id: 'a', version: 2, title: 'Tips' };

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('artifact height cache', () => {
  it('keys by artifact version and frame width, so phone and laptop differ', () => {
    expect(heightCacheKey(REF, 390)).not.toBe(heightCacheKey(REF, 1200));
    expect(heightCacheKey(REF, 390)).toBe(heightCacheKey(REF, 400));
    expect(heightCacheKey(REF, 390)).toContain('a@2');
  });

  it('remembers a height per key', () => {
    setCachedHeight('k', 321);
    expect(getCachedHeight('k')).toBe(321);
    expect(getCachedHeight('other')).toBeNull();
  });

  it('keeps at most 200 entries, dropping the oldest', () => {
    for (let i = 0; i < 205; i++) setCachedHeight(`k${i}`, i + 1);
    expect(getCachedHeight('k0')).toBeNull();
    expect(getCachedHeight('k204')).toBe(205);
  });

  it('storage that throws is harmless', () => {
    // The test setup replaces localStorage with a plain mock object
    vi.spyOn(localStorage, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(() => setCachedHeight('k', 1)).not.toThrow();
    expect(getCachedHeight('k')).toBeNull();
  });
});
