/**
 * Version Update Banner Component
 *
 * Shows a banner when a new version of the app is available,
 * prompting users to reload the page.
 *
 * The initial version is injected into the HTML template by Flask
 * (data-version attribute on #app), avoiding an initial API call.
 * Subsequent version checks use the /api/version endpoint.
 */

import { version } from '../api/app';
import { useStore } from '../state/store';
import { CLOSE_ICON, REFRESH_ICON } from '../utils/icons';
import { createLogger } from '../utils/logger';

const log = createLogger('version');

// Constants
const VERSION_CHECK_INTERVAL = 5 * 60 * 1000; // 5 minutes
const DISMISSED_VERSION_KEY = 'ai-chatbot-version-dismissed';

// Module state
let bannerElement: HTMLDivElement | null = null;
let checkInterval: number | null = null;
let lastCheckTime = 0;

/**
 * Initialize the version banner
 * Creates the DOM element and starts version checking
 */
export function initVersionBanner(): void {
  // Read initial version from HTML (injected by Flask)
  const appElement = document.getElementById('app');
  const initialVersion = appElement?.dataset.version || null;

  // Store initial version in Zustand if we have one
  if (initialVersion) {
    const store = useStore.getState();
    if (!store.appVersion) {
      store.setAppVersion(initialVersion);
    }
  }

  createBannerElement();
  startVersionChecking();
  setupVisibilityListener();
}

/**
 * Create the banner DOM element
 */
function createBannerElement(): void {
  bannerElement = document.createElement('div');
  bannerElement.className = 'version-banner';
  bannerElement.innerHTML = `
    <span class="version-banner-message">
      A new version is available
    </span>
    <div class="version-banner-actions">
      <button class="version-banner-reload">
        ${REFRESH_ICON} Reload
      </button>
      <button class="version-banner-dismiss">
        ${CLOSE_ICON} Dismiss
      </button>
    </div>
  `;

  // Event listeners using delegation
  bannerElement.addEventListener('click', handleBannerClick);

  // Insert at start of body
  document.body.insertBefore(bannerElement, document.body.firstChild);
}

/**
 * Handle clicks on banner buttons
 */
function handleBannerClick(e: Event): void {
  const target = e.target as HTMLElement;

  if (target.closest('.version-banner-reload')) {
    window.location.reload();
  } else if (target.closest('.version-banner-dismiss')) {
    hideVersionBanner();
    useStore.getState().dismissVersionBanner();

    // Store the dismissed version so we don't show again for this version
    const store = useStore.getState();
    if (store.appVersion) {
      // Store the NEW version that was dismissed (not the old one)
      const serverVersion = localStorage.getItem(DISMISSED_VERSION_KEY + '-pending');
      if (serverVersion) {
        localStorage.setItem(DISMISSED_VERSION_KEY, serverVersion);
        localStorage.removeItem(DISMISSED_VERSION_KEY + '-pending');
      }
    }
  }
}

/**
 * Start periodic version checking
 */
function startVersionChecking(): void {
  // Check if we need to check immediately (e.g., after PWA resume)
  const now = Date.now();
  if (now - lastCheckTime >= VERSION_CHECK_INTERVAL) {
    checkForNewVersion();
  }

  // Clear any existing interval
  if (checkInterval) {
    clearInterval(checkInterval);
  }

  // Start periodic checks
  checkInterval = window.setInterval(checkForNewVersion, VERSION_CHECK_INTERVAL);
}

/**
 * Stop version checking (when tab is hidden)
 */
function stopVersionChecking(): void {
  if (checkInterval) {
    clearInterval(checkInterval);
    checkInterval = null;
  }
}

/**
 * Check for new version from API
 */
async function checkForNewVersion(): Promise<void> {
  lastCheckTime = Date.now();

  try {
    const { version: serverVersion } = await version.get();
    if (!serverVersion) return;

    const store = useStore.getState();

    // If we don't have an initial version stored, this is first load
    // (shouldn't happen normally since we read from HTML, but handle gracefully)
    if (!store.appVersion) {
      store.setAppVersion(serverVersion);
      return;
    }

    // Compare versions
    if (serverVersion !== store.appVersion) {
      log.info('New version available', { current: store.appVersion, server: serverVersion });
      store.setNewVersionAvailable(true);

      // Store pending version for dismiss tracking
      localStorage.setItem(DISMISSED_VERSION_KEY + '-pending', serverVersion);

      // Check if this version was already dismissed
      const dismissedVersion = localStorage.getItem(DISMISSED_VERSION_KEY);
      if (dismissedVersion !== serverVersion) {
        // New version since last dismiss, show banner
        showVersionBanner();
      } else if (!store.versionBannerDismissed) {
        // Same dismissed version but banner wasn't dismissed in this session
        showVersionBanner();
      }
    }
  } catch (error) {
    // Silently ignore version check errors
    log.debug('Version check failed', { error });
  }
}

/**
 * Show the version banner with animation
 */
function showVersionBanner(): void {
  if (bannerElement) {
    bannerElement.classList.add('visible');
  }
}

/**
 * Hide the version banner
 */
function hideVersionBanner(): void {
  if (bannerElement) {
    bannerElement.classList.remove('visible');
  }
}

/**
 * Handle visibility changes to pause/resume polling
 * For PWA: check immediately on refocus if last check was > 5 minutes ago
 */
function setupVisibilityListener(): void {
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stopVersionChecking();
    } else {
      // When becoming visible, check if we need to check immediately
      const now = Date.now();
      if (now - lastCheckTime >= VERSION_CHECK_INTERVAL) {
        // More than 5 minutes since last check, check immediately
        checkForNewVersion();
      }
      startVersionChecking();
    }
  });
}

// Expose test helper on window for development/testing
// Usage in browser console: window.__testVersionBanner()
if (typeof window !== 'undefined') {
  (window as Window & { __testVersionBanner?: () => void }).__testVersionBanner = () => {
    useStore.getState().setNewVersionAvailable(true);
    showVersionBanner();
    log.info('Version banner shown for testing');
  };
}