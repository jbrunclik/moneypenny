/**
 * Deep linking module for conversation URLs.
 *
 * Uses hash-based routing (#/conversations/{conversationId}) to allow users to:
 * - Bookmark conversations
 * - Share conversation URLs
 * - Use browser back/forward navigation
 * - Reload the page and return to the same conversation
 *
 * Key considerations:
 * - Hash is only updated for persisted conversations (not temp- prefixed)
 * - Hash is cleared when conversation is deleted
 * - Handles conversations not in the initially paginated list by fetching from API
 * - Race conditions: handles temp→persisted transitions, deleted conversations
 */

import { createLogger } from '../utils/logger';

const log = createLogger('deeplink');

/** Route types supported by the router */
type RouteType = 'home' | 'conversation' | 'unknown';

/** Parsed route information */
interface ParsedRoute {
  type: RouteType;
  conversationId?: string;
}

/** Callback when hash changes to a conversation */
type HashChangeCallback = (conversationId: string | null) => void;

// Module state
let hashChangeCallback: HashChangeCallback | null = null;
let isIgnoringHashChange = false;

/**
 * Parse the current URL hash into a route.
 */
export function parseHash(hash: string = window.location.hash): ParsedRoute {
  // Remove leading # if present
  const cleanHash = hash.startsWith('#') ? hash.slice(1) : hash;

  // Empty hash = home
  if (!cleanHash || cleanHash === '/') {
    return { type: 'home' };
  }

  // Match /conversations/{id}
  const conversationMatch = cleanHash.match(/^\/conversations\/([^/]+)$/);
  if (conversationMatch) {
    const conversationId = conversationMatch[1];
    // Validate it's not a temp conversation in URL (should never happen, but defensive)
    if (!conversationId.startsWith('temp-')) {
      return { type: 'conversation', conversationId };
    }
    log.warn('Temp conversation ID found in URL hash, ignoring', { conversationId });
    return { type: 'home' };
  }

  log.debug('Unknown route', { hash: cleanHash });
  return { type: 'unknown' };
}

/**
 * Get the conversation ID from the current URL hash, if any.
 * Returns null if no conversation is specified or if the URL points to a temp conversation.
 */
export function getConversationIdFromHash(): string | null {
  const route = parseHash();
  return route.type === 'conversation' ? route.conversationId ?? null : null;
}

/**
 * Update the URL hash to point to a conversation.
 * Only updates for persisted conversations (not temp-).
 *
 * @param conversationId - The conversation ID to set, or null to clear
 * @param options - Optional configuration
 * @param options.replace - Use replaceState instead of pushState (default: false)
 */
export function setConversationHash(
  conversationId: string | null,
  options: { replace?: boolean } = {}
): void {
  // For temp conversations, clear the hash instead of setting it
  // This ensures the URL accurately reflects that no persisted conversation is selected
  // Using replaceState to avoid cluttering browser history
  if (conversationId && conversationId.startsWith('temp-')) {
    log.debug('Clearing hash for temp conversation', { conversationId });
    const currentHash = window.location.hash;
    if (currentHash && currentHash !== '') {
      isIgnoringHashChange = true;
      history.replaceState(null, '', window.location.pathname);
      setTimeout(() => {
        isIgnoringHashChange = false;
      }, 0);
    }
    return;
  }

  const newHash = conversationId ? `#/conversations/${conversationId}` : '';
  const currentHash = window.location.hash;

  // Only update if hash is actually changing
  if (currentHash === newHash || (currentHash === '' && newHash === '')) {
    return;
  }

  log.debug('Updating hash', { from: currentHash, to: newHash, replace: options.replace });

  // Temporarily ignore the resulting hashchange event
  isIgnoringHashChange = true;

  if (options.replace) {
    // Replace current history entry (for initial load, temp→persisted transitions)
    history.replaceState(null, '', newHash || window.location.pathname);
  } else {
    // Push new history entry (for user navigation)
    history.pushState(null, '', newHash || window.location.pathname);
  }

  // Reset ignore flag after a tick (hashchange is async)
  setTimeout(() => {
    isIgnoringHashChange = false;
  }, 0);
}

/**
 * Clear the conversation hash (e.g., when conversation is deleted).
 * Uses replaceState to avoid adding to history.
 */
export function clearConversationHash(): void {
  setConversationHash(null, { replace: true });
}

/**
 * Push an empty hash entry to browser history.
 * Use this when creating a new temp conversation so back button navigates to previous conversation.
 */
export function pushEmptyHash(): void {
  setConversationHash(null, { replace: false });
}

/**
 * Handle hash changes from browser back/forward navigation.
 */
function handleHashChange(): void {
  if (isIgnoringHashChange) {
    log.debug('Ignoring programmatic hash change');
    return;
  }

  const route = parseHash();
  log.debug('Hash changed via navigation', { route });

  if (hashChangeCallback) {
    if (route.type === 'conversation' && route.conversationId) {
      hashChangeCallback(route.conversationId);
    } else {
      // Home or unknown route - pass null to indicate no conversation selected
      hashChangeCallback(null);
    }
  }
}

/**
 * Initialize deep linking.
 * Call this once during app initialization, after components are ready.
 *
 * @param onHashChange - Callback invoked when URL hash changes via browser navigation
 * @returns The initial conversation ID from the URL, or null
 */
export function initDeepLinking(onHashChange: HashChangeCallback): string | null {
  log.info('Initializing deep linking');

  hashChangeCallback = onHashChange;

  // Listen for browser back/forward navigation
  window.addEventListener('hashchange', handleHashChange);

  // Return the initial conversation ID (if any) for the caller to handle
  const initialRoute = parseHash();
  if (initialRoute.type === 'conversation' && initialRoute.conversationId) {
    log.info('Initial route has conversation', { conversationId: initialRoute.conversationId });
    return initialRoute.conversationId;
  }

  // Check if the hash contains a temp conversation ID and clear it
  // This handles the case where a temp ID somehow ended up in the URL
  const hash = window.location.hash;
  if (hash.includes('/conversations/temp-')) {
    log.warn('Clearing temp conversation ID from URL');
    clearConversationHash();
  }

  return null;
}

/**
 * Clean up deep linking listeners.
 * Call this on logout to prevent stale handlers.
 */
export function cleanupDeepLinking(): void {
  log.debug('Cleaning up deep linking');
  window.removeEventListener('hashchange', handleHashChange);
  hashChangeCallback = null;
  isIgnoringHashChange = false;
}

/**
 * Check if a conversation ID looks valid (basic validation).
 * Does not verify the conversation exists on the server.
 */
export function isValidConversationId(id: string): boolean {
  // UUIDs are 36 chars with hyphens, but backend may use other formats
  // Just check it's not empty and doesn't have obviously invalid chars
  if (!id || id.length === 0 || id.length > 100) {
    return false;
  }
  // Allow alphanumeric and hyphens
  return /^[a-zA-Z0-9-]+$/.test(id);
}

