/**
 * Centralized configuration for the AI Chatbot frontend.
 *
 * This file contains developer-configurable values like timeouts, thresholds,
 * and feature settings. For true constants (unit conversions), see constants.ts.
 *
 * Guidelines:
 * - Use SCREAMING_SNAKE_CASE for constant names
 * - Group related config together with section headers
 * - Include units in the constant name (e.g., _MS, _PX, _BYTES)
 * - Add comments explaining non-obvious values
 * - Import and use base constants from constants.ts
 */

import {
  MS_PER_SECOND,
  MS_PER_MINUTE,
  MS_PER_DAY,
  BYTES_PER_MB,
} from './constants';

// =============================================================================
// localStorage Keys
// =============================================================================

/** Main app state storage key (Zustand persist) */
export const STORAGE_KEY_APP_STATE = 'ai-chatbot-storage';

/** Legacy token storage key (for backwards compatibility) */
export const STORAGE_KEY_LEGACY_TOKEN = 'token';

/** Voice input language preference */
export const STORAGE_KEY_VOICE_LANG = 'voice-input-lang';

/** Dismissed version banner storage key */
export const STORAGE_KEY_VERSION_DISMISSED = 'ai-chatbot-version-dismissed';

// =============================================================================
// API Client Configuration
// =============================================================================

/** Default timeout for API requests (30 seconds) */
export const API_DEFAULT_TIMEOUT_MS = 30 * MS_PER_SECOND;

/** Timeout for chat requests (5 minutes) */
export const API_CHAT_TIMEOUT_MS = 5 * MS_PER_MINUTE;

/** Timeout for individual stream reads (1 minute, backend sends keepalives every 15s) */
export const API_STREAM_READ_TIMEOUT_MS = 1 * MS_PER_MINUTE;

/** Maximum number of retry attempts for failed requests */
export const API_MAX_RETRIES = 3;

/** Initial delay before first retry (exponential backoff) */
export const API_RETRY_INITIAL_DELAY_MS = 1 * MS_PER_SECOND;

/** Maximum delay between retries */
export const API_RETRY_MAX_DELAY_MS = 10 * MS_PER_SECOND;

/** Jitter factor for exponential backoff (0.25 = ±25%) */
export const API_RETRY_JITTER_FACTOR = 0.25;

/** HTTP status codes that are safe to retry */
export const API_RETRYABLE_STATUS_CODES = [408, 429, 500, 502, 503, 504];

// =============================================================================
// Authentication
// =============================================================================

/** Buffer time before token expiration to trigger refresh (2 days) */
export const TOKEN_REFRESH_BUFFER_MS = 2 * MS_PER_DAY;

/** Width of the Google Sign-In button */
export const GOOGLE_BUTTON_WIDTH = 280;

/** Poll interval when waiting for Google script to load */
export const GOOGLE_SCRIPT_POLL_INTERVAL_MS = 100;

// =============================================================================
// Responsive Breakpoints
// =============================================================================

/** Mobile breakpoint width - matches CSS media queries in layout.css */
export const MOBILE_BREAKPOINT_PX = 768;

// =============================================================================
// Touch Gestures / Swipe
// =============================================================================

/** Default minimum swipe distance to trigger action */
export const SWIPE_THRESHOLD_PX = 50;

/** Default maximum swipe distance (for visual feedback capping) */
export const SWIPE_MAX_DISTANCE_PX = 80;

/** Minimum movement to distinguish swipe from tap */
export const SWIPE_MIN_MOVEMENT_PX = 10;

/** Maximum touch duration to be considered a tap (not swipe) */
export const TAP_MAX_DURATION_MS = 300;

/** Maximum movement during tap (if exceeded, it's a swipe) */
export const TAP_MAX_MOVEMENT_PX = 10;

/** Width of the edge zone for sidebar swipe-to-open */
export const SIDEBAR_EDGE_SWIPE_ZONE_PX = 50;

/** Duration to trigger long-press actions (e.g., voice input language selector) */
export const LONG_PRESS_DURATION_MS = 500;

// =============================================================================
// Thumbnail Loading
// =============================================================================

/** Maximum concurrent thumbnail fetches */
export const THUMBNAIL_MAX_CONCURRENT_FETCHES = 6;

/** Initial polling delay when thumbnail is pending (ms) */
export const THUMBNAIL_POLL_INITIAL_DELAY_MS = 500;

/** Maximum polling delay for pending thumbnails (ms) */
export const THUMBNAIL_POLL_MAX_DELAY_MS = 4 * MS_PER_SECOND;

/** Maximum number of polling attempts before giving up */
export const THUMBNAIL_POLL_MAX_ATTEMPTS = 5;

// =============================================================================
// Scroll Behavior
// =============================================================================

/** Delay after programmatic scroll to reset the flag (ensures scroll events fired) */
export const SCROLL_PROGRAMMATIC_RESET_DELAY_MS = 150;

/** Distance from bottom to consider user "scrolled away" from bottom */
export const SCROLL_USER_DETECTION_THRESHOLD_PX = 200;

/** Delay for smooth scroll animation to complete (300-600ms actual + buffer) */
export const SCROLL_SMOOTH_COMPLETION_DELAY_MS = 700;

/** Debounce delay for user scroll listener */
export const SCROLL_EVENT_DEBOUNCE_MS = 100;

/** Grace period after enabling scroll mode to ignore false positives */
export const SCROLL_MODE_GRACE_PERIOD_MS = 500;

/** Delay between retry attempts for checking if images are loaded */
export const IMAGE_LOAD_RETRY_DELAY_MS = 300;

/** Maximum retry attempts for image load checking */
export const IMAGE_LOAD_MAX_RETRY_ATTEMPTS = 3;

