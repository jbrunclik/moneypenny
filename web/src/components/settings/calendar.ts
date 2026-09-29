import { escapeHtml } from '../../utils/dom';
import { CHECK_ICON, WARNING_ICON, CALENDAR_ICON, STAR_ICON } from '../../utils/icons';
import { calendar } from '../../api/client';
import { toast } from '../Toast';
import type { Calendar, CalendarStatus } from '../../types/api';
import { useStore } from '../../state/store';
import { renderConversationsList } from '../Sidebar';
import { log, renderFieldLabel, rerenderField } from './shared';

export const CALENDAR_STATE_KEY = 'calendar-oauth-state';

const LABEL = 'Google Calendar Integration';

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

export function setCalendarStatus(status: CalendarStatus | null): void {
  calendarStatus = status;
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
      ${calendars.map((cal) => renderCalendarItem(cal, selected)).join('')}
    </div>
    <p class="settings-helper">
      ${selected.length === 1 ? '1 calendar selected' : `${selected.length} calendars selected`}
    </p>
  `;
}

function renderCalendarItem(cal: Calendar, selected: string[]): string {
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
}

function renderCalendarBody(status: CalendarStatus | null): string {
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

/** Render the whole Google Calendar field (label + status body). */
export function renderCalendarField(): string {
  return `
      <div class="settings-field" data-section="calendar">
        ${renderFieldLabel(CALENDAR_ICON, LABEL)}
        ${renderCalendarBody(calendarStatus)}
      </div>
  `;
}

function updateCalendarSection(): void {
  rerenderField('calendar', CALENDAR_ICON, LABEL, renderCalendarBody(calendarStatus));
}

/**
 * Fetch the user's calendars and current selection into the connected
 * section (shows a loading state while in flight).
 */
export async function loadCalendarSelection(): Promise<void> {
  calendarsLoading = true;

  // Re-render to show loading state
  updateCalendarSection();

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
    updateCalendarSection();
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

    updateCalendarSection();

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
    saveBtn.textContent = 'Save Selection';
    saveBtn.disabled = false;
  }
}

/** Delegated click handling for the Google Calendar field's buttons. */
export function handleCalendarClick(target: HTMLElement): void {
  if (target.classList.contains('settings-calendar-connect')) {
    void handleCalendarConnect();
  }
  if (target.classList.contains('settings-calendar-disconnect')) {
    void handleCalendarDisconnect();
  }
  if (target.classList.contains('settings-calendar-save-btn')) {
    void handleCalendarSaveSelection();
  }
}

/** Delegated `change` handling for the calendar selection checkboxes. */
export function handleCalendarChange(target: HTMLElement): void {
  if (target.classList.contains('settings-calendar-checkbox')) {
    handleCalendarCheckboxChange();
  }
}
