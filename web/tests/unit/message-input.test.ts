/**
 * Unit tests for MessageInput component utilities
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { isIOSPWA } from '@/components/MessageInput';

describe('isIOSPWA', () => {
  const originalNavigator = window.navigator;
  const originalMatchMedia = window.matchMedia;

  // Helper to mock navigator.userAgent
  function mockUserAgent(userAgent: string): void {
    Object.defineProperty(window, 'navigator', {
      value: {
        ...originalNavigator,
        userAgent,
      },
      configurable: true,
      writable: true,
    });
  }

  // Helper to mock navigator.standalone (iOS Safari property)
  function mockStandalone(value: boolean | undefined): void {
    const nav = window.navigator as Record<string, unknown>;
    if (value === undefined) {
      delete nav.standalone;
    } else {
      nav.standalone = value;
    }
  }

  // Helper to mock matchMedia
  function mockMatchMedia(standaloneMatches: boolean): void {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query === '(display-mode: standalone)' ? standaloneMatches : false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  }

  beforeEach(() => {
    // Reset to defaults
    mockMatchMedia(false);
  });

  afterEach(() => {
    // Restore original
    Object.defineProperty(window, 'navigator', {
      value: originalNavigator,
      configurable: true,
      writable: true,
    });
    window.matchMedia = originalMatchMedia;
  });

  describe('iOS device detection', () => {
    it('detects iPhone', () => {
      mockUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(true);
    });

    it('detects iPad', () => {
      mockUserAgent('Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(true);
    });

    it('detects iPod', () => {
      mockUserAgent('Mozilla/5.0 (iPod touch; CPU iPhone OS 17_0 like Mac OS X)');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(true);
    });

    it('returns false for Android', () => {
      mockUserAgent('Mozilla/5.0 (Linux; Android 14)');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(false);
    });

    it('returns false for desktop Chrome', () => {
      mockUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120.0.0.0');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(false);
    });

    it('returns false for desktop Windows', () => {
      mockUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64)');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(false);
    });
  });

  describe('PWA mode detection', () => {
    it('returns false for iOS in browser (not PWA)', () => {
      mockUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)');
      mockMatchMedia(false);
      mockStandalone(undefined);
      expect(isIOSPWA()).toBe(false);
    });

    it('returns true when display-mode: standalone matches', () => {
      mockUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(true);
    });

    it('returns true when navigator.standalone is true (iOS Safari property)', () => {
      mockUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)');
      mockMatchMedia(false);
      mockStandalone(true);
      expect(isIOSPWA()).toBe(true);
    });

    it('returns false when navigator.standalone is false', () => {
      mockUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)');
      mockMatchMedia(false);
      mockStandalone(false);
      expect(isIOSPWA()).toBe(false);
    });
  });

  describe('combined conditions', () => {
    it('requires both iOS AND PWA mode', () => {
      // Android in PWA mode
      mockUserAgent('Mozilla/5.0 (Linux; Android 14)');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(false);

      // iOS not in PWA mode
      mockUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)');
      mockMatchMedia(false);
      mockStandalone(undefined);
      expect(isIOSPWA()).toBe(false);

      // iOS in PWA mode
      mockUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)');
      mockMatchMedia(true);
      expect(isIOSPWA()).toBe(true);
    });
  });
});