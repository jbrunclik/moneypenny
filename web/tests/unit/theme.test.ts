/**
 * Color scheme preference: stored choice, system fallback, and the
 * data-theme attribute (light sets it, dark is the default without it).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  applyColorScheme,
  getEffectiveTheme,
  getStoredColorScheme,
  initializeTheme,
  saveColorScheme,
  setupSystemPreferenceListener,
} from '@/utils/theme';

const STORAGE_KEY = 'ai-chatbot-color-scheme';

type ChangeListener = (e: MediaQueryListEvent) => void;

/** A matchMedia stub whose dark-mode query reports `dark` and records listeners. */
function stubMatchMedia(dark: boolean) {
  const listeners = new Set<ChangeListener>();
  const mql = {
    matches: dark,
    addEventListener: vi.fn((_: string, l: ChangeListener) => listeners.add(l)),
    removeEventListener: vi.fn((_: string, l: ChangeListener) => listeners.delete(l)),
  };
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => mql)
  );
  const emit = (matches: boolean) =>
    listeners.forEach((l) => l({ matches } as MediaQueryListEvent));
  return { listeners, emit };
}

describe('theme', () => {
  beforeEach(() => {
    localStorage.removeItem(STORAGE_KEY);
    document.documentElement.removeAttribute('data-theme');
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.removeItem(STORAGE_KEY);
  });

  describe('stored scheme', () => {
    it('defaults to system when nothing is stored', () => {
      expect(getStoredColorScheme()).toBe('system');
    });

    it.each(['light', 'dark', 'system'] as const)('round-trips %s', (scheme) => {
      saveColorScheme(scheme);
      expect(getStoredColorScheme()).toBe(scheme);
    });

    it('treats an unknown stored value as system', () => {
      localStorage.setItem(STORAGE_KEY, 'sepia');
      expect(getStoredColorScheme()).toBe('system');
    });
  });

  describe('effective theme', () => {
    it('an explicit scheme wins over the system preference', () => {
      stubMatchMedia(true);
      expect(getEffectiveTheme('light')).toBe('light');
      stubMatchMedia(false);
      expect(getEffectiveTheme('dark')).toBe('dark');
    });

    it('system follows prefers-color-scheme', () => {
      stubMatchMedia(true);
      expect(getEffectiveTheme('system')).toBe('dark');
      stubMatchMedia(false);
      expect(getEffectiveTheme('system')).toBe('light');
    });
  });

  describe('applying', () => {
    it('light sets data-theme="light"', () => {
      expect(applyColorScheme('light')).toBe('light');
      expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    });

    it('dark removes data-theme (dark is the stylesheet default)', () => {
      document.documentElement.setAttribute('data-theme', 'light');
      expect(applyColorScheme('dark')).toBe('dark');
      expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    });

    it('initializeTheme applies the stored scheme', () => {
      stubMatchMedia(true);
      saveColorScheme('light');
      expect(initializeTheme()).toEqual({ scheme: 'light', effectiveTheme: 'light' });
      expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    });

    it('initializeTheme resolves system through the media query', () => {
      stubMatchMedia(true);
      expect(initializeTheme()).toEqual({ scheme: 'system', effectiveTheme: 'dark' });
    });
  });

  describe('system preference listener', () => {
    it('reports changes and stops after cleanup', () => {
      const { listeners, emit } = stubMatchMedia(false);
      const onChange = vi.fn();
      const cleanup = setupSystemPreferenceListener(onChange);
      emit(true);
      expect(onChange).toHaveBeenLastCalledWith('dark');
      emit(false);
      expect(onChange).toHaveBeenLastCalledWith('light');
      cleanup();
      expect(listeners.size).toBe(0);
    });
  });
});
