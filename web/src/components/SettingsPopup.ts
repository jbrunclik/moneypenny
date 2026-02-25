import { getElementById, escapeHtml } from '../utils/dom';
import {
  SETTINGS_ICON,
  CLOSE_ICON,
  SUN_ICON,
  MOON_ICON,
  MONITOR_ICON,
  CHECK_ICON,
  WARNING_ICON,
  CHECKLIST_ICON,
  CALENDAR_ICON,
  EDIT_ICON,
  STAR_ICON,
  PHONE_ICON,
  ACTIVITY_ICON,
} from '../utils/icons';
import { settings, todoist, calendar, garmin } from '../api/client';
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
import type { TodoistStatus, CalendarStatus, GarminStatus, Calendar } from '../types/api';
import { useStore } from '../state/store';
import { renderConversationsList } from './Sidebar';

const log = createLogger('settings-popup');

const POPUP_ID = 'settings-popup';
const CHAR_LIMIT = 2000;
const TODOIST_STATE_KEY = 'todoist-oauth-state';
const CALENDAR_STATE_KEY = 'calendar-oauth-state';

/** Current custom instructions value */
let currentInstructions = '';

/** Current WhatsApp phone number */
let currentWhatsappPhone = '';

/** Whether WhatsApp is available at the app level */
let whatsappAvailable = false;

/** Current color scheme value */
let currentColorScheme: ColorScheme = 'system';

/** Current Todoist status */
let todoistStatus: TodoistStatus | null = null;

/** Current Google Calendar status */
let calendarStatus: CalendarStatus | null = null;

/** Available calendars from Google */
let availableCalendars: Calendar[] | null = null;

/** Selected calendar IDs */
let selectedCalendarIds: string[] = ['primary'];

/** Loading state for calendar list */
let calendarsLoading = false;

/** Error message when fetching calendar list fails */
let calendarsError: string | null = null;

/** Current Garmin Connect status */

let garminStatus: GarminStatus | null = null;

/** Garmin MFA state: awaiting MFA code input */

let garminMfaRequired = false;

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
 * Render calendar selection UI with checkboxes
 */
