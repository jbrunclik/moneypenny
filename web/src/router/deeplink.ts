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
type RouteType = 'home' | 'conversation' | 'planner' | 'agents' | 'unknown';

/** Parsed route information */
interface ParsedRoute {
  type: RouteType;
  conversationId?: string;
}

/** Callback when hash changes to a conversation, planner, or agents */
type HashChangeCallback = (conversationId: string | null, isPlanner?: boolean, isAgents?: boolean) => void;

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

  // Match /planner route
  if (cleanHash === '/planner') {
    return { type: 'planner' };
  }

  // Match /agents route
  if (cleanHash === '/agents') {
    return { type: 'agents' };
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
 * Set the URL hash to the planner route.
 */
export function setPlannerHash(): void {
  const newHash = '#/planner';
  const currentHash = window.location.hash;

  if (currentHash === newHash) {
    return;
  }

  log.debug('Setting planner hash', { from: currentHash });

  isIgnoringHashChange = true;
  history.pushState(null, '', newHash);
  setTimeout(() => {
    isIgnoringHashChange = false;
  }, 0);
}

/**
 * Check if the current route is the planner.
 */
export function isPlannerRoute(): boolean {
  const route = parseHash();
  return route.type === 'planner';
}

/**
 * Set the URL hash to the agents route.
 */
export function setAgentsHash(): void {
  const newHash = '#/agents';
  const currentHash = window.location.hash;

  if (currentHash === newHash) {
    return;
  }

  log.debug('Setting agents hash', { from: currentHash });

  isIgnoringHashChange = true;
  history.pushState(null, '', newHash);
  setTimeout(() => {
    isIgnoringHashChange = false;
  }, 0);
}

/**
 * Check if the current route is agents.
 */
export function isAgentsRoute(): boolean {
  const route = parseHash();
  return route.type === 'agents';
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
    if (route.type === 'planner') {
      hashChangeCallback(null, true, false);
    } else if (route.type === 'agents') {
      hashChangeCallback(null, false, true);
    } else if (route.type === 'conversation' && route.conversationId) {
      hashChangeCallback(route.conversationId, false, false);
    } else {
      // Home or unknown route - pass null to indicate no conversation selected
      hashChangeCallback(null, false, false);
    }
  }
}

/** Initial route information returned by initDeepLinking */
export interface InitialRoute {
  conversationId: string | null;
  isPlanner: boolean;
  isAgents: boolean;
}

/**
 * Initialize deep linking.
 * Call this once during app initialization, after components are ready.
 *
 * @param onHashChange - Callback invoked when URL hash changes via browser navigation
 * @returns The initial route info: conversation ID and whether it's planner/agents
 */
export function initDeepLinking(onHashChange: HashChangeCallback): InitialRoute {
  log.info('Initializing deep linking');

  hashChangeCallback = onHashChange;

  // Listen for browser back/forward navigation
  window.addEventListener('hashchange', handleHashChange);

  // Return the initial route info for the caller to handle
  const initialRoute = parseHash();

  if (initialRoute.type === 'planner') {
    log.info('Initial route is planner');
    return { conversationId: null, isPlanner: true, isAgents: false };
  }

  if (initialRoute.type === 'agents') {
    log.info('Initial route is agents');
    return { conversationId: null, isPlanner: false, isAgents: true };
  }

  if (initialRoute.type === 'conversation' && initialRoute.conversationId) {
    log.info('Initial route has conversation', { conversationId: initialRoute.conversationId });
    return { conversationId: initialRoute.conversationId, isPlanner: false, isAgents: false };
  }

  // Check if the hash contains a temp conversation ID and clear it
  // This handles the case where a temp ID somehow ended up in the URL
  const hash = window.location.hash;
  if (hash.includes('/conversations/temp-')) {
    log.warn('Clearing temp conversation ID from URL');
    clearConversationHash();
  }

  return { conversationId: null, isPlanner: false, isAgents: false };
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

