/**
 * App initialization module.
 * Handles app shell rendering, login overlay, and initial data loading.
 */

import { createLogger } from '../utils/logger';
import { initToast } from '../components/Toast';
import { initModal } from '../components/Modal';
import { initKbDebugToggle, initKeyboardViewportPinning } from './keyboard-viewport';
import { initComposerHeight } from './composer-height';
import { initQuickActions } from './quick-actions';
import { initAttention } from './attention';
import { initConnectivity } from './connectivity';
import { registerServiceWorker } from './push';
import { initVersionBanner } from '../components/VersionBanner';
import { initErrorReporting } from './error-reporting';
import { getElementById } from '../utils/dom';
import { initializeTheme } from '../utils/theme';
import { initPopupEscapeListener } from '../utils/popupEscapeHandler';
import { initDeepLinking } from '../router/deeplink';

import { setupEventListeners } from './events';
import { initSidebarSelection } from '../components/SidebarSelection';
import { setupTouchGestures } from './gestures';
import { initTTSVoices } from './tts';
import { initToolbarButtons } from './toolbar';
import { handleDeepLinkNavigation } from './conversation-deeplink';
import { initAgents } from './agents';
import { installAvatarFallback } from '../utils/avatar';
import { mountAppShell } from './startup/app-shell';
import { initAuthEvents, startSession } from './startup/auth';
import { initMessageEvents } from './startup/message-events';
import { initMessageScrolling } from './startup/message-scrolling';
import { initComposer } from './startup/composer';
import { initMessageUi } from './startup/message-ui';
import { initSearch } from './startup/search';

const log = createLogger('init');

/**
 * Initialize the application.
 */
export async function init(): Promise<void> {
  log.info('Initializing application');

  // First, so errors from the rest of startup reach the server too
  initErrorReporting();

  // Initialize theme early to prevent flash of wrong theme
  const { scheme, effectiveTheme } = initializeTheme();
  log.debug('Theme initialized', { scheme, effectiveTheme });

  const app = getElementById<HTMLDivElement>('app');
  if (!app) return;

  // Before any avatar renders: a dead Google photo URL falls back to initials
  installAvatarFallback();

  // Every init* below looks its elements up in the shell, so it goes first
  mountAppShell(app);

  // Initialize components
  initToast();
  initModal();
  initPopupEscapeListener(); // Single Escape key listener for all popups
  initComposer();
  initMessageUi();
  initAgents();
  initMessageScrolling();
  initKeyboardViewportPinning();
  initComposerHeight();
  initQuickActions();
  initKbDebugToggle();
  initAttention();
  initConnectivity();
  initVersionBanner();
  // Keep an existing push subscription working after reloads; actual
  // permission requests only happen from the Settings toggle
  void registerServiceWorker();
  initSearch();
  initTTSVoices();
  setupEventListeners();
  initSidebarSelection();
  setupTouchGestures();

  // Initialize toolbar buttons
  initToolbarButtons();

  // Initialize deep linking and capture initial route from URL
  const initialRoute = initDeepLinking(handleDeepLinkNavigation);

  // After every init* above: signing in renders data into those components
  await startSession(initialRoute);

  // Only once the boot session has settled (signed in and loaded, or the
  // sign-in button shown): the handlers below assume startup is done
  initAuthEvents();
  initMessageEvents();
}
