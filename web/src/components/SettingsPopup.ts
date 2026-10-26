/**
 * Settings popup shell: open/close, loading, tab switching and the
 * delegated event wiring. Each tab's markup, state and handlers live in
 * ./settings/<section>.ts.
 */
import { createElement, getElementById } from '../utils/dom';
import { SETTINGS_ICON, CLOSE_ICON, createIconElement, setIcon } from '../utils/icons';
import { todoist, calendar, garmin, rouvy } from '../api/integrations';
import { settings } from '../api/settings';
import {
  getStoredColorScheme,
  applyColorScheme,
  setupSystemPreferenceListener,
} from '../utils/theme';
import { registerPopupEscapeHandler } from '../utils/popupEscapeHandler';
import { attachSheetDismiss } from '../utils/sheet-gesture';
import { log, POPUP_ID } from './settings/shared';
import { bindColorSchemeOptions, handleAppearanceChange, renderAppearanceSection } from './settings/appearance';
import { handleIntegrationsChange, renderIntegrationsSection } from './settings/integrations';
import { handleTodoistClick } from './settings/todoist';
import { handleCalendarChange, handleCalendarClick, loadCalendarSelection } from './settings/calendar';
import { handleGarminClick, resetGarminState } from './settings/garmin';
import { handleRouvyClick } from './settings/rouvy';
import {
  bindWhatsappField,
  fetchPushState,
  handleNotificationsChange,
  handleNotificationsClick,
  renderNotificationsSection,
} from './settings/notifications';
import type { PushState } from '../types/api';
import { bindInstructionsField, renderInstructionsSection } from './settings/instructions';
import { useStore } from '../state/store';

function settingsBody(): HTMLElement {
  const tab = (key: string, label: string, active = false): HTMLButtonElement =>
    createElement('button', { class: `settings-tab${active ? ' active' : ''}`, role: 'tab', 'data-settings-tab': key }, [label]);
  return createElement('div', { class: 'settings-body' }, [
    createElement('div', { class: 'settings-tabs', role: 'tablist' }, [
      tab('appearance', 'Appearance', true),
      tab('integrations', 'Integrations'),
      tab('notifications', 'Notifications'),
      tab('instructions', 'AI Instructions'),
    ]),
    renderAppearanceSection(),
    renderIntegrationsSection(),
    renderNotificationsSection(),
    renderInstructionsSection(),
  ]);
}

/**
 * Switch the active settings tab (desktop; mobile shows all sections).
 */
function switchSettingsTab(tabKey: string): void {
  document.querySelectorAll<HTMLElement>('.settings-tab').forEach((tab) => {
    tab.classList.toggle('active', tab.dataset.settingsTab === tabKey);
  });
  document.querySelectorAll<HTMLElement>('.settings-section').forEach((section) => {
    section.classList.toggle('active', section.dataset.settingsSection === tabKey);
  });
}

function renderLoadingShell(popup: HTMLElement): void {
  const content = popup.querySelector('.info-popup-content');
  if (!content) return;
  const closeBtn = createElement('button', { class: 'info-popup-close dialog-close', 'aria-label': 'Close' });
  setIcon(closeBtn, CLOSE_ICON);
  content.replaceChildren(
    createElement('div', { class: 'info-popup-header' }, [
      createIconElement('info-popup-icon', SETTINGS_ICON),
      createElement('h3', { class: 'dialog-title' }, ['Settings']),
      closeBtn,
    ]),
    createElement('div', { class: 'info-popup-body settings-body' }, [
      createElement('div', { class: 'settings-loading' }, ['Loading settings...']),
    ])
  );

  // Attach close handler
  content.querySelector('.info-popup-close')?.addEventListener('click', closeSettingsPopup);
}

/** Warn and fall back to null when an integration status fetch fails. */
function statusOrNull<T>(promise: Promise<T>, what: string): Promise<T | null> {
  return promise.catch((err) => {
    log.warn(`Failed to fetch ${what} status`, { error: err });
    return null;
  });
}

/**
 * Fetch settings, every integration status and the push state in
 * parallel, and hand each to the section module that owns it.
 */
