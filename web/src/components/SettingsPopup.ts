import { getElementById } from '../utils/dom';
import {
  SETTINGS_ICON,
  CLOSE_ICON,
  SUN_ICON,
  MOON_ICON,
  MONITOR_ICON,
  CHECK_ICON,
  WARNING_ICON,
} from '../utils/icons';
import { settings, todoist, calendar } from '../api/client';
import { toast } from './Toast';
import { createLogger } from '../utils/logger';
import {
  type ColorScheme,
  getStoredColorScheme,
  saveColorScheme,
  applyColorScheme,
  setupSystemPreferenceListener,
} from '../utils/theme';
import { registerPopupEscapeHandler } from '../utils/popupEscapeHandler';
import type { TodoistStatus, CalendarStatus } from '../types/api';

const log = createLogger('settings-popup');

const POPUP_ID = 'settings-popup';
const CHAR_LIMIT = 2000;
const TODOIST_STATE_KEY = 'todoist-oauth-state';
const CALENDAR_STATE_KEY = 'calendar-oauth-state';

/** Current custom instructions value */
let currentInstructions = '';

/** Current color scheme value */
let currentColorScheme: ColorScheme = 'system';

/** Current Todoist status */
let todoistStatus: TodoistStatus | null = null;

/** Current Google Calendar status */
let calendarStatus: CalendarStatus | null = null;

/**
 * Render color scheme option
 */
function renderColorSchemeOption(
  value: ColorScheme,
  icon: string,
  label: string,
  selected: boolean
): string {
  return `
    <button
      type="button"
      class="settings-color-scheme-option${selected ? ' selected' : ''}"
      data-color-scheme="${value}"
    >
      <span class="settings-color-scheme-icon">${icon}</span>
      <span class="settings-color-scheme-label">${label}</span>
    </button>
  `;
}

/**
 * Render Todoist connection status
 */
