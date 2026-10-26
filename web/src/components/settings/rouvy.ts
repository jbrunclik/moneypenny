import { CHECK_ICON, WARNING_ICON, ACTIVITY_ICON } from '../../utils/icons';
import { rouvy, type RouvyStatus } from '../../api/integrations';
import { toast } from '../Toast';
import { createElement } from '../../utils/dom';
import { helper, log, rerenderField, settingsField, statusLine, textButton } from './shared';

const LABEL = 'Rouvy';

/** Current Rouvy connection status */
let rouvyStatus: RouvyStatus | null = null;

export function setRouvyStatus(status: RouvyStatus | null): void {
  rouvyStatus = status;
}

/**
 * The Rouvy section (no MFA — Rouvy's login flow has none)
 */
function rouvyBody(status: RouvyStatus | null): HTMLElement[] {
  if (status === null) {
    return [createElement('div', { class: 'settings-rouvy-loading' }, ['Loading Rouvy status...'])];
  }

  if (status.connected && status.needs_reconnect) {
    return [
      createElement('div', { class: 'settings-rouvy-needs-reconnect' }, [
        statusLine('rouvy', 'warning', WARNING_ICON, 'Rouvy session expired'),
        helper('Your Rouvy session has expired. Please reconnect with your credentials.'),
        createElement('div', { class: 'settings-rouvy-actions' }, [
          textButton('btn btn-primary btn-sm settings-rouvy-show-login', 'Reconnect'),
          textButton('btn btn-secondary btn-sm settings-rouvy-disconnect', 'Disconnect'),
        ]),
      ]),
    ];
  }

  if (status.connected) {
    return [
      createElement('div', { class: 'settings-rouvy-connected' }, [
        statusLine('rouvy', 'connected', CHECK_ICON, 'Connected'),
        textButton('btn btn-secondary btn-sm settings-rouvy-disconnect', 'Disconnect'),
      ]),
    ];
  }

  return [
    createElement('div', { class: 'settings-rouvy-disconnected' }, [
      helper('Connect your Rouvy account so the coach can upload workouts directly.'),
      createElement('div', { class: 'settings-rouvy-login-form' }, [
        createElement('input', { type: 'email', class: 'settings-input settings-rouvy-email', placeholder: 'Rouvy email', autocomplete: 'email' }),
        createElement('input', {
          type: 'password',
          class: 'settings-input settings-rouvy-password',
          placeholder: 'Rouvy password',
          autocomplete: 'current-password',
        }),
        helper('Your password is stored encrypted so the session can be refreshed automatically.', true),
        textButton('btn btn-primary settings-rouvy-connect', 'Connect Rouvy'),
      ]),
    ]),
  ];
}

/** The whole Rouvy field (label + status body). */
export function renderRouvyField(): HTMLElement {
  return settingsField('rouvy', ACTIVITY_ICON, LABEL, rouvyBody(rouvyStatus));
}

/**
 * Update Rouvy section in the popup
 */
function updateRouvySection(): void {
  rerenderField('rouvy', ACTIVITY_ICON, LABEL, rouvyBody(rouvyStatus));
}

/**
 * Handle Rouvy connect button click - headless login on the backend.
 */
async function handleRouvyConnect(): Promise<void> {
  const emailInput = document.querySelector<HTMLInputElement>('.settings-rouvy-email');
  const passwordInput = document.querySelector<HTMLInputElement>('.settings-rouvy-password');
  const email = emailInput?.value.trim() ?? '';
  const password = passwordInput?.value ?? '';
  if (!email || !password) {
    toast.error('Enter your Rouvy email and password');
    return;
  }

  const submitBtn = document.querySelector<HTMLButtonElement>('.settings-rouvy-connect');
  if (submitBtn) submitBtn.disabled = true;

  try {
    log.debug('Connecting to Rouvy');
    await rouvy.connect(email, password);
    rouvyStatus = { connected: true, connected_at: new Date().toISOString(), needs_reconnect: false };
    updateRouvySection();
    toast.success('Rouvy connected');
    log.info('Rouvy connected');
  } catch (error) {
    log.error('Failed to connect Rouvy', { error });
    toast.error(error instanceof Error ? error.message : 'Failed to connect Rouvy');
    if (submitBtn) submitBtn.disabled = false;
  }
}

/**
 * Handle Rouvy disconnect button click.
 */
async function handleRouvyDisconnect(): Promise<void> {
  try {
    log.debug('Disconnecting Rouvy');
    await rouvy.disconnect();
    rouvyStatus = { connected: false, connected_at: null, needs_reconnect: false };
    updateRouvySection();
    toast.success('Rouvy disconnected');
    log.info('Rouvy disconnected');
  } catch (error) {
    log.error('Failed to disconnect Rouvy', { error });
    toast.error('Failed to disconnect Rouvy');
  }
}

/** Delegated click handling for the Rouvy field's buttons. */
export function handleRouvyClick(target: HTMLElement): void {
  if (target.classList.contains('settings-rouvy-connect')) {
    void handleRouvyConnect();
  }

  // Show login form (reconnect)
  if (target.classList.contains('settings-rouvy-show-login')) {
    rouvyStatus = { connected: false, connected_at: null, needs_reconnect: false };
    updateRouvySection();
  }

  if (target.classList.contains('settings-rouvy-disconnect')) {
    void handleRouvyDisconnect();
  }
}
