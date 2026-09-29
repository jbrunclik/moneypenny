import { escapeHtml } from '../../utils/dom';
import { BELL_ICON, SUNRISE_ICON, PHONE_ICON } from '../../utils/icons';
import { settings } from '../../api/client';
import {
  type PushState,
  enablePush,
  disablePush,
  sendTestNotification,
} from '../../core/push';
import { toast } from '../Toast';
import type { DailyBriefingSettings, UserSettings } from '../../types/api';
import { log, showSavedIndicator } from './shared';

/** Current push notification state on this device */
let pushState: PushState = 'unsupported';

/** Current Daily Briefing settings */
let briefingSettings: DailyBriefingSettings = {
  enabled: false,
  time: '08:00',
  timezone: 'UTC',
};

/** Current WhatsApp phone number */
let currentWhatsappPhone = '';

/** Whether WhatsApp is available at the app level */
let whatsappAvailable = false;

/** Adopt server settings and this device's push state after a settings fetch. */
export function loadNotificationSettings(data: UserSettings, push: PushState): void {
  currentWhatsappPhone = data.whatsapp_phone || '';
  whatsappAvailable = data.whatsapp_available ?? false;
  briefingSettings = data.daily_briefing ?? briefingSettings;
  pushState = push;
}

/**
 * Render the Notifications (Web Push) section for the current state.
 */
function renderPushBody(state: PushState): string {
  switch (state) {
    case 'subscribed':
      return `
        <p class="settings-helper">Notifications are enabled on this device.</p>
        <div class="settings-push-actions">
          <button class="btn btn-secondary push-toggle-btn" data-action="disable">Disable</button>
          <button class="btn btn-secondary push-test-btn">Send test</button>
        </div>
      `;
    case 'not-subscribed':
      return `
        <p class="settings-helper">Get notified when agents finish work or wait for your approval.</p>
        <div class="settings-push-actions">
          <button class="btn btn-primary push-toggle-btn" data-action="enable">Enable notifications</button>
        </div>
      `;
    case 'denied':
      return `<p class="settings-helper">Notifications are blocked for this site. Allow them in your browser settings, then try again.</p>`;
    case 'ios-needs-install':
      return `<p class="settings-helper">On iPhone/iPad, add this app to your Home Screen (Share &rarr; Add to Home Screen) to enable notifications.</p>`;
    case 'server-disabled':
      return `<p class="settings-helper settings-helper-muted">Not configured on the server (VAPID keys missing).</p>`;
    case 'unsupported':
      return `<p class="settings-helper settings-helper-muted">Not supported in this browser.</p>`;
  }
}

function renderWhatsappField(): string {
  if (!whatsappAvailable) return '';
  return `
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
        <span class="settings-saved-indicator" data-saved-for="whatsapp-phone">Saved</span>
      </div>
      `;
}

/**
 * Render the "Notifications" tab section: push, Daily Briefing, WhatsApp.
 */
export function renderNotificationsSection(): string {
  return `
      <div class="settings-section" data-settings-section="notifications">
      <div class="settings-section-title">Notifications</div>
      <div class="settings-field" data-section="push">
        <label class="settings-label settings-label-with-icon">
          <span class="settings-label-icon">${BELL_ICON}</span>
          Notifications
        </label>
        <div class="settings-push-body">${renderPushBody(pushState)}</div>
      </div>

      <div class="settings-divider"></div>

      <div class="settings-field" data-section="briefing">
        <label class="settings-label settings-label-with-icon">
          <span class="settings-label-icon">${SUNRISE_ICON}</span>
          Daily Briefing
        </label>
        <p class="settings-helper">A morning summary of your schedule, tasks and readiness, delivered as a notification. Runs as an agent you can also find in the Command Center.</p>
        <div class="settings-briefing-controls">
          <label class="toggle-label">
            <input type="checkbox" id="briefing-enabled" ${briefingSettings.enabled ? 'checked' : ''}>
            <span class="toggle-switch"></span>
            <span class="toggle-text">Enabled</span>
          </label>
          <label class="settings-briefing-time-label" for="briefing-time">
            Deliver at
            <input type="time" id="briefing-time" class="settings-input settings-briefing-time" value="${escapeHtml(briefingSettings.time)}">
          </label>
        </div>
      </div>

      ${renderWhatsappField()}
      </div>
  `;
}