function renderTodoistSection(status: TodoistStatus | null): string {
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

function renderCalendarSection(status: CalendarStatus | null): string {
  if (status === null) {
    return `
      <div class="settings-calendar-loading">Loading Google Calendar status...</div>
    `;
  }

  if (status.connected && status.needs_reconnect) {
    return `
      <div class="settings-calendar-needs-reconnect">
        <span class="settings-calendar-status">
          <span class="settings-calendar-icon warning">${WARNING_ICON}</span>
          Google Calendar access expired
        </span>
        <p class="settings-helper">Your Google Calendar connection has expired. Please reconnect to keep scheduling events.</p>
        <div class="settings-calendar-actions">
          <button type="button" class="btn btn-primary btn-sm settings-calendar-connect">
            Reconnect
          </button>
          <button type="button" class="btn btn-secondary btn-sm settings-calendar-disconnect">
            Disconnect
          </button>
        </div>
      </div>
    `;
  }

  if (status.connected) {
    return `
      <div class="settings-calendar-connected">
        <span class="settings-calendar-status">
          <span class="settings-calendar-icon connected">${CHECK_ICON}</span>
          Connected${status.calendar_email ? ` as ${status.calendar_email}` : ''}
        </span>
        <button type="button" class="btn btn-secondary btn-sm settings-calendar-disconnect">
          Disconnect
        </button>
      </div>
    `;
  }

  return `
    <div class="settings-calendar-disconnected">
      <p class="settings-helper">Connect Google Calendar to schedule events and focus blocks with AI</p>
      <button type="button" class="btn btn-primary btn-sm settings-calendar-connect">
        Connect Google Calendar
      </button>
    </div>
  `;
}

/**
 * Render the popup content
 */
function renderContent(
  instructions: string,
  colorScheme: ColorScheme,
  todoistSt: TodoistStatus | null,
  calendarSt: CalendarStatus | null
): string {
  const charCount = instructions.length;
  const charCountClass = charCount > CHAR_LIMIT ? 'error' : charCount > CHAR_LIMIT * 0.9 ? 'warning' : '';

  return `
    <div class="settings-body">
      <div class="settings-field">
        <label class="settings-label">Appearance</label>
        <div class="settings-color-scheme">
          ${renderColorSchemeOption('light', SUN_ICON, 'Light', colorScheme === 'light')}
          ${renderColorSchemeOption('dark', MOON_ICON, 'Dark', colorScheme === 'dark')}
          ${renderColorSchemeOption('system', MONITOR_ICON, 'System', colorScheme === 'system')}
        </div>
      </div>

      <div class="settings-divider"></div>

      <div class="settings-field" data-section="todoist">
        <label class="settings-label">Todoist Integration</label>
        ${renderTodoistSection(todoistSt)}
      </div>

      <div class="settings-divider"></div>

      <div class="settings-field" data-section="calendar">
        <label class="settings-label">Google Calendar Integration</label>
        ${renderCalendarSection(calendarSt)}
      </div>

      <div class="settings-divider"></div>

      <div class="settings-field">
        <label class="settings-label" for="custom-instructions">Custom Instructions</label>
        <p class="settings-helper">Tell the AI how to respond (e.g., "respond in Czech", "be concise", "use bullet points")</p>
        <textarea
          id="custom-instructions"
          class="settings-textarea"
          placeholder="Enter your custom instructions here..."
          maxlength="${CHAR_LIMIT}"
        >${instructions}</textarea>
        <span class="settings-char-count ${charCountClass}">${charCount}/${CHAR_LIMIT}</span>
      </div>
    </div>
  `;
}

/**
 * Update character count display
 */
function updateCharCount(textarea: HTMLTextAreaElement): void {
  const charCount = textarea.value.length;
  const charCountEl = document.querySelector('.settings-char-count');
  if (charCountEl) {
    charCountEl.textContent = `${charCount}/${CHAR_LIMIT}`;
    charCountEl.className = 'settings-char-count';
    if (charCount > CHAR_LIMIT) {
      charCountEl.classList.add('error');
    } else if (charCount > CHAR_LIMIT * 0.9) {
      charCountEl.classList.add('warning');
    }
  }
}

/**
 * Save settings
 */
async function saveSettings(): Promise<void> {
  const textarea = document.getElementById('custom-instructions') as HTMLTextAreaElement;
  if (!textarea) return;

  const instructions = textarea.value.trim();

  // Check if value changed
  if (instructions === currentInstructions) {
    closeSettingsPopup();
    return;
  }

  log.debug('Saving settings', { instructionsLength: instructions.length });

  try {
    await settings.update({ custom_instructions: instructions });
    currentInstructions = instructions;
    closeSettingsPopup();
    toast.success('Settings saved');
    log.info('Settings saved', { instructionsLength: instructions.length });
  } catch (error) {
    log.error('Failed to save settings', { error });
    toast.error('Failed to save settings');
  }
}

/**
 * Handle color scheme option click
 */
function handleColorSchemeClick(scheme: ColorScheme): void {
  if (scheme === currentColorScheme) return;

  // Update selection UI
  const options = document.querySelectorAll('.settings-color-scheme-option');
  options.forEach((option) => {
    const optionScheme = (option as HTMLElement).dataset.colorScheme as ColorScheme;
    option.classList.toggle('selected', optionScheme === scheme);
  });

  // Apply and save the theme
  currentColorScheme = scheme;
  saveColorScheme(scheme);
  applyColorScheme(scheme);

  log.info('Color scheme changed', { scheme });
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
    updateIntegrationSection('todoist');
    toast.success('Todoist disconnected');
    log.info('Todoist disconnected');
  } catch (error) {
    log.error('Failed to disconnect Todoist', { error });
    toast.error('Failed to disconnect Todoist');
  }
}

