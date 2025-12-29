/**
 * Unit tests for MessageInput component utilities
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { isIOSPWA, isMobileViewport } from '@/components/MessageInput';
import { MOBILE_BREAKPOINT_PX } from '@/config';

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

describe('isMobileViewport', () => {
  const originalInnerWidth = window.innerWidth;

  // Helper to mock window.innerWidth
  function mockInnerWidth(width: number): void {
    Object.defineProperty(window, 'innerWidth', {
      value: width,
      configurable: true,
      writable: true,
    });
  }

  afterEach(() => {
    // Restore original
    Object.defineProperty(window, 'innerWidth', {
      value: originalInnerWidth,
      configurable: true,
      writable: true,
    });
  });

  describe('mobile detection based on viewport width', () => {
    it('returns true for narrow mobile viewport (375px - iPhone)', () => {
      mockInnerWidth(375);
      expect(isMobileViewport()).toBe(true);
    });

    it('returns true for wider mobile viewport (414px - iPhone Plus)', () => {
      mockInnerWidth(414);
      expect(isMobileViewport()).toBe(true);
    });

    it('returns true at exactly the breakpoint (768px)', () => {
      mockInnerWidth(MOBILE_BREAKPOINT_PX);
      expect(isMobileViewport()).toBe(true);
    });

    it('returns false just above breakpoint (769px)', () => {
      mockInnerWidth(MOBILE_BREAKPOINT_PX + 1);
      expect(isMobileViewport()).toBe(false);
    });

    it('returns false for tablet landscape (1024px)', () => {
      mockInnerWidth(1024);
      expect(isMobileViewport()).toBe(false);
    });

    it('returns false for desktop (1440px)', () => {
      mockInnerWidth(1440);
      expect(isMobileViewport()).toBe(false);
    });

    it('returns false for large desktop (1920px)', () => {
      mockInnerWidth(1920);
      expect(isMobileViewport()).toBe(false);
    });
  });

  describe('edge cases', () => {
    it('returns true for very small viewport (320px - iPhone SE)', () => {
      mockInnerWidth(320);
      expect(isMobileViewport()).toBe(true);
    });

    it('returns true for iPad mini portrait (768px)', () => {
      mockInnerWidth(768);
      expect(isMobileViewport()).toBe(true);
    });
  });
});