/**
 * Re-render only the push section (after enable/disable).
 */
function updatePushSection(): void {
  const section = document.querySelector('[data-section="push"] .settings-push-body');
  if (section) {
    section.innerHTML = renderPushBody(pushState);
  }
}

/**
 * Enable/disable push for this device (runs in the click's user
 * gesture, which the permission prompt requires).
 */
async function handlePushToggle(btn: HTMLButtonElement): Promise<void> {
  const enable = btn.dataset.action === 'enable';
  btn.disabled = true;
  try {
    pushState = enable ? await enablePush() : await disablePush();
    if (enable && pushState === 'subscribed') {
      toast.success('Notifications enabled');
    } else if (!enable && pushState === 'not-subscribed') {
      toast.success('Notifications disabled');
    } else if (pushState === 'denied') {
      toast.warning('Notifications are blocked in your browser settings.');
    }
  } catch (error) {
    log.error('Push toggle failed', { error, enable });
    toast.error(enable ? 'Failed to enable notifications.' : 'Failed to disable notifications.');
  } finally {
    updatePushSection();
  }
}

/**
 * Send a test notification and surface the outcome.
 */
async function handlePushTest(btn: HTMLButtonElement): Promise<void> {
  btn.disabled = true;
  try {
    const status = await sendTestNotification();
    if (status === 'no_subscriptions') {
      toast.warning('No subscribed devices found.');
    } else {
      toast.success('Test notification sent');
    }
  } catch (error) {
    log.error('Push test failed', { error });
    toast.error('Failed to send test notification.');
  } finally {
    btn.disabled = false;
  }
}

/**
 * Apply a Daily Briefing toggle/time change immediately.
 * Timezone comes from the browser so "08:00" means local morning.
 */
async function handleBriefingChange(): Promise<void> {
  const enabledEl = document.getElementById('briefing-enabled') as HTMLInputElement | null;
  const timeEl = document.getElementById('briefing-time') as HTMLInputElement | null;
  if (!enabledEl || !timeEl) return;

  const update: DailyBriefingSettings = {
    enabled: enabledEl.checked,
    time: timeEl.value || '08:00',
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  };

  try {
    await settings.update({ daily_briefing: update });
    briefingSettings = update;
    toast.success(
      update.enabled ? `Daily briefing scheduled for ${update.time}` : 'Daily briefing disabled'
    );
  } catch (error) {
    log.error('Failed to update daily briefing', { error });
    toast.error('Failed to update daily briefing.');
    // Restore the controls to the last known good state
    enabledEl.checked = briefingSettings.enabled;
    timeEl.value = briefingSettings.time;
  }
}

/**
 * Save the WhatsApp phone field (called on blur when changed).
 */
async function saveWhatsappPhone(): Promise<void> {
  const phoneInput = document.getElementById('whatsapp-phone') as HTMLInputElement | null;
  if (!phoneInput || !whatsappAvailable) return;
  const whatsappPhone = phoneInput.value.trim();
  if (whatsappPhone === currentWhatsappPhone) return;

  try {
    await settings.update({ whatsapp_phone: whatsappPhone });
    currentWhatsappPhone = whatsappPhone;
    showSavedIndicator('whatsapp-phone');
    log.info('WhatsApp phone saved', { hasPhone: !!whatsappPhone });
  } catch (error) {
    log.error('Failed to save WhatsApp phone', { error });
    toast.error('Failed to save WhatsApp number');
  }
}

/** Attach the WhatsApp field's save-on-blur after the body renders. */
export function bindWhatsappField(): void {
  const phoneInput = document.getElementById('whatsapp-phone') as HTMLInputElement | null;
  phoneInput?.addEventListener('blur', () => void saveWhatsappPhone());
}

/** Delegated click handling for the push buttons. */
export function handleNotificationsClick(target: HTMLElement): void {
  if (target.classList.contains('push-toggle-btn')) {
    void handlePushToggle(target as HTMLButtonElement);
  }
  if (target.classList.contains('push-test-btn')) {
    void handlePushTest(target as HTMLButtonElement);
  }
}

/** Delegated `change` handling for the Daily Briefing controls. */
export function handleNotificationsChange(target: HTMLElement): void {
  if (target.id === 'briefing-enabled' || target.id === 'briefing-time') {
    void handleBriefingChange();
  }
}
