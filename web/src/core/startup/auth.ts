/**
 * Signing in at startup and reacting to later sign-ins and sign-outs: the
 * login overlay, OAuth callbacks, and tearing the UI down on logout.
 */
import { initGoogleSignIn, renderGoogleButton, checkAuth } from '../../auth/google';
import {
  renderMessages,
  cleanupOlderMessagesScrollListener,
  cleanupNewerMessagesScrollListener,
} from '../../components/messages';
import { renderConversationsList, cleanupInfiniteScroll } from '../../components/Sidebar';
import { toast } from '../../components/Toast';
import { initDeepLinking, cleanupDeepLinking, clearConversationHash } from '../../router/deeplink';
import type { InitialRoute } from '../../router/deeplink';
import { stopSyncManager } from '../../sync/SyncManager';
import { getElementById, clearElement } from '../../utils/dom';
import { createLogger } from '../../utils/logger';
import { abortAllStreamingRequests } from '../active-requests';
import { handleDeepLinkNavigation } from '../conversation-deeplink';
import { loadInitialData } from './initial-data';
import { initialRouteFromHash } from './initial-route';

const log = createLogger('init');

/**
 * Show the login overlay.
 */
function showLoginOverlay(): void {
  getElementById('login-overlay')?.classList.remove('hidden');
}

/**
 * Hide the login overlay.
 */
function hideLoginOverlay(): void {
  getElementById('login-overlay')?.classList.add('hidden');
}

/** Finish an integration OAuth flow the page was redirected back from. */
async function completeIntegrationOAuth(): Promise<void> {
  // OAuth callbacks only matter mid-flow (state keys set when the flow
  // started); gate the settings OAuth import on them so boot stays lean.
  // Key literals must match TODOIST_STATE_KEY / CALENDAR_STATE_KEY in
  // components/settings/{todoist,calendar}.ts.
  if (
    sessionStorage.getItem('todoist-oauth-state') ||
    sessionStorage.getItem('calendar-oauth-state')
  ) {
    const oauth = await import('../../components/settings/oauth');
    await oauth.checkTodoistOAuthCallback();
    await oauth.checkCalendarOAuthCallback();
  }
}

/**
 * Check authentication; load the user's data, or show the sign-in button.
 */
export async function startSession(initialRoute: InitialRoute): Promise<void> {
  const isAuthenticated = await checkAuth();

  if (isAuthenticated) {
    hideLoginOverlay();
    // Awaited before loading data: a callback connects the integration,
    // and the integration-status fetch there (planner visibility) must
    // see the new connection
    await completeIntegrationOAuth();
    await loadInitialData(initialRoute);
  } else {
    showLoginOverlay();
    // Clear any conversation hash since user isn't authenticated
    clearConversationHash();
    await initGoogleSignIn();
    const loginBtn = getElementById<HTMLDivElement>('google-login-btn');
    if (loginBtn) {
      renderGoogleButton(loginBtn);
    }
  }
}

async function handleLogin(): Promise<void> {
  hideLoginOverlay();
  try {
    await loadInitialData(initialRouteFromHash());
  } catch (error) {
    log.error('Failed to load data after login', { error });
    toast.error('Failed to load data. Please refresh the page.', {
      action: { label: 'Refresh', onClick: () => window.location.reload() },
    });
  }
}

async function handleLogout(): Promise<void> {
  // Kill in-flight readers and persisted resume entries before anything
  // else - they would keep writing into the logged-out UI, and another
  // account on this browser must not resume the previous user's turns
  abortAllStreamingRequests();

  // Stop sync manager and scroll listeners on logout
  stopSyncManager();
  cleanupInfiniteScroll();
  cleanupOlderMessagesScrollListener();
  cleanupNewerMessagesScrollListener();

  // Clear URL hash and clean up deep linking
  clearConversationHash();
  cleanupDeepLinking();

  showLoginOverlay();
  // All user data in the store (messages, pagination, drafts, agents,
  // storage, programs, ...) is wiped by the store.logout() the event
  // dispatcher already ran - only re-render the now-empty UI here
  renderConversationsList();
  renderMessages([]);

  // Re-render Google Sign-In button. A session that started signed in
  // never initialized sign-in (Google's script loads on demand), so
  // initialize first - the button used to render empty here
  await initGoogleSignIn();
  const loginBtn = getElementById<HTMLDivElement>('google-login-btn');
  if (loginBtn) {
    clearElement(loginBtn);
    renderGoogleButton(loginBtn);
  }

  // Re-initialize deep linking for next login
  initDeepLinking(handleDeepLinkNavigation);
}

/**
 * Listen for auth:login / auth:logout (dispatched by auth/google.ts).
 */
export function initAuthEvents(): void {
  window.addEventListener('auth:login', () => {
    void handleLogin();
  });
  window.addEventListener('auth:logout', () => {
    void handleLogout().catch((error: unknown) => log.error('Failed to reset the UI after logout', { error }));
  });
}
