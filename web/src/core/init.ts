/**
 * App startup: the order the app's features start in.
 *
 * Each feature's startup lives in its own module (core/startup/*.ts, or the
 * feature's own init function) and hooks in here with one line. Add a new
 * feature as one line in the right place; the comments mark the steps whose
 * order matters.
 */

import { renderConversationsList } from '../components/Sidebar';
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
import { leaveArchiveView } from './archive';
import { initComposerHeight } from './composer-height';
import { bulkDeleteConversations } from './conversation-actions';
import { handleDeepLinkNavigation } from './conversation-deeplink';
import { initErrorReporting } from './error-reporting';
import { setupEventListeners } from './events';
import { setupTouchGestures } from './gestures';
import { initKeyboardViewportPinning } from './keyboard-viewport';
import { initKbDebugToggle } from './keyboard/debug-overlay';
import { initLayoutChecks } from './layout-checks';
import { initQuickActions } from './quick-actions';
import { initToolbarButtons } from './toolbar';
import { leaveTrashView } from './trash';
import { initTTSVoices } from './tts';
import { mountAppShell } from './startup/app-shell';
import { initAppStatus } from './startup/app-status';
import { markAppReady } from './startup/app-ready';
import { initAuthEvents, startSession } from './startup/auth';
import { initComposer } from './startup/composer';
import { initMessageEvents } from './startup/message-events';
import { initMessageScrolling } from './startup/message-scrolling';
import { initMessageUi } from './startup/message-ui';
import { initNavigation } from './startup/navigation';
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

  // Before anything can navigate: conversation selection and switching
  // reach the feature views through the hooks this sets
  initNavigation();

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
  // After the keyboard pinning: it observes what that code applies
  initLayoutChecks();
  initAppStatus();
  initSearch();
  initTTSVoices();
  setupEventListeners();
  initSidebarSelection({
    renderConversationsList,
    bulkDelete: bulkDeleteConversations,
    leaveTrashView,
    leaveArchiveView,
  });
  setupTouchGestures();
  initToolbarButtons();

  // Capture the initial route from the URL BEFORE the session starts: a
  // signed-out start clears the conversation hash
  const initialRoute = initDeepLinking(handleDeepLinkNavigation);

  // After every init* above: signing in renders data into those components
  const signedIn = await startSession(initialRoute);

  // Only once the boot session has settled (signed in and loaded, or the
  // sign-in button shown): the handlers below assume startup is done
  initAuthEvents();
  initMessageEvents();
  // Signed in, ready waits for the first sync (startup/initial-data.ts)
  if (!signedIn) markAppReady();
}
