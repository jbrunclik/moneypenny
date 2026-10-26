import { createElement } from '../../utils/dom';
import { MAP_PIN_ICON } from '../../utils/icons';
import {
  isLocationSharingEnabled,
  requestLocationFix,
  setLocationSharingEnabled,
} from '../../utils/location';
import { toast } from '../Toast';
import { renderCalendarField } from './calendar';
import { renderGarminField } from './garmin';
import { renderRouvyField } from './rouvy';
import { renderTodoistField } from './todoist';
import { fieldLabel, helper, toggle } from './shared';

function locationField(): HTMLElement {
  return createElement('div', { class: 'settings-field', 'data-section': 'location' }, [
    fieldLabel(MAP_PIN_ICON, 'Location'),
    helper('Used for "near me" suggestions and routes. Sent only with your messages, never stored. Applies to this device only.'),
    toggle('location-sharing-enabled', isLocationSharingEnabled(), 'Share device location with the assistant'),
  ]);
}

/**
 * The "Integrations" tab section: Todoist, Google Calendar, Garmin, Rouvy
 * and device location sharing, with a divider between them.
 */
export function renderIntegrationsSection(): HTMLElement {
  const fields = [renderTodoistField(), renderCalendarField(), renderGarminField(), renderRouvyField(), locationField()];
  return createElement('div', { class: 'settings-section', 'data-settings-section': 'integrations' }, [
    createElement('div', { class: 'settings-section-title' }, ['Integrations']),
    ...fields.flatMap((field, i) => (i === 0 ? [field] : [createElement('div', { class: 'settings-divider' }), field])),
  ]);
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
    const messages: Record<typeof result.reason, string> = {
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
