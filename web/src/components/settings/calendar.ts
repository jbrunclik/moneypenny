import { createElement } from '../../utils/dom';
import { CHECK_ICON, WARNING_ICON, CALENDAR_ICON, STAR_ICON, createIconElement } from '../../utils/icons';
import { calendar } from '../../api/integrations';
import { ApiError } from '../../api/http';
import { toast } from '../Toast';
import type { Calendar, CalendarStatus } from '../../types/api';
import { useStore } from '../../state/store';
import { renderConversationsList } from '../Sidebar';
import { checkbox, helper, log, rerenderField, settingsField, statusLine, textButton } from './shared';

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
 * The calendar selection: a checkbox per calendar
 */
function calendarSelection(
  calendars: Calendar[],
  selected: string[],
  loading: boolean,
  error: string | null = null
): HTMLElement[] {
  if (loading) {
    return [
      createElement('div', { class: 'settings-calendar-loading' }, [
        createElement('div', { class: 'spinner-small' }),
        createElement('span', {}, ['Loading calendars...']),
      ]),
    ];
  }

  // Show error message if present (from backend)
  if (error) {
    const reconnect = error.toLowerCase().includes('expired') || error.toLowerCase().includes('reconnect');
    return [
      createElement('div', { class: 'settings-calendar-error' }, [
        createIconElement('settings-calendar-icon warning', WARNING_ICON),
        createElement('div', {}, [
          createElement('p', { class: 'settings-error-message' }, [error]),
          helper(
            reconnect
              ? 'Please disconnect and reconnect your Google Calendar in the section above.'
              : 'Please try refreshing the page or check your connection.'
          ),
        ]),
      ]),
    ];
  }

  if (calendars.length === 0) {
    return [
      createElement('div', { class: 'settings-empty-state' }, [
        createElement('p', {}, ['No calendars available. Create one in Google Calendar first.']),
      ]),
    ];
  }

  return [
    createElement('div', { class: 'settings-calendar-list' }, calendars.map((cal) => calendarItem(cal, selected))),
    helper(selected.length === 1 ? '1 calendar selected' : `${selected.length} calendars selected`),
  ];
}

// A plain CSS colour from the server: #rgb, #rrggbb(aa) or rgb()/rgba() of numbers
const CSS_COLOR_PATTERN = /^(#[0-9a-f]{3,4}|#[0-9a-f]{6}|#[0-9a-f]{8}|rgba?\(\s*\d{1,3}(\s*,\s*\d{1,3}){2}(\s*,\s*(0|1|0?\.\d+))?\s*\))$/i;

/** The calendar's colour dot; none when the server's value is not a plain colour. */
function colorDot(color: string | null | undefined): HTMLElement | null {
  if (!color || !CSS_COLOR_PATTERN.test(color)) return null;
  const dot = createElement('span', { class: 'calendar-color-dot' });
  dot.style.backgroundColor = color;
  return dot;
}

function calendarItem(cal: Calendar, selected: string[]): HTMLElement {
  const isPrimary = cal.primary || cal.id === 'primary';
  const isChecked = isPrimary || selected.includes(cal.id); // Primary always checked
  const isDisabled = isPrimary; // Primary calendar cannot be unchecked

  return createElement(
    'label',
    { class: `settings-calendar-item${isDisabled ? ' disabled' : ''}`, 'data-calendar-id': cal.id },
    [
      checkbox(
        { class: 'settings-calendar-checkbox', 'data-calendar-id': cal.id, ...(isDisabled ? { disabled: '' } : {}) },
        isChecked
      ),
      createElement('div', { class: 'settings-calendar-info' }, [
        colorDot(cal.background_color),
        isPrimary && createIconElement('calendar-star-icon', STAR_ICON),
        createElement('span', { class: 'settings-calendar-name' }, [cal.summary]),
        cal.access_role !== 'owner' && !isPrimary && createElement('span', { class: 'settings-calendar-badge' }, [cal.access_role]),
      ]),
    ]
  );
}

function calendarBody(status: CalendarStatus | null): HTMLElement[] {
  if (status === null) {
    return [createElement('div', { class: 'settings-calendar-loading' }, ['Loading Google Calendar status...'])];
  }

  if (status.connected && status.needs_reconnect) {
    return [
      createElement('div', { class: 'settings-calendar-needs-reconnect' }, [
        statusLine('calendar', 'warning', WARNING_ICON, 'Google Calendar access expired'),
        helper('Your Google Calendar connection has expired. Please reconnect to keep scheduling events.'),
        createElement('div', { class: 'settings-calendar-actions' }, [
          textButton('btn btn-primary btn-sm settings-calendar-connect', 'Reconnect'),
          textButton('btn btn-secondary btn-sm settings-calendar-disconnect', 'Disconnect'),
        ]),
      ]),
    ];
  }

  if (status.connected) {
    const save = textButton('btn btn-primary settings-calendar-save-btn', 'Save Selection');
    save.disabled = selectedCalendarIds.length === 0 || calendarsLoading;
    return [
      createElement('div', { class: 'settings-calendar-connected-wrapper' }, [
        createElement('div', { class: 'settings-calendar-connected' }, [
          statusLine('calendar', 'connected', CHECK_ICON, `Connected${status.calendar_email ? ` as ${status.calendar_email}` : ''}`),
          textButton('btn btn-secondary btn-sm settings-calendar-disconnect', 'Disconnect'),
        ]),
        createElement('div', { class: 'settings-calendar-selection' }, [
          createElement('label', { class: 'settings-label' }, ['Show events from:']),
          ...calendarSelection(availableCalendars || [], selectedCalendarIds, calendarsLoading, calendarsError),
          save,
        ]),
      ]),
    ];
  }

  return [
    createElement('div', { class: 'settings-calendar-disconnected' }, [
      helper('Connect Google Calendar to schedule events and focus blocks with AI'),
      textButton('btn btn-primary btn-sm settings-calendar-connect', 'Connect Google Calendar'),
    ]),
  ];
}

/** The whole Google Calendar field (label + status body). */
export function renderCalendarField(): HTMLElement {
  return settingsField('calendar', CALENDAR_ICON, LABEL, calendarBody(calendarStatus));
}

function updateCalendarSection(): void {
  rerenderField('calendar', CALENDAR_ICON, LABEL, calendarBody(calendarStatus));
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

    availableCalendars = calendarsResp.calendars;
    calendarsError = null;
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
    // The server's message says what to do ("... Please reconnect.")
    calendarsError = err instanceof ApiError ? err.message : 'Failed to load calendars. Please try again.';
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
    .flatMap(cb => cb.dataset.calendarId ?? []);

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