async function handleCalendarConnect(): Promise<void> {
  try {
    log.debug('Starting Google Calendar OAuth flow');
    const { auth_url, state } = await calendar.getAuthUrl();
    sessionStorage.setItem(CALENDAR_STATE_KEY, state);
    window.location.href = auth_url;
  } catch (error) {
    log.error('Failed to start Google Calendar OAuth', { error });
    toast.error('Failed to connect Google Calendar');
  }
}

async function handleCalendarDisconnect(): Promise<void> {
  try {
    log.debug('Disconnecting Google Calendar');
    await calendar.disconnect();
    calendarStatus = { connected: false, calendar_email: null, connected_at: null, needs_reconnect: false };
    updateIntegrationSection('calendar');
    toast.success('Google Calendar disconnected');
    log.info('Google Calendar disconnected');
  } catch (error) {
    log.error('Failed to disconnect Google Calendar', { error });
    toast.error('Failed to disconnect Google Calendar');
  }
}

function updateIntegrationSection(section: 'todoist' | 'calendar'): void {
  const popup = getElementById<HTMLDivElement>(POPUP_ID);
  if (!popup) return;

  const field = popup.querySelector(`.settings-field[data-section="${section}"]`);
  if (!field) return;

  const label = section === 'todoist' ? 'Todoist Integration' : 'Google Calendar Integration';
  const content = section === 'todoist' ? renderTodoistSection(todoistStatus) : renderCalendarSection(calendarStatus);
  field.innerHTML = `
    <label class="settings-label">${label}</label>
    ${content}
  `;

  if (section === 'todoist') {
    field.querySelector('.settings-todoist-connect')?.addEventListener('click', handleTodoistConnect);
    field.querySelector('.settings-todoist-disconnect')?.addEventListener('click', handleTodoistDisconnect);
  } else {
    field.querySelector('.settings-calendar-connect')?.addEventListener('click', handleCalendarConnect);
    field.querySelector('.settings-calendar-disconnect')?.addEventListener('click', handleCalendarDisconnect);
  }
}

/**
 * Check for OAuth callback and complete connection.
 * Call this on app initialization to handle the OAuth redirect.
 * Returns true if this was an OAuth callback (handled), false otherwise.
 */
export async function checkTodoistOAuthCallback(): Promise<boolean> {
  const urlParams = new URLSearchParams(window.location.search);
  const code = urlParams.get('code');
  const state = urlParams.get('state');
  const error = urlParams.get('error');

  // Check if we have a pending Todoist OAuth (state stored in sessionStorage)
  const storedState = sessionStorage.getItem(TODOIST_STATE_KEY);
  if (!storedState) {
    // No Todoist OAuth in progress - let other handlers process this
    return false;
  }

  // Check if this is an OAuth callback
  if (!code && !error) {
    return false;
  }

  // Clear URL params
  window.history.replaceState({}, '', window.location.pathname + window.location.hash);

  if (error) {
    log.error('Todoist OAuth error', { error });
    toast.error('Failed to connect Todoist: ' + error);
    sessionStorage.removeItem(TODOIST_STATE_KEY);
    return true;
  }

  // Verify state
  if (state !== storedState) {
    log.error('Todoist OAuth state mismatch', { expected: storedState, received: state });
    toast.error('Failed to connect Todoist: Invalid state');
    sessionStorage.removeItem(TODOIST_STATE_KEY);
    return true;
  }

  sessionStorage.removeItem(TODOIST_STATE_KEY);

  // Exchange code for token
  try {
    log.debug('Exchanging Todoist OAuth code for token');
    const result = await todoist.connect(code as string, state as string);
    todoistStatus = {
      connected: result.connected,
      todoist_email: result.todoist_email,
      connected_at: new Date().toISOString(),
      needs_reconnect: false,
    };
    toast.success('Todoist connected successfully');
    log.info('Todoist connected', { email: result.todoist_email });

    // Open settings popup to show the connected state
    openSettingsPopup();
  } catch (err) {
    log.error('Failed to complete Todoist OAuth', { error: err });
    toast.error('Failed to connect Todoist');
  }

  return true;
}

