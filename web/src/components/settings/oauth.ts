/**
 * OAuth redirect completion for the Todoist and Google Calendar
 * integrations. Called on app initialization (only while a flow is in
 * progress) to finish the connection and reopen Settings.
 */
import { todoist, calendar } from '../../api/client';
import { toast } from '../Toast';
import { useStore } from '../../state/store';
import { renderConversationsList } from '../Sidebar';
import { openSettingsPopup } from '../SettingsPopup';
import { log } from './shared';
import { TODOIST_STATE_KEY, setTodoistStatus } from './todoist';
import { CALENDAR_STATE_KEY, setCalendarStatus } from './calendar';

interface OAuthFlow {
  name: string;
  stateKey: string;
  /** Exchange the code, adopt the new status and flag the user as connected. */
  complete: (code: string, state: string) => Promise<void>;
}

/**
 * Shared callback handling: returns false when this flow is not in
 * progress or the URL is not a callback, true once handled (either way).
 */
async function handleOAuthCallback(flow: OAuthFlow): Promise<boolean> {
  const urlParams = new URLSearchParams(window.location.search);
  const code = urlParams.get('code');
  const state = urlParams.get('state');
  const error = urlParams.get('error');

  // Check if this flow is pending (state stored in sessionStorage)
  const storedState = sessionStorage.getItem(flow.stateKey);
  if (!storedState) {
    // Not in progress - let other handlers process this
    return false;
  }

  // Check if this is an OAuth callback
  if (!code && !error) {
    return false;
  }

  // Clear URL params
  window.history.replaceState({}, '', window.location.pathname + window.location.hash);

  if (error) {
    log.error(`${flow.name} OAuth error`, { error });
    toast.error(`Failed to connect ${flow.name}: ` + error);
    sessionStorage.removeItem(flow.stateKey);
    return true;
  }

  // Verify state
  if (state !== storedState) {
    log.error(`${flow.name} OAuth state mismatch`, { expected: storedState, received: state });
    toast.error(`Failed to connect ${flow.name}: Invalid state`);
    sessionStorage.removeItem(flow.stateKey);
    return true;
  }

  sessionStorage.removeItem(flow.stateKey);

  try {
    log.debug(`Exchanging ${flow.name} OAuth code for token`);
    await flow.complete(code as string, state as string);
    // Open settings popup to show the connected state
    openSettingsPopup();
  } catch (err) {
    log.error(`Failed to complete ${flow.name} OAuth`, { error: err });
    toast.error(`Failed to connect ${flow.name}`);
  }

  return true;
}

/** Flag the user as connected and re-render the sidebar (planner entry). */
function markUserConnected(flag: 'todoist_connected' | 'calendar_connected'): void {
  const store = useStore.getState();
  const user = store.user;
  if (user) {
    store.setUser({ ...user, [flag]: true });
    renderConversationsList();
  }
}

/**
 * Check for a Todoist OAuth callback and complete the connection.
 * Returns true if this was an OAuth callback (handled), false otherwise.
 */
export function checkTodoistOAuthCallback(): Promise<boolean> {
  return handleOAuthCallback({
    name: 'Todoist',
    stateKey: TODOIST_STATE_KEY,
    complete: async (code, state) => {
      const result = await todoist.connect(code, state);
      setTodoistStatus({
        connected: result.connected,
        todoist_email: result.todoist_email,
        connected_at: new Date().toISOString(),
        needs_reconnect: false,
      });
      markUserConnected('todoist_connected');
      toast.success('Todoist connected successfully');
      log.info('Todoist connected', { email: result.todoist_email });
    },
  });
}

/**
 * Check for a Google Calendar OAuth callback and complete the connection.
 * Returns true if this was an OAuth callback (handled), false otherwise.
 */
export function checkCalendarOAuthCallback(): Promise<boolean> {
  return handleOAuthCallback({
    name: 'Google Calendar',
    stateKey: CALENDAR_STATE_KEY,
    complete: async (code, state) => {
      const result = await calendar.connect(code, state);
      setCalendarStatus({
        connected: result.connected,
        calendar_email: result.calendar_email,
        connected_at: new Date().toISOString(),
        needs_reconnect: false,
      });
      markUserConnected('calendar_connected');
      toast.success('Google Calendar connected successfully');
      log.info('Google Calendar connected', { email: result.calendar_email });
    },
  });
}
