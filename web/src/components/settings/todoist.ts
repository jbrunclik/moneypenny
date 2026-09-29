import { CHECK_ICON, WARNING_ICON, CHECKLIST_ICON } from '../../utils/icons';
import { todoist } from '../../api/client';
import { toast } from '../Toast';
import type { TodoistStatus } from '../../types/api';
import { useStore } from '../../state/store';
import { renderConversationsList } from '../Sidebar';
import { log, renderFieldLabel, rerenderField } from './shared';

export const TODOIST_STATE_KEY = 'todoist-oauth-state';

const LABEL = 'Todoist Integration';

/** Current Todoist status */
let todoistStatus: TodoistStatus | null = null;

export function setTodoistStatus(status: TodoistStatus | null): void {
  todoistStatus = status;
}

/**
 * Render Todoist connection status
 */
function renderTodoistBody(status: TodoistStatus | null): string {
  if (status === null) {
    return `
      <div class="settings-todoist-loading">Loading Todoist status...</div>
    `;
  }

  // Token is invalid - show reconnection warning
  if (status.connected && status.needs_reconnect) {
    return `
      <div class="settings-todoist-needs-reconnect">
        <span class="settings-todoist-status">
          <span class="settings-todoist-icon warning">${WARNING_ICON}</span>
          Todoist access expired
        </span>
        <p class="settings-helper">Your Todoist connection has expired. Please reconnect to continue managing tasks.</p>
        <div class="settings-todoist-actions">
          <button type="button" class="btn btn-primary btn-sm settings-todoist-connect">
            Reconnect
          </button>
          <button type="button" class="btn btn-secondary btn-sm settings-todoist-disconnect">
            Disconnect
          </button>
        </div>
      </div>
    `;
  }

  if (status.connected) {
    return `
      <div class="settings-todoist-connected">
        <span class="settings-todoist-status">
          <span class="settings-todoist-icon connected">${CHECK_ICON}</span>
          Connected${status.todoist_email ? ` as ${status.todoist_email}` : ''}
        </span>
        <button type="button" class="btn btn-secondary btn-sm settings-todoist-disconnect">
          Disconnect
        </button>
      </div>
    `;
  }

  return `
    <div class="settings-todoist-disconnected">
      <p class="settings-helper">Connect your Todoist account to manage tasks with AI</p>
      <button type="button" class="btn btn-primary btn-sm settings-todoist-connect">
        Connect Todoist
      </button>
    </div>
  `;
}

/** Render the whole Todoist field (label + status body). */
export function renderTodoistField(): string {
  return `
      <div class="settings-field" data-section="todoist">
        ${renderFieldLabel(CHECKLIST_ICON, LABEL)}
        ${renderTodoistBody(todoistStatus)}
      </div>
  `;
}

function updateTodoistSection(): void {
  rerenderField('todoist', CHECKLIST_ICON, LABEL, renderTodoistBody(todoistStatus));
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
    todoistStatus = { connected: false, todoist_email: null, connected_at: null, needs_reconnect: false };
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
