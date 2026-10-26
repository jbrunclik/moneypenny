import { createElement } from '../../utils/dom';
import { CHECK_ICON, WARNING_ICON, CHECKLIST_ICON } from '../../utils/icons';
import { todoist } from '../../api/integrations';
import { toast } from '../Toast';
import type { TodoistStatus } from '../../types/api';
import { useStore } from '../../state/store';
import { renderConversationsList } from '../Sidebar';
import { helper, log, rerenderField, settingsField, statusLine, textButton } from './shared';

export const TODOIST_STATE_KEY = 'todoist-oauth-state';

const LABEL = 'Todoist Integration';

/** The connection status (store: settings slice). */
const todoistStatus = () => useStore.getState().integrationStatuses.todoist;
const setTodoist = (status: TodoistStatus): void => useStore.getState().setIntegrationStatus('todoist', status);

/**
 * The Todoist connection status
 */
function todoistBody(status: TodoistStatus | null): HTMLElement[] {
  if (status === null) {
    return [createElement('div', { class: 'settings-todoist-loading' }, ['Loading Todoist status...'])];
  }

  // Token is invalid - show reconnection warning
  if (status.connected && status.needs_reconnect) {
    return [
      createElement('div', { class: 'settings-todoist-needs-reconnect' }, [
        statusLine('todoist', 'warning', WARNING_ICON, 'Todoist access expired'),
        helper('Your Todoist connection has expired. Please reconnect to continue managing tasks.'),
        createElement('div', { class: 'settings-todoist-actions' }, [
          textButton('btn btn-primary btn-sm settings-todoist-connect', 'Reconnect'),
          textButton('btn btn-secondary btn-sm settings-todoist-disconnect', 'Disconnect'),
        ]),
      ]),
    ];
  }

  if (status.connected) {
    return [
      createElement('div', { class: 'settings-todoist-connected' }, [
        statusLine('todoist', 'connected', CHECK_ICON, `Connected${status.todoist_email ? ` as ${status.todoist_email}` : ''}`),
        textButton('btn btn-secondary btn-sm settings-todoist-disconnect', 'Disconnect'),
      ]),
    ];
  }

  return [
    createElement('div', { class: 'settings-todoist-disconnected' }, [
      helper('Connect your Todoist account to manage tasks with AI'),
      textButton('btn btn-primary btn-sm settings-todoist-connect', 'Connect Todoist'),
    ]),
  ];
}

/** The whole Todoist field (label + status body). */
export function renderTodoistField(): HTMLElement {
  return settingsField('todoist', CHECKLIST_ICON, LABEL, todoistBody(todoistStatus()));
}

function updateTodoistSection(): void {
  rerenderField('todoist', CHECKLIST_ICON, LABEL, todoistBody(todoistStatus()));
}

/**
 * Handle Todoist connect button click - initiate OAuth flow
 */
async function handleTodoistConnect(): Promise<void> {
  try {
    log.debug('Starting Todoist OAuth flow');
    const { auth_url, state } = await todoist.getAuthUrl();

    // Store state for verification when user returns
    sessionStorage.setItem(TODOIST_STATE_KEY, state);

    // Redirect to Todoist OAuth page
    window.location.href = auth_url;
  } catch (error) {
    log.error('Failed to start Todoist OAuth', { error });
    toast.error('Failed to connect to Todoist');
  }
}

/**
 * Handle Todoist disconnect button click
 */
async function handleTodoistDisconnect(): Promise<void> {
  try {
    log.debug('Disconnecting Todoist');
    await todoist.disconnect();
    setTodoist({ connected: false, todoist_email: null, connected_at: null, needs_reconnect: false });
    updateTodoistSection();

    // Update store and re-render sidebar to hide planner entry
    const store = useStore.getState();
    const user = store.user;
    if (user) {
      store.setUser({ ...user, todoist_connected: false });
      renderConversationsList();
    }

    toast.success('Todoist disconnected');
    log.info('Todoist disconnected');
  } catch (error) {
    log.error('Failed to disconnect Todoist', { error });
    toast.error('Failed to disconnect Todoist');
  }
}

/** Delegated click handling for the Todoist field's buttons. */
export function handleTodoistClick(target: HTMLElement): void {
  if (target.classList.contains('settings-todoist-connect')) {
    void handleTodoistConnect();
  }
  if (target.classList.contains('settings-todoist-disconnect')) {
    void handleTodoistDisconnect();
  }
}
