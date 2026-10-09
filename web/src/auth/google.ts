import { auth } from '../api/auth';
import { ApiError } from '../api/http';
import { useStore } from '../state/store';
import { toast } from '../components/Toast';
import { createLogger } from '../utils/logger';
import { disablePush } from '../core/push';
import { GOOGLE_BUTTON_WIDTH, GOOGLE_SCRIPT_POLL_INTERVAL_MS, GOOGLE_SCRIPT_TIMEOUT_MS } from '../config';

const log = createLogger('auth');

let googleInitialized = false;
let tokenRefreshTimeoutId: ReturnType<typeof setTimeout> | null = null;

// Refresh token when less than 2 days remain (tokens last 7 days)
// This gives a 48-hour window where any app open will trigger refresh,
// so users can skip a day without getting logged out.
const TOKEN_REFRESH_BUFFER_MS = 2 * 24 * 60 * 60 * 1000; // 2 days

/**
 * Initialize Google Identity Services
 */
export async function initGoogleSignIn(): Promise<void> {
  if (googleInitialized) return;

  const store = useStore.getState();

  // Get client ID from server
  const clientId = await auth.getClientId();
  if (!clientId) {
    log.info('No Google Client ID - running in development mode');
    return;
  }

  store.setGoogleClientId(clientId);

  // Wait for Google script to load - a blocked/offline script leaves
  // googleInitialized false and renderGoogleButton shows a retry
  if (!(await waitForGoogleScript())) {
    log.warn('Google Sign-In script did not load', { timeoutMs: GOOGLE_SCRIPT_TIMEOUT_MS });
    return;
  }

  // Initialize Google Identity Services
  google.accounts.id.initialize({
    client_id: clientId,
    callback: handleGoogleCredential,
    auto_select: false,
  });

  googleInitialized = true;
}

/**
 * Render Google Sign-In button
 */
export function renderGoogleButton(container: HTMLElement): void {
  const clientId = useStore.getState().googleClientId;
  if (!clientId) {
    log.debug('Google Sign-In not available');
    return;
  }
  if (!googleInitialized) {
    // Sign-in is configured but Google's script never came up: say so and
    // offer a way forward instead of an empty login card
    container.innerHTML = `
      <div class="login-unavailable" role="alert">
        <p>Sign-in couldn’t load. Check your connection and try again.</p>
        <button type="button" class="btn btn-secondary login-retry-btn">Retry</button>
      </div>
    `;
    container.querySelector('.login-retry-btn')?.addEventListener('click', () => window.location.reload());
    return;
  }

  google.accounts.id.renderButton(container, {
    theme: 'filled_black',
    size: 'large',
    text: 'signin_with',
    // Pill: matches the app's rounded controls
    shape: 'pill',
    width: GOOGLE_BUTTON_WIDTH,
  });
}

/**
 * Handle Google credential response
 */
async function handleGoogleCredential(
  response: google.accounts.id.CredentialResponse
): Promise<void> {
  const store = useStore.getState();

  try {
    const authResponse = await auth.googleLogin(response.credential);
    store.setToken(authResponse.token);
    store.setUser(authResponse.user);

    // Schedule automatic token refresh before expiration
    scheduleTokenRefresh(authResponse.token);

    // Trigger app reload/init
    window.dispatchEvent(new CustomEvent('auth:login'));
  } catch (error) {
    log.error('Google login failed', { error });
    toast.error('Login failed. Please try again.');
    window.dispatchEvent(
      new CustomEvent('auth:error', { detail: { error } })
    );
  }
}

/**
 * Check authentication status
 *
 * Returns true if authenticated, false otherwise.
 * If the token has expired, shows a toast prompting re-login.
 * If authenticated, schedules automatic token refresh.
 */
export async function checkAuth(): Promise<boolean> {
  const store = useStore.getState();

  try {
    const user = await auth.me();
    log.info('User authenticated', { userId: user.id, email: user.email });
    store.setUser(user);

    // Schedule automatic token refresh for existing valid token
    if (store.token) {
      scheduleTokenRefresh(store.token);
    }

    return true;
  } catch (error) {
    // Auth failed - clear any stale token and cancel refresh
    if (store.token) {
      cancelTokenRefresh();
      store.logout();

      // Show helpful message for token expiration
      if (error instanceof ApiError && error.isTokenExpired) {
        toast.info('Your session has expired. Please sign in again.');
      }
    }
    return false;
  }
}

