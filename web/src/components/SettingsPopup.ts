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
import { settings, todoist } from '../api/client';
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
import type { TodoistStatus } from '../types/api';

const log = createLogger('settings-popup');

const POPUP_ID = 'settings-popup';
const CHAR_LIMIT = 2000;
const TODOIST_STATE_KEY = 'todoist-oauth-state';

/** Current custom instructions value */
let currentInstructions = '';

/** Current color scheme value */
let currentColorScheme: ColorScheme = 'system';

/** Current Todoist status */
let todoistStatus: TodoistStatus | null = null;

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

/**
 * Render the popup content
 */
function renderContent(instructions: string, colorScheme: ColorScheme, todoistSt: TodoistStatus | null): string {
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

      <div class="settings-field">
        <label class="settings-label">Todoist Integration</label>
        ${renderTodoistSection(todoistSt)}
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

    // Update UI
    const popup = getElementById<HTMLDivElement>(POPUP_ID);
    if (popup) {
      const todoistSection = popup.querySelector('.settings-field:has(.settings-todoist-connected), .settings-field:has(.settings-todoist-disconnected)');
      if (todoistSection) {
        const labelEl = todoistSection.querySelector('.settings-label');
        if (labelEl) {
          todoistSection.innerHTML = `
            <label class="settings-label">Todoist Integration</label>
            ${renderTodoistSection(todoistStatus)}
          `;
        }
      }
    }

    toast.success('Todoist disconnected');
    log.info('Todoist disconnected');
  } catch (error) {
    log.error('Failed to disconnect Todoist', { error });
    toast.error('Failed to disconnect Todoist');
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

  // Check if this is a Todoist OAuth callback
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
  const storedState = sessionStorage.getItem(TODOIST_STATE_KEY);
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

    // Fetch both in parallel - Todoist status is optional, don't block on failure
    const [settingsData, todoistData] = await Promise.all([
      settings.get(),
      todoist.getStatus().catch((err) => {
        log.warn('Failed to fetch Todoist status', { error: err });
        return null;
      }),
    ]);

    currentInstructions = settingsData.custom_instructions || '';
    todoistStatus = todoistData;
    log.info('Settings loaded', {
      instructionsLength: currentInstructions.length,
      todoistConnected: todoistStatus?.connected ?? false,
    });

    // Update popup body
    const body = popup.querySelector('.info-popup-body');
    if (body) {
      body.outerHTML = `<div class="info-popup-body">${renderContent(currentInstructions, currentColorScheme, todoistStatus)}</div>`;
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
