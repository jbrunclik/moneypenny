import { MAP_PIN_ICON } from '../../utils/icons';
import {
  isLocationSharingEnabled,
  requestLocationFix,
  setLocationSharingEnabled,
} from '../../core/location';
import { toast } from '../Toast';
import { renderCalendarField } from './calendar';
import { renderGarminField } from './garmin';
import { renderRouvyField } from './rouvy';
import { renderTodoistField } from './todoist';

function renderLocationField(): string {
  return `
      <div class="settings-field" data-section="location">
        <label class="settings-label settings-label-with-icon">
          <span class="settings-label-icon">${MAP_PIN_ICON}</span>
          Location
        </label>
        <p class="settings-helper">Used for "near me" suggestions and routes. Sent only with your messages, never stored. Applies to this device only.</p>
        <label class="toggle-label">
          <input type="checkbox" id="location-sharing-enabled" ${isLocationSharingEnabled() ? 'checked' : ''}>
          <span class="toggle-switch"></span>
          <span class="toggle-text">Share device location with the assistant</span>
        </label>
      </div>
  `;
}

/**
 * Render the "Integrations" tab section: Todoist, Google Calendar,
 * Garmin, Rouvy and device location sharing.
 */
export function renderIntegrationsSection(): string {
  const divider = '<div class="settings-divider"></div>';
  return `
      <div class="settings-section" data-settings-section="integrations">
      <div class="settings-section-title">Integrations</div>
      ${[
        renderTodoistField(),
        renderCalendarField(),
        renderGarminField(),
        renderRouvyField(),
        renderLocationField(),
      ].join(divider)}
      </div>
  `;
}

/**
 * Apply the location-sharing toggle immediately (per-device, localStorage).
 * Enabling requests a fix right away so the browser permission prompt (and
 * any denial) is visible now, not at message-send time.
 */
function handleLocationSharingChange(checkbox: HTMLInputElement): void {
  const enabled = checkbox.checked;
  setLocationSharingEnabled(enabled);
  if (!enabled) {
    toast.success('Location sharing disabled');
    return;
  }
  void requestLocationFix().then((result) => {
    if (result.ok) {
      toast.success('Location sharing enabled');
      return;
    }
    const messages: Record<string, string> = {
      unsupported: 'This browser does not support location.',
      denied:
        'Location permission denied - allow location for this site in your browser settings, then try again.',
      unavailable:
        "Your browser couldn't determine a location. Check that location services are enabled for it in system settings.",
      timeout: 'Timed out waiting for a location fix - try again.',
    };
    toast.error(messages[result.reason]);
    setLocationSharingEnabled(false);
    checkbox.checked = false;
  });
}

/** Delegated `change` handling for the integrations section's own controls. */
export function handleIntegrationsChange(target: HTMLElement): void {
  if (target.id === 'location-sharing-enabled') {
    handleLocationSharingChange(target as HTMLInputElement);
  }
}