/** IntersectionObserver root margin for lazy loading */
export const INTERSECTION_OBSERVER_ROOT_MARGIN = '50px';

/** IntersectionObserver threshold for visibility detection */
export const INTERSECTION_OBSERVER_THRESHOLD = 0.1;

/** Default threshold for isScrolledToBottom check */
export const SCROLL_BOTTOM_THRESHOLD_PX = 100;

/** Distance from bottom to show scroll-to-bottom button */
export const SCROLL_BUTTON_SHOW_THRESHOLD_PX = 200;

// =============================================================================
// Smooth Scroll Animation
// =============================================================================

/** Maximum duration for smooth scroll animation */
export const SMOOTH_SCROLL_MAX_DURATION_MS = 600;

/** Minimum duration for smooth scroll animation */
export const SMOOTH_SCROLL_MIN_DURATION_MS = 300;

/** Factor to calculate scroll duration based on distance */
export const SMOOTH_SCROLL_DISTANCE_FACTOR = 0.5;

// =============================================================================
// UI Animation Durations
// =============================================================================

/** Default toast notification display duration */
export const TOAST_DEFAULT_DURATION_MS = 5 * MS_PER_SECOND;

/** Toast exit animation duration */
export const TOAST_EXIT_ANIMATION_MS = 200;

/** Modal exit animation duration */
export const MODAL_EXIT_ANIMATION_MS = 150;

/** Delay before focusing input in modal (allows animation to settle) */
export const MODAL_FOCUS_DELAY_MS = 50;

// =============================================================================
// Version Banner
// =============================================================================

/** Interval between version checks (5 minutes) */
export const VERSION_CHECK_INTERVAL_MS = 5 * MS_PER_MINUTE;

// =============================================================================
// Sync Configuration
// =============================================================================

/** Interval between sync polls (1 minute) */
export const SYNC_POLL_INTERVAL_MS = 1 * MS_PER_MINUTE;

/** Threshold for triggering full sync after tab is hidden (5 minutes) */
export const SYNC_FULL_SYNC_THRESHOLD_MS = 5 * MS_PER_MINUTE;

// =============================================================================
// Pagination Configuration
// =============================================================================

/** Approximate height of a conversation item in pixels (for viewport calculation) */
export const CONVERSATION_ITEM_HEIGHT_PX = 60;

/** Approximate height of a message in pixels (for viewport calculation) */
export const MESSAGE_AVG_HEIGHT_PX = 120;

/** Minimum page size for conversations (floor for small viewports) */
export const CONVERSATIONS_MIN_PAGE_SIZE = 15;

/** Minimum page size for messages (floor for small viewports) */
export const MESSAGES_MIN_PAGE_SIZE = 20;

/** Buffer multiplier for viewport-based page size calculation */
export const VIEWPORT_BUFFER_MULTIPLIER = 1.5;

/** Distance from bottom of scroll container to trigger loading more (in pixels) */
export const LOAD_MORE_THRESHOLD_PX = 200;

/** Debounce delay for infinite scroll scroll event handler */
export const INFINITE_SCROLL_DEBOUNCE_MS = 100;

// =============================================================================
// Streaming Abort Cleanup
// =============================================================================

/** Delay before attempting to delete partial message after aborting stream (1.5 seconds) */
export const STREAMING_ABORT_CLEANUP_DELAY_MS = 1.5 * MS_PER_SECOND;

// =============================================================================
// Voice Input
// =============================================================================

/** Supported languages for voice input */
export const VOICE_SUPPORTED_LANGUAGES = ['en-US', 'cs-CZ'] as const;

/** Mapping from browser language codes to full language codes */
export const VOICE_LANGUAGE_VARIANTS: Record<string, string> = {
  en: 'en-US',
  cs: 'cs-CZ',
};

/** Display names for supported languages */
export const VOICE_LANGUAGE_NAMES: Record<string, string> = {
  'en-US': 'English',
  'cs-CZ': 'Čeština',
};

// =============================================================================
// File Upload
// =============================================================================

/** Default maximum file size (20MB) */
export const UPLOAD_DEFAULT_MAX_FILE_SIZE_BYTES = 20 * BYTES_PER_MB;

/** Default maximum number of files per message */
export const UPLOAD_DEFAULT_MAX_FILES = 10;

/** Allowed MIME types for file uploads */
export const UPLOAD_ALLOWED_TYPES = [
  'image/jpeg',
  'image/png',
  'image/gif',
  'image/webp',
  'application/pdf',
  'text/plain',
  'text/markdown',
  'text/csv',
  'application/json',
];

// =============================================================================
// Default Values
// =============================================================================

/** Default conversation title for new conversations */
export const DEFAULT_CONVERSATION_TITLE = 'New Conversation';

// =============================================================================
// Logging
// =============================================================================

/** Available log levels */
export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

/** Log level priority (higher = more severe) */
export const LOG_LEVELS: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

/**
 * Current log level.
 * In development mode, defaults to 'debug' to show all logs.
 * In production, defaults to 'warn' to reduce noise.
 * Can be overridden by setting window.__LOG_LEVEL__ before app loads.
 */
export const LOG_LEVEL: LogLevel = (() => {
  // Allow runtime override via window property
  if (
    typeof window !== 'undefined' &&
    '__LOG_LEVEL__' in window &&
    typeof (window as Record<string, unknown>).__LOG_LEVEL__ === 'string'
  ) {
    const level = (window as Record<string, unknown>).__LOG_LEVEL__ as string;
    if (level in LOG_LEVELS) {
      return level as LogLevel;
    }
  }
  // Default based on environment
  return import.meta.env.DEV ? 'debug' : 'warn';
})();