async function loadAllSettings(): Promise<{ calendarConnected: boolean }> {
  log.debug('Fetching settings and Todoist status');

  const [settingsData, todoistData, calendarData, garminData, rouvyData, pushStateData] = await Promise.all([
    settings.get(),
    statusOrNull(todoist.getStatus(), 'Todoist'),
    statusOrNull(calendar.getStatus(), 'Google Calendar'),
    statusOrNull(garmin.getStatus(), 'Garmin'),
    statusOrNull(rouvy.getStatus(), 'Rouvy'),
    fetchPushState().catch((err): PushState => {
      log.warn('Failed to determine push state', { error: err });
      return 'unsupported';
    }),
  ]);

  const store = useStore.getState();
  store.setUserSettings(settingsData);
  store.setPushState(pushStateData);
  store.setIntegrationStatus('todoist', todoistData);
  store.setIntegrationStatus('calendar', calendarData);
  resetGarminState(garminData);
  store.setIntegrationStatus('rouvy', rouvyData);
  log.info('Settings loaded', {
    instructionsLength: settingsData.custom_instructions.length,
    hasWhatsappPhone: !!settingsData.whatsapp_phone,
    whatsappAvailable: settingsData.whatsapp_available ?? false,
    todoistConnected: todoistData?.connected ?? false,
    calendarConnected: calendarData?.connected ?? false,
    garminConnected: garminData?.connected ?? false,
  });
  return { calendarConnected: calendarData?.connected ?? false };
}

/** Attach the per-element handlers of the freshly rendered body. */
function bindRenderedBody(popup: HTMLElement): void {
  // Tab switching (desktop; mobile shows all sections stacked)
  popup.querySelectorAll<HTMLElement>('.settings-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      if (tab.dataset.settingsTab) switchSettingsTab(tab.dataset.settingsTab);
    });
  });

  // Text fields save on blur with an inline "Saved" indicator
  bindInstructionsField();
  bindWhatsappField();
  bindColorSchemeOptions(popup);

  // Note: integration button handlers are attached via event delegation in initSettingsPopup()
}

/**
 * Open the settings popup
 */
export async function openSettingsPopup(): Promise<void> {
  ensureSettingsPopupInit(); // idempotent - module is lazy-loaded on first open

  const popup = getElementById<HTMLDivElement>(POPUP_ID);
  if (!popup) return;

  // Show popup with loading state
  renderLoadingShell(popup);
  popup.classList.remove('hidden');

  try {
    const { calendarConnected } = await loadAllSettings();

    // Update popup body
    const body = popup.querySelector('.info-popup-body');
    if (body) {
      body.replaceWith(createElement('div', { class: 'info-popup-body' }, [settingsBody()]));
    }

    // If calendar is connected, fetch available calendars and selected calendars
    if (calendarConnected) {
      await loadCalendarSelection();
    }

    bindRenderedBody(popup);
  } catch (error) {
    log.error('Failed to load settings', { error });
    const body = popup.querySelector('.info-popup-body');
    if (body) {
      body.replaceChildren(
        createElement('div', { class: 'settings-error' }, [
          createElement('p', {}, ['Failed to load settings.']),
          createElement('button', { class: 'btn btn-secondary settings-retry-btn' }, ['Retry']),
        ])
      );
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
// UI-local (F2): the popup wires its handlers once
let _settingsInitDone = false;

function ensureSettingsPopupInit(): void {
  if (_settingsInitDone) return;
  _settingsInitDone = true;
  initSettingsPopup();
}

function initSettingsPopup(): void {
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

  // Mobile bottom sheet: drag the handle/header down to dismiss
  const content = popup.querySelector<HTMLElement>('.info-popup-content');
  if (content) attachSheetDismiss(content, closeSettingsPopup);

  // Toggles, selects and checkboxes apply immediately on change
  popup.addEventListener('change', (e) => {
    const target = e.target as HTMLElement;
    handleNotificationsChange(target);
    handleAppearanceChange(target);
    handleIntegrationsChange(target);
    handleCalendarChange(target);
  });

  // Event delegation for buttons
  popup.addEventListener('click', (e) => {
    const target = e.target as HTMLElement;

    // Retry button
    if (target.classList.contains('settings-retry-btn')) {
      void openSettingsPopup();
    }

    handleTodoistClick(target);
    handleCalendarClick(target);
    handleNotificationsClick(target);
    handleGarminClick(target);
    handleRouvyClick(target);
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
