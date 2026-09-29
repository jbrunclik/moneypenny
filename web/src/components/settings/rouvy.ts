import { CHECK_ICON, WARNING_ICON, ACTIVITY_ICON } from '../../utils/icons';
import { rouvy, type RouvyStatus } from '../../api/client';
import { toast } from '../Toast';
import { log, renderFieldLabel, rerenderField } from './shared';

const LABEL = 'Rouvy';

/** Current Rouvy connection status */
let rouvyStatus: RouvyStatus | null = null;

export function setRouvyStatus(status: RouvyStatus | null): void {
  rouvyStatus = status;
}

/**
 * Render Rouvy section (no MFA — Rouvy's login flow has none)
 */
function renderRouvyBody(status: RouvyStatus | null): string {
  if (status === null) {
    return `<div class="settings-rouvy-loading">Loading Rouvy status...</div>`;
  }

  if (status.connected && status.needs_reconnect) {
    return `
      <div class="settings-rouvy-needs-reconnect">
        <span class="settings-rouvy-status">
          <span class="settings-rouvy-icon warning">${WARNING_ICON}</span>
          Rouvy session expired
        </span>
        <p class="settings-helper">Your Rouvy session has expired. Please reconnect with your credentials.</p>
        <div class="settings-rouvy-actions">
          <button type="button" class="btn btn-primary btn-sm settings-rouvy-show-login">
            Reconnect
          </button>
          <button type="button" class="btn btn-secondary btn-sm settings-rouvy-disconnect">
            Disconnect
          </button>
        </div>
      </div>
    `;
  }

  if (status.connected) {
    return `
      <div class="settings-rouvy-connected">
        <span class="settings-rouvy-status">
          <span class="settings-rouvy-icon connected">${CHECK_ICON}</span>
          Connected
        </span>
        <button type="button" class="btn btn-secondary btn-sm settings-rouvy-disconnect">
          Disconnect
        </button>
      </div>
    `;
  }

  return `
    <div class="settings-rouvy-disconnected">
      <p class="settings-helper">Connect your Rouvy account so the coach can upload workouts directly.</p>
      <div class="settings-rouvy-login-form">
        <input
          type="email"
          class="settings-input settings-rouvy-email"
          placeholder="Rouvy email"
          autocomplete="email"
        />
        <input
          type="password"
          class="settings-input settings-rouvy-password"
          placeholder="Rouvy password"
          autocomplete="current-password"
        />
        <p class="settings-helper settings-helper-muted">Your password is stored encrypted so the session can be refreshed automatically.</p>
        <button type="button" class="btn btn-primary settings-rouvy-connect">
          Connect Rouvy
        </button>
      </div>
    </div>
  `;
}

/** Render the whole Rouvy field (label + status body). */
export function renderRouvyField(): string {
  return `
      <div class="settings-field" data-section="rouvy">
        ${renderFieldLabel(ACTIVITY_ICON, LABEL)}
        ${renderRouvyBody(rouvyStatus)}
      </div>
  `;
}

/**
 * Update Rouvy section in the popup
 */
function updateRouvySection(): void {
  rerenderField('rouvy', ACTIVITY_ICON, LABEL, renderRouvyBody(rouvyStatus));
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