export async function checkCalendarOAuthCallback(): Promise<boolean> {
  const urlParams = new URLSearchParams(window.location.search);
  const code = urlParams.get('code');
  const state = urlParams.get('state');
  const error = urlParams.get('error');

  // Check if we have a pending Calendar OAuth (state stored in sessionStorage)
  const storedState = sessionStorage.getItem(CALENDAR_STATE_KEY);
  if (!storedState) {
    // No Calendar OAuth in progress - let other handlers process this
    return false;
  }

  if (!code && !error) {
    return false;
  }

  window.history.replaceState({}, '', window.location.pathname + window.location.hash);

  if (error) {
    log.error('Google Calendar OAuth error', { error });
    toast.error('Failed to connect Google Calendar: ' + error);
    sessionStorage.removeItem(CALENDAR_STATE_KEY);
    return true;
  }

  // Verify state
  if (state !== storedState) {
    log.error('Google Calendar OAuth state mismatch', { expected: storedState, received: state });
    toast.error('Failed to connect Google Calendar: Invalid state');
    sessionStorage.removeItem(CALENDAR_STATE_KEY);
    return true;
  }

  sessionStorage.removeItem(CALENDAR_STATE_KEY);

  try {
    log.debug('Exchanging Google Calendar OAuth code for token');
    const result = await calendar.connect(code as string, state as string);
    calendarStatus = {
      connected: result.connected,
      calendar_email: result.calendar_email,
      connected_at: new Date().toISOString(),
      needs_reconnect: false,
    };
    toast.success('Google Calendar connected successfully');
    log.info('Google Calendar connected', { email: result.calendar_email });
    openSettingsPopup();
  } catch (err) {
    log.error('Failed to complete Google Calendar OAuth', { error: err });
    toast.error('Failed to connect Google Calendar');
  }

  return true;
}

/**
 * Open the settings popup
 */
export async function openSettingsPopup(): Promise<void> {
  const popup = getElementById<HTMLDivElement>(POPUP_ID);
  if (!popup) return;

  // Load current color scheme
  currentColorScheme = getStoredColorScheme();

  // Show popup with loading state
  const content = popup.querySelector('.info-popup-content');
  if (content) {
    content.innerHTML = `
      <div class="info-popup-header">
        <span class="info-popup-icon">${SETTINGS_ICON}</span>
        <h3>Settings</h3>
        <button class="info-popup-close" aria-label="Close">${CLOSE_ICON}</button>
      </div>
      <div class="info-popup-body settings-body">
        <div class="settings-loading">Loading settings...</div>
      </div>
      <div class="info-popup-footer settings-footer">
        <button class="btn btn-primary settings-save-btn" disabled>Save</button>
      </div>
    `;

    // Attach close handler
    content.querySelector('.info-popup-close')?.addEventListener('click', closeSettingsPopup);
  }

  popup.classList.remove('hidden');

  // Fetch settings and Todoist status in parallel
  try {
    log.debug('Fetching settings and Todoist status');

    const [settingsData, todoistData, calendarData] = await Promise.all([
      settings.get(),
      todoist.getStatus().catch((err) => {
        log.warn('Failed to fetch Todoist status', { error: err });
        return null;
      }),
      calendar.getStatus().catch((err) => {
        log.warn('Failed to fetch Google Calendar status', { error: err });
        return null;
      }),
    ]);

    currentInstructions = settingsData.custom_instructions || '';
    todoistStatus = todoistData;
    calendarStatus = calendarData;
    log.info('Settings loaded', {
      instructionsLength: currentInstructions.length,
      todoistConnected: todoistStatus?.connected ?? false,
      calendarConnected: calendarStatus?.connected ?? false,
    });

    // Update popup body
    const body = popup.querySelector('.info-popup-body');
    if (body) {
      body.outerHTML = `<div class="info-popup-body">${renderContent(currentInstructions, currentColorScheme, todoistStatus, calendarStatus)}</div>`;
    }

    // Enable save button and attach handlers
    const saveBtn = popup.querySelector('.settings-save-btn') as HTMLButtonElement;
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.addEventListener('click', saveSettings);
    }

    // Attach textarea input handler for character count
    const textarea = document.getElementById('custom-instructions') as HTMLTextAreaElement;
    if (textarea) {
      textarea.addEventListener('input', () => updateCharCount(textarea));
      // Focus the textarea
      textarea.focus();
    }

    // Attach color scheme click handlers
    const colorSchemeOptions = popup.querySelectorAll('.settings-color-scheme-option');
    colorSchemeOptions.forEach((option) => {
      option.addEventListener('click', () => {
        const scheme = (option as HTMLElement).dataset.colorScheme as ColorScheme;
        handleColorSchemeClick(scheme);
      });
    });

    popup.querySelector('.settings-todoist-connect')?.addEventListener('click', handleTodoistConnect);
    popup.querySelector('.settings-todoist-disconnect')?.addEventListener('click', handleTodoistDisconnect);
    popup.querySelector('.settings-calendar-connect')?.addEventListener('click', handleCalendarConnect);
    popup.querySelector('.settings-calendar-disconnect')?.addEventListener('click', handleCalendarDisconnect);
  } catch (error) {
    log.error('Failed to load settings', { error });
    const body = popup.querySelector('.info-popup-body');
    if (body) {
      body.innerHTML = `
        <div class="settings-error">
          <p>Failed to load settings.</p>
          <button class="btn btn-secondary settings-retry-btn">Retry</button>
        </div>
      `;
    }
  }
}

