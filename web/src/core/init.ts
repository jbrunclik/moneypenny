/**
 * App startup: the order the app's features start in.
 *
 * Each feature's startup lives in its own module (core/startup/*.ts, or the
 * feature's own init function) and hooks in here with one line. Add a new
 * feature as one line in the right place; the comments mark the steps whose
 * order matters.
 */

import { initSidebarSelection } from '../components/SidebarSelection';
import { initModal } from '../components/Modal';
import { initToast } from '../components/Toast';
import { initDeepLinking } from '../router/deeplink';
import { installAvatarFallback } from '../utils/avatar';
import { getElementById } from '../utils/dom';
import { createLogger } from '../utils/logger';
import { initPopupEscapeListener } from '../utils/popupEscapeHandler';
import { initializeTheme } from '../utils/theme';
import { initAgents } from './agents';
import { initComposerHeight } from './composer-height';
import { handleDeepLinkNavigation } from './conversation-deeplink';
import { initErrorReporting } from './error-reporting';
import { setupEventListeners } from './events';
import { setupTouchGestures } from './gestures';
import { initKbDebugToggle, initKeyboardViewportPinning } from './keyboard-viewport';
import { initQuickActions } from './quick-actions';
import { initToolbarButtons } from './toolbar';
import { initTTSVoices } from './tts';
import { mountAppShell } from './startup/app-shell';
import { initAppStatus } from './startup/app-status';
import { initAuthEvents, startSession } from './startup/auth';
import { initComposer } from './startup/composer';
import { initMessageEvents } from './startup/message-events';
import { initMessageScrolling } from './startup/message-scrolling';
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
  initAppStatus();
  initSearch();
  initTTSVoices();
  setupEventListeners();
  initSidebarSelection();
  setupTouchGestures();
  initToolbarButtons();

  // Capture the initial route from the URL BEFORE the session starts: a
  // signed-out start clears the conversation hash
  const initialRoute = initDeepLinking(handleDeepLinkNavigation);

  // After every init* above: signing in renders data into those components
  await startSession(initialRoute);

  // Only once the boot session has settled (signed in and loaded, or the
  // sign-in button shown): the handlers below assume startup is done
  initAuthEvents();
  initMessageEvents();
}
