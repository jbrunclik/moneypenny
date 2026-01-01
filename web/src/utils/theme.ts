/**
 * Theme Management Utility
 *
 * Handles color scheme switching between light, dark, and system preference.
 * Theme preference is stored in localStorage and applied via data-theme attribute on html element.
 */

import { createLogger } from './logger';

const log = createLogger('theme');

export type ColorScheme = 'light' | 'dark' | 'system';

const THEME_STORAGE_KEY = 'ai-chatbot-color-scheme';

/**
 * Get the current system preference for color scheme
 */
function getSystemPreference(): 'light' | 'dark' {
  if (
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-color-scheme: dark)').matches
  ) {
    return 'dark';
  }
  return 'light';
}

/**
 * Apply the theme to the document
 */
function applyTheme(theme: 'light' | 'dark'): void {
  if (theme === 'light') {
    document.documentElement.setAttribute('data-theme', 'light');
  } else {
    document.documentElement.removeAttribute('data-theme');
  }
  log.debug('Theme applied', { theme });
}

/**
 * Get the stored color scheme preference from localStorage
 */
export function getStoredColorScheme(): ColorScheme {
  if (typeof window === 'undefined') {
    return 'system';
  }
  const stored = localStorage.getItem(THEME_STORAGE_KEY);
  if (stored === 'light' || stored === 'dark' || stored === 'system') {
    return stored;
  }
  return 'system';
}

/**
 * Save the color scheme preference to localStorage
 */
export function saveColorScheme(scheme: ColorScheme): void {
  if (typeof window === 'undefined') {
    return;
  }
  localStorage.setItem(THEME_STORAGE_KEY, scheme);
  log.info('Color scheme saved', { scheme });
}

/**
 * Get the effective theme based on the current preference
 */
export function getEffectiveTheme(scheme: ColorScheme): 'light' | 'dark' {
  if (scheme === 'system') {
    return getSystemPreference();
  }
  return scheme;
}

/**
 * Apply the color scheme and return the effective theme
 */
export function applyColorScheme(scheme: ColorScheme): 'light' | 'dark' {
  const effectiveTheme = getEffectiveTheme(scheme);
  applyTheme(effectiveTheme);
  return effectiveTheme;
}

/**
 * Set up listener for system preference changes
 */
export function setupSystemPreferenceListener(
  onSystemChange: (newTheme: 'light' | 'dark') => void
): () => void {
  if (typeof window === 'undefined' || !window.matchMedia) {
    return () => {};
  }

  const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

  const listener = (e: MediaQueryListEvent) => {
    const newTheme = e.matches ? 'dark' : 'light';
    log.debug('System preference changed', { newTheme });
    onSystemChange(newTheme);
  };

  // Modern browsers
  if (mediaQuery.addEventListener) {
    mediaQuery.addEventListener('change', listener);
    return () => mediaQuery.removeEventListener('change', listener);
  }

  // Legacy browsers (Safari < 14)
  mediaQuery.addListener(listener);
  return () => mediaQuery.removeListener(listener);
}

/**
 * Initialize the theme system
 * Call this early in the app initialization to prevent flash of wrong theme
 */
export function initializeTheme(): {
  scheme: ColorScheme;
  effectiveTheme: 'light' | 'dark';
} {
  const scheme = getStoredColorScheme();
  const effectiveTheme = applyColorScheme(scheme);
  log.info('Theme initialized', { scheme, effectiveTheme });
  return { scheme, effectiveTheme };
}