/**
 * Close the settings popup
 */
export function closeSettingsPopup(): void {
  const popup = getElementById<HTMLDivElement>(POPUP_ID);
  if (popup) {
    popup.classList.add('hidden');
  }
}

/**
 * Initialize settings popup and theme system
 */
export function initSettingsPopup(): void {
  const popup = getElementById<HTMLDivElement>(POPUP_ID);
  if (!popup) return;

  // Close on backdrop click
  popup.addEventListener('click', (e) => {
    if (e.target === popup) {
      closeSettingsPopup();
    }
  });

  // Register with centralized Escape key handler
  registerPopupEscapeHandler(POPUP_ID, closeSettingsPopup);

  // Event delegation for buttons
  popup.addEventListener('click', (e) => {
    const target = e.target as HTMLElement;

    // Retry button
    if (target.classList.contains('settings-retry-btn')) {
      openSettingsPopup();
    }

    // Todoist connect button
    if (target.classList.contains('settings-todoist-connect')) {
      handleTodoistConnect();
    }

    // Todoist disconnect button
    if (target.classList.contains('settings-todoist-disconnect')) {
      handleTodoistDisconnect();
    }

    if (target.classList.contains('settings-calendar-connect')) {
      handleCalendarConnect();
    }

    if (target.classList.contains('settings-calendar-disconnect')) {
      handleCalendarDisconnect();
    }
  });

  // Set up system preference listener for when 'system' is selected
  // Note: This listener is never cleaned up since the popup/app lives forever
  setupSystemPreferenceListener(() => {
    const currentScheme = getStoredColorScheme();
    if (currentScheme === 'system') {
      // Re-apply when system preference changes and 'system' is selected
      applyColorScheme('system');
    }
  });

  log.debug('Settings popup initialized');
}

/**
 * Get HTML for settings popup shell
 */
export function getSettingsPopupHtml(): string {
  return `
    <div id="${POPUP_ID}" class="info-popup hidden">
      <div class="info-popup-content">
        <!-- Content populated dynamically -->
      </div>
    </div>
  `;
}