function renderCalendarSelection(
  calendars: Calendar[],
  selected: string[],
  loading: boolean,
  error: string | null = null
): string {
  if (loading) {
    return `
      <div class="settings-calendar-loading">
        <div class="spinner-small"></div>
        <span>Loading calendars...</span>
      </div>
    `;
  }

  // Show error message if present (from backend)
  if (error) {
    return `
      <div class="settings-calendar-error">
        <span class="settings-calendar-icon warning">${WARNING_ICON}</span>
        <div>
          <p class="settings-error-message">${escapeHtml(error)}</p>
          ${error.toLowerCase().includes('expired') || error.toLowerCase().includes('reconnect')
            ? '<p class="settings-helper">Please disconnect and reconnect your Google Calendar in the section above.</p>'
            : '<p class="settings-helper">Please try refreshing the page or check your connection.</p>'}
        </div>
      </div>
    `;
  }

  if (calendars.length === 0) {
    return `
      <div class="settings-empty-state">
        <p>No calendars available. Create one in Google Calendar first.</p>
      </div>
    `;
  }

  return `
    <div class="settings-calendar-list">
      ${calendars.map(cal => {
        const isPrimary = cal.primary || cal.id === 'primary';
        const isChecked = isPrimary || selected.includes(cal.id); // Primary always checked
        const isDisabled = isPrimary; // Primary calendar cannot be unchecked

        return `
          <label class="settings-calendar-item${isDisabled ? ' disabled' : ''}" data-calendar-id="${escapeHtml(cal.id)}">
            <input
              type="checkbox"
              class="settings-calendar-checkbox"
              data-calendar-id="${escapeHtml(cal.id)}"
              ${isChecked ? 'checked' : ''}
              ${isDisabled ? 'disabled' : ''}
            />
            <div class="settings-calendar-info">
              ${cal.background_color ? `<span class="calendar-color-dot" style="background-color: ${escapeHtml(cal.background_color)}"></span>` : ''}
              ${isPrimary ? `<span class="calendar-star-icon">${STAR_ICON}</span>` : ''}
              <span class="settings-calendar-name">${escapeHtml(cal.summary)}</span>
              ${cal.access_role !== 'owner' && !isPrimary ? `<span class="settings-calendar-badge">${escapeHtml(cal.access_role)}</span>` : ''}
            </div>
          </label>
        `;
      }).join('')}
    </div>
    <p class="settings-helper">
      ${selected.length === 1 ? '1 calendar selected' : `${selected.length} calendars selected`}
    </p>
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
    const calendarSelectionHtml = renderCalendarSelection(
      availableCalendars || [],
      selectedCalendarIds,
      calendarsLoading,
      calendarsError
    );

    return `
      <div class="settings-calendar-connected-wrapper">
        <div class="settings-calendar-connected">
          <span class="settings-calendar-status">
            <span class="settings-calendar-icon connected">${CHECK_ICON}</span>
            Connected${status.calendar_email ? ` as ${status.calendar_email}` : ''}
          </span>
          <button type="button" class="btn btn-secondary btn-sm settings-calendar-disconnect">
            Disconnect
          </button>
        </div>

        <div class="settings-calendar-selection">
          <label class="settings-label">Show events from:</label>
          ${calendarSelectionHtml}
          <button
            type="button"
            class="btn btn-primary settings-calendar-save-btn"
            ${selectedCalendarIds.length === 0 || calendarsLoading ? 'disabled' : ''}
          >
            Save Selection
          </button>
        </div>
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
 * Render Garmin Connect section
 */
function renderGarminSection(status: GarminStatus | null, mfaRequired: boolean): string {
  if (status === null) {
    return `
      <div class="settings-garmin-loading">Loading Garmin status...</div>
    `;
  }

  if (mfaRequired) {
    return `
      <div class="settings-garmin-mfa">
        <p class="settings-helper">Garmin requires a verification code. Check your email or authenticator app.</p>
        <input
          type="text"
          class="settings-input settings-garmin-mfa-input"
          placeholder="Enter MFA code"
          maxlength="10"
          autocomplete="one-time-code"
        />
        <div class="settings-garmin-actions">
          <button type="button" class="btn btn-primary settings-garmin-mfa-submit">
            Submit
          </button>
          <button type="button" class="btn btn-secondary settings-garmin-mfa-cancel">
            Cancel
          </button>
        </div>
      </div>
    `;
  }

  if (status.connected && status.needs_reconnect) {
    return `
      <div class="settings-garmin-needs-reconnect">
        <span class="settings-garmin-status">
          <span class="settings-garmin-icon warning">${WARNING_ICON}</span>
          Garmin session expired
        </span>
        <p class="settings-helper">Your Garmin session has expired. Please reconnect with your credentials.</p>
        <div class="settings-garmin-actions">
          <button type="button" class="btn btn-primary btn-sm settings-garmin-show-login">
            Reconnect
          </button>
          <button type="button" class="btn btn-secondary btn-sm settings-garmin-disconnect">
            Disconnect
          </button>
        </div>
      </div>
    `;
  }

  if (status.connected) {
    return `
      <div class="settings-garmin-connected">
        <span class="settings-garmin-status">
          <span class="settings-garmin-icon connected">${CHECK_ICON}</span>
          Connected
        </span>
        <button type="button" class="btn btn-secondary btn-sm settings-garmin-disconnect">
          Disconnect
        </button>
      </div>
    `;
  }

  return `
    <div class="settings-garmin-disconnected">
      <p class="settings-helper">Connect your Garmin account to access health and training data</p>
      <div class="settings-garmin-login-form">
        <input
          type="email"
          class="settings-input settings-garmin-email"
          placeholder="Garmin email"
          autocomplete="email"
        />
        <input
          type="password"
          class="settings-input settings-garmin-password"
          placeholder="Garmin password"
          autocomplete="current-password"
        />
        <p class="settings-helper settings-helper-muted">Your password is used to create a session token and is never stored.</p>
        <button type="button" class="btn btn-primary settings-garmin-connect">
          Connect Garmin
        </button>
      </div>
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
  calendarSt: CalendarStatus | null,
  garminSt: GarminStatus | null = null,
  garminMfa: boolean = false,
): string {
  const charCount = instructions.length;
  const charCountClass = charCount > CHAR_LIMIT ? 'error' : charCount > CHAR_LIMIT * 0.9 ? 'warning' : '';

  return `
    <div class="settings-body">
      <div class="settings-field">
        <label class="settings-label settings-label-with-icon">
          <span class="settings-label-icon">${MONITOR_ICON}</span>
          Appearance
        </label>
        <div class="settings-color-scheme">
          ${renderColorSchemeOption('light', SUN_ICON, 'Light', colorScheme === 'light')}
          ${renderColorSchemeOption('dark', MOON_ICON, 'Dark', colorScheme === 'dark')}
          ${renderColorSchemeOption('system', MONITOR_ICON, 'System', colorScheme === 'system')}
        </div>
      </div>

      <div class="settings-divider"></div>

      <div class="settings-field" data-section="todoist">
        <label class="settings-label settings-label-with-icon">
          <span class="settings-label-icon">${CHECKLIST_ICON}</span>
          Todoist Integration
        </label>
        ${renderTodoistSection(todoistSt)}
      </div>

      <div class="settings-divider"></div>

      <div class="settings-field" data-section="calendar">
        <label class="settings-label settings-label-with-icon">
          <span class="settings-label-icon">${CALENDAR_ICON}</span>
          Google Calendar Integration
        </label>
        ${renderCalendarSection(calendarSt)}
      </div>

      <div class="settings-divider"></div>

      <div class="settings-field" data-section="garmin">
        <label class="settings-label settings-label-with-icon">
          <span class="settings-label-icon">${ACTIVITY_ICON}</span>
          Garmin Connect
        </label>
        ${renderGarminSection(garminSt, garminMfa)}
      </div>

      ${whatsappAvailable ? `
      <div class="settings-divider"></div>

      <div class="settings-field">
        <label class="settings-label settings-label-with-icon" for="whatsapp-phone">
          <span class="settings-label-icon">${PHONE_ICON}</span>
          WhatsApp Notifications
        </label>
        <p class="settings-helper">Enter your phone number to receive notifications from autonomous agents via WhatsApp</p>
        <input
          type="tel"
          id="whatsapp-phone"
          class="settings-input"
          placeholder="+1234567890"
          maxlength="20"
          value="${escapeHtml(currentWhatsappPhone)}"
        />
        <p class="settings-helper settings-helper-muted">Format: E.164 (e.g., +420123456789)</p>
      </div>
      ` : ''}

      <div class="settings-divider"></div>

      <div class="settings-field">
        <label class="settings-label settings-label-with-icon" for="custom-instructions">
          <span class="settings-label-icon">${EDIT_ICON}</span>
          Custom Instructions
        </label>
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
  const phoneInput = document.getElementById('whatsapp-phone') as HTMLInputElement | null;
  if (!textarea) return;

  const instructions = textarea.value.trim();
  // Only get phone value if WhatsApp is available and input exists
  const whatsappPhone = whatsappAvailable && phoneInput ? phoneInput.value.trim() : currentWhatsappPhone;

  // Check if any values changed
  const instructionsChanged = instructions !== currentInstructions;
  const phoneChanged = whatsappAvailable && whatsappPhone !== currentWhatsappPhone;

  if (!instructionsChanged && !phoneChanged) {
    closeSettingsPopup();
    return;
  }

  log.debug('Saving settings', {
    instructionsLength: instructions.length,
    phoneChanged,
  });

  try {
    const updateData: { custom_instructions?: string; whatsapp_phone?: string } = {};

    if (instructionsChanged) {
      updateData.custom_instructions = instructions;
    }
    if (phoneChanged) {
      updateData.whatsapp_phone = whatsappPhone;
    }

    await settings.update(updateData);

    if (instructionsChanged) currentInstructions = instructions;
    if (phoneChanged) currentWhatsappPhone = whatsappPhone;

    closeSettingsPopup();
    toast.success('Settings saved');
    log.info('Settings saved', {
      instructionsLength: instructions.length,
      hasPhone: !!whatsappPhone,
    });
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

    // Clear calendar data
    availableCalendars = null;
    selectedCalendarIds = ['primary'];
    calendarsLoading = false;

    updateIntegrationSection('calendar');

    // Update store and re-render sidebar to hide planner entry
    const store = useStore.getState();
    const user = store.user;
    if (user) {
      store.setUser({ ...user, calendar_connected: false });
      renderConversationsList();
    }

    toast.success('Google Calendar disconnected');
    log.info('Google Calendar disconnected');
  } catch (error) {
    log.error('Failed to disconnect Google Calendar', { error });
    toast.error('Failed to disconnect Google Calendar');
  }
}

/**
 * Handle Garmin connect button click - submit email/password
 */
async function handleGarminConnect(): Promise<void> {
  const emailInput = document.querySelector<HTMLInputElement>('.settings-garmin-email');
  const passwordInput = document.querySelector<HTMLInputElement>('.settings-garmin-password');
  if (!emailInput || !passwordInput) return;

  const email = emailInput.value.trim();
  const password = passwordInput.value;

  if (!email || !password) {
    toast.error('Please enter both email and password');
    return;
  }

  try {
    log.debug('Connecting to Garmin');
    const result = await garmin.connect(email, password);

    // Clear password from DOM immediately
    passwordInput.value = '';

    if (result.mfa_required) {
      garminMfaRequired = true;
      updateGarminSection();
      return;
    }

    garminStatus = { connected: true, connected_at: new Date().toISOString(), needs_reconnect: false };
    garminMfaRequired = false;
    updateGarminSection();
    toast.success('Garmin connected successfully');
    log.info('Garmin connected');
  } catch (error) {
    log.error('Failed to connect Garmin', { error });
    passwordInput.value = '';
    toast.error('Failed to connect to Garmin. Check your credentials.');
  }
}

/**
 * Handle Garmin MFA code submission
 */
async function handleGarminMfaSubmit(): Promise<void> {
  const mfaInput = document.querySelector<HTMLInputElement>('.settings-garmin-mfa-input');
  if (!mfaInput) return;

  const mfaCode = mfaInput.value.trim();
  if (!mfaCode) {
    toast.error('Please enter the MFA code');
    return;
  }

  try {
    log.debug('Submitting Garmin MFA code');
    await garmin.submitMfa(mfaCode);

    garminStatus = { connected: true, connected_at: new Date().toISOString(), needs_reconnect: false };
    garminMfaRequired = false;
    updateGarminSection();
    toast.success('Garmin connected successfully');
    log.info('Garmin connected via MFA');
  } catch (error) {
    log.error('Failed to submit Garmin MFA', { error });
    toast.error('Invalid MFA code, please try again');
  }
}

/**
 * Handle Garmin disconnect button click
 */
async function handleGarminDisconnect(): Promise<void> {
  try {
    log.debug('Disconnecting Garmin');
    await garmin.disconnect();
    garminStatus = { connected: false, connected_at: null, needs_reconnect: false };
    garminMfaRequired = false;
    updateGarminSection();
    toast.success('Garmin disconnected');
    log.info('Garmin disconnected');
  } catch (error) {
    log.error('Failed to disconnect Garmin', { error });
    toast.error('Failed to disconnect Garmin');
  }
}

/**
 * Update Garmin section in the popup
 */
function updateGarminSection(): void {
  const popup = getElementById<HTMLDivElement>(POPUP_ID);
  if (!popup) return;

  const field = popup.querySelector('.settings-field[data-section="garmin"]');
  if (!field) return;

  field.innerHTML = `
    <label class="settings-label settings-label-with-icon">
      <span class="settings-label-icon">${ACTIVITY_ICON}</span>
      Garmin Connect
    </label>
    ${renderGarminSection(garminStatus, garminMfaRequired)}
  `;
}

/**
 * Handle checkbox change - update selected list and re-render
 */
function handleCalendarCheckboxChange(): void {
  const checkboxes = document.querySelectorAll<HTMLInputElement>('.settings-calendar-checkbox');
  selectedCalendarIds = Array.from(checkboxes)
    .filter(cb => cb.checked)
    .map(cb => cb.dataset.calendarId!);

  // Update helper text
  const helper = document.querySelector('.settings-calendar-selection .settings-helper');
  if (helper) {
    helper.textContent = selectedCalendarIds.length === 1
      ? '1 calendar selected'
      : `${selectedCalendarIds.length} calendars selected`;
  }

  // Update save button state
  const saveBtn = document.querySelector<HTMLButtonElement>('.settings-calendar-save-btn');
  if (saveBtn) {
    saveBtn.disabled = selectedCalendarIds.length === 0;
  }

  log.debug('Calendar selection changed', { count: selectedCalendarIds.length });
}

/**
 * Save calendar selection to backend
 */
async function handleCalendarSaveSelection(): Promise<void> {
  if (selectedCalendarIds.length === 0) {
    toast.error('Select at least one calendar');
    return;
  }

  const saveBtn = document.querySelector<HTMLButtonElement>('.settings-calendar-save-btn');
  if (!saveBtn) return;

  try {
    // Show loading state
    const originalText = saveBtn.textContent;
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    log.debug('Saving calendar selection', { count: selectedCalendarIds.length });

    // Normalize: replace primary calendar's actual ID with "primary"
    const primaryCalendar = availableCalendars?.find(cal => cal.primary);
    const normalizedIds = selectedCalendarIds.map(id =>
      (primaryCalendar && id === primaryCalendar.id) ? 'primary' : id
    );

    await calendar.updateSelectedCalendars(normalizedIds);

    const calendarText = selectedCalendarIds.length === 1 ? 'calendar' : 'calendars';
    toast.success(`Saved! Now showing events from ${selectedCalendarIds.length} ${calendarText}`);
    log.info('Calendar selection updated', { count: selectedCalendarIds.length });

    // Restore button
    saveBtn.textContent = originalText;
    saveBtn.disabled = false;

  } catch (error) {
    log.error('Failed to save calendar selection', { error });
    toast.error('Failed to save calendar selection');

    // Restore button
    if (saveBtn) {
      saveBtn.textContent = 'Save Selection';
      saveBtn.disabled = false;
    }
  }
}

function updateIntegrationSection(section: 'todoist' | 'calendar'): void {
  const popup = getElementById<HTMLDivElement>(POPUP_ID);
  if (!popup) return;

  const field = popup.querySelector(`.settings-field[data-section="${section}"]`);
  if (!field) return;

  const label = section === 'todoist' ? 'Todoist Integration' : 'Google Calendar Integration';
  const icon = section === 'todoist' ? CHECKLIST_ICON : CALENDAR_ICON;
  const content = section === 'todoist' ? renderTodoistSection(todoistStatus) : renderCalendarSection(calendarStatus);
  field.innerHTML = `
    <label class="settings-label settings-label-with-icon">
      <span class="settings-label-icon">${icon}</span>
      ${label}
    </label>
    ${content}
  `;

  // Note: Event handlers are attached via event delegation in initSettingsPopup()
  // No need to manually attach handlers here - they're already handled globally
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

    // Update store and re-render sidebar to show planner entry
    const store = useStore.getState();
    const user = store.user;
    if (user) {
      store.setUser({ ...user, todoist_connected: true });
      renderConversationsList();
    }

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

    // Update store and re-render sidebar to show planner entry
    const store = useStore.getState();
    const user = store.user;
    if (user) {
      store.setUser({ ...user, calendar_connected: true });
      renderConversationsList();
    }

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

    const [settingsData, todoistData, calendarData, garminData] = await Promise.all([
      settings.get(),
      todoist.getStatus().catch((err) => {
        log.warn('Failed to fetch Todoist status', { error: err });
        return null;
      }),
      calendar.getStatus().catch((err) => {
        log.warn('Failed to fetch Google Calendar status', { error: err });
        return null;
      }),
      garmin.getStatus().catch((err) => {
        log.warn('Failed to fetch Garmin status', { error: err });
        return null;
      }),
    ]);

    currentInstructions = settingsData.custom_instructions || '';
    currentWhatsappPhone = settingsData.whatsapp_phone || '';
    whatsappAvailable = settingsData.whatsapp_available ?? false;
    todoistStatus = todoistData;
    calendarStatus = calendarData;
    garminStatus = garminData;
    garminMfaRequired = false;
    log.info('Settings loaded', {
      instructionsLength: currentInstructions.length,
      hasWhatsappPhone: !!currentWhatsappPhone,
      whatsappAvailable,
      todoistConnected: todoistStatus?.connected ?? false,
      calendarConnected: calendarStatus?.connected ?? false,
      garminConnected: garminStatus?.connected ?? false,
    });

    // Update popup body
    const body = popup.querySelector('.info-popup-body');
    if (body) {
      body.outerHTML = `<div class="info-popup-body">${renderContent(currentInstructions, currentColorScheme, todoistStatus, calendarStatus, garminStatus, garminMfaRequired)}</div>`;
    }

    // If calendar is connected, fetch available calendars and selected calendars
    if (calendarData?.connected) {
      calendarsLoading = true;

      // Re-render to show loading state
      updateIntegrationSection('calendar');

      try {
        const [calendarsResp, selectedResp] = await Promise.all([
          calendar.listCalendars(),
          calendar.getSelectedCalendars(),
        ]);

        if (calendarsResp.error) {
          log.warn('Failed to fetch calendars', { error: calendarsResp.error });
          availableCalendars = [];
          calendarsError = calendarsResp.error;
        } else {
          availableCalendars = calendarsResp.calendars;
          calendarsError = null;
        }

        selectedCalendarIds = selectedResp.calendar_ids;

        log.debug('Calendars loaded', {
          available: availableCalendars?.length ?? 0,
          selected: selectedCalendarIds.length
        });
      } catch (err) {
        log.error('Failed to fetch calendars', { error: err });
        availableCalendars = [];
        // Don't overwrite selectedCalendarIds - preserve user's existing selection
        // They won't be able to change it until the error is resolved, but we won't lose their data
        calendarsError = 'Failed to load calendars. Please try again.';
      } finally {
        calendarsLoading = false;
        // Re-render with loaded data
        updateIntegrationSection('calendar');
      }
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

    // Note: Todoist and Calendar button handlers are attached via event delegation in initSettingsPopup()
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

    if (target.classList.contains('settings-calendar-save-btn')) {
      handleCalendarSaveSelection();
    }

    // Garmin connect button
    if (target.classList.contains('settings-garmin-connect')) {
      handleGarminConnect();
    }

    // Garmin show login form (reconnect)
    if (target.classList.contains('settings-garmin-show-login')) {
      garminStatus = { connected: false, connected_at: null, needs_reconnect: false };
      garminMfaRequired = false;
      updateGarminSection();
    }

    // Garmin disconnect button
    if (target.classList.contains('settings-garmin-disconnect')) {
      handleGarminDisconnect();
    }

    // Garmin MFA submit
    if (target.classList.contains('settings-garmin-mfa-submit')) {
      handleGarminMfaSubmit();
    }

    // Garmin MFA cancel
    if (target.classList.contains('settings-garmin-mfa-cancel')) {
      garminMfaRequired = false;
      garminStatus = { connected: false, connected_at: null, needs_reconnect: false };
      updateGarminSection();
    }
  });

  // Event delegation for checkbox changes
  popup.addEventListener('change', (e) => {
    const target = e.target as HTMLElement;
    if (target.classList.contains('settings-calendar-checkbox')) {
      handleCalendarCheckboxChange();
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