/**
 * Logout user
 */
export function logout(): void {
  log.info('User logging out');
  const store = useStore.getState();

  // Best-effort: stop this device from receiving the user's push
  // notifications (matters on shared devices). Fired before the token
  // is cleared because the unsubscribe API call needs auth; failures
  // are fine - the dead subscription gets pruned on its next send.
  void disablePush().catch(() => undefined);

  // Cancel any scheduled token refresh
  cancelTokenRefresh();

  store.logout();

  // Disable Google auto-select on next visit
  if (googleInitialized) {
    google.accounts.id.disableAutoSelect();
  }

  // Trigger UI update
  window.dispatchEvent(new CustomEvent('auth:logout'));
}

/**
 * Wait for Google script to load
 */
/** Resolves true once the Google script is up, false after GOOGLE_SCRIPT_TIMEOUT_MS. */
function waitForGoogleScript(): Promise<boolean> {
  return new Promise((resolve) => {
    const deadline = Date.now() + GOOGLE_SCRIPT_TIMEOUT_MS;
    const checkGoogle = (): void => {
      if (typeof google !== 'undefined' && google.accounts) {
        resolve(true);
      } else if (Date.now() >= deadline) {
        resolve(false);
      } else {
        setTimeout(checkGoogle, GOOGLE_SCRIPT_POLL_INTERVAL_MS);
      }
    };
    checkGoogle();
  });
}

/**
 * Decode JWT payload without verification (for reading expiration time).
 * This is safe because we only use it to schedule refresh - the server
 * will verify the token when we actually use it.
 */
function decodeJwtPayload(token: string): { exp?: number; iat?: number } | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = JSON.parse(atob(parts[1]));
    return payload;
  } catch {
    return null;
  }
}

/**
 * Schedule automatic token refresh before expiration.
 * Called after successful login or token refresh.
 */
export function scheduleTokenRefresh(token: string): void {
  // Clear any existing scheduled refresh
  cancelTokenRefresh();

  const payload = decodeJwtPayload(token);
  if (!payload?.exp) {
    log.warn('Could not decode token expiration, skipping auto-refresh');
    return;
  }

  const expirationMs = payload.exp * 1000;
  const now = Date.now();
  const timeUntilExpiry = expirationMs - now;

  // Schedule refresh 1 hour before expiration
  const refreshIn = timeUntilExpiry - TOKEN_REFRESH_BUFFER_MS;

  if (refreshIn <= 0) {
    // Token expires in less than 1 hour, refresh immediately
    log.info('Token expiring soon, refreshing immediately');
    performTokenRefresh();
    return;
  }

  log.debug('Scheduling token refresh', { refreshInMinutes: Math.round(refreshIn / 1000 / 60) });
  tokenRefreshTimeoutId = setTimeout(performTokenRefresh, refreshIn);
}

/**
 * Cancel any scheduled token refresh.
 */
export function cancelTokenRefresh(): void {
  if (tokenRefreshTimeoutId) {
    clearTimeout(tokenRefreshTimeoutId);
    tokenRefreshTimeoutId = null;
  }
}

/**
 * Perform the actual token refresh.
 */
async function performTokenRefresh(): Promise<void> {
  const store = useStore.getState();

  if (!store.token) {
    log.debug('No token to refresh');
    return;
  }

  try {
    log.debug('Refreshing token');
    const newToken = await auth.refreshToken();
    store.setToken(newToken);
    log.info('Token refreshed successfully');

    // Schedule next refresh
    scheduleTokenRefresh(newToken);
  } catch (error) {
    log.error('Failed to refresh token', { error });

    // If refresh fails due to expired token, trigger re-auth
    if (error instanceof ApiError && error.isTokenExpired) {
      store.logout();
      toast.info('Your session has expired. Please sign in again.');
      window.dispatchEvent(new CustomEvent('auth:logout'));
    }
    // For other errors, we'll try again on the next API call
  }
}