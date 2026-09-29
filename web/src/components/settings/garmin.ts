import { CHECK_ICON, WARNING_ICON, ACTIVITY_ICON } from '../../utils/icons';
import { garmin } from '../../api/client';
import { ApiError } from '../../api/http';
import { toast } from '../Toast';
import type { GarminStatus } from '../../types/api';
import { log, renderFieldLabel, rerenderField } from './shared';

const LABEL = 'Garmin Connect';

const DISCONNECTED: GarminStatus = { connected: false, connected_at: null, needs_reconnect: false };

/** Current Garmin Connect status */
let garminStatus: GarminStatus | null = null;

/** Garmin MFA state: awaiting MFA code input */
let garminMfaRequired = false;

/**
 * Credentials retained in memory while we await the MFA code so we can
 * re-submit them together with the code. The MFA flow on the backend runs
 * a single full login per request (no cross-request state), which means we
 * have to resend email+password with the MFA code. Cleared after MFA
 * success, cancel, or any settled outcome.
 */
let garminPendingCredentials: { email: string; password: string } | null = null;

/** Adopt a freshly fetched status and drop any half-finished MFA flow. */
export function resetGarminState(status: GarminStatus | null): void {
  garminStatus = status;
  garminMfaRequired = false;
  garminPendingCredentials = null;
}

const MFA_HTML = `
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

const LOGIN_FORM_HTML = `
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

/**
 * Render Garmin Connect section
 */
function renderGarminBody(status: GarminStatus | null, mfaRequired: boolean): string {
  if (status === null) {
    return `
      <div class="settings-garmin-loading">Loading Garmin status...</div>
    `;
  }

  if (mfaRequired) return MFA_HTML;

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

  return LOGIN_FORM_HTML;
}

/** Render the whole Garmin field (label + status body). */
export function renderGarminField(): string {
  return `
      <div class="settings-field" data-section="garmin">
        ${renderFieldLabel(ACTIVITY_ICON, LABEL)}
        ${renderGarminBody(garminStatus, garminMfaRequired)}
      </div>
  `;
}

/**
 * Update Garmin section in the popup
 */
function updateGarminSection(): void {
  rerenderField('garmin', ACTIVITY_ICON, LABEL, renderGarminBody(garminStatus, garminMfaRequired));
}

/** Mark the Garmin account connected after a successful login. */
function markGarminConnected(): void {
  garminPendingCredentials = null;
  garminStatus = { connected: true, connected_at: new Date().toISOString(), needs_reconnect: false };
  garminMfaRequired = false;
  updateGarminSection();
  toast.success('Garmin connected successfully');
}

/** Disable a submit button with a busy label; returns a restore function. */
function setBusy(btn: HTMLButtonElement | null, busyText: string): () => void {
  const originalText = btn?.textContent ?? '';
  if (btn) {
    btn.disabled = true;
    btn.textContent = busyText;
  }
  return () => {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  };
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

  const submitBtn = document.querySelector<HTMLButtonElement>('.settings-garmin-connect');
  if (submitBtn?.disabled) return;
  const restore = setBusy(submitBtn, 'Connecting...');

  try {
    log.debug('Connecting to Garmin');
    const result = await garmin.connect(email, password);

    // Clear password from DOM immediately
    passwordInput.value = '';

    if (result.mfa_required) {
      // Retain credentials so the MFA submit can resend them together with
      // the code — the backend completes login in a single request and has
      // no cross-request session state.
      garminPendingCredentials = { email, password };
      garminMfaRequired = true;
      updateGarminSection();
      return;
    }

    markGarminConnected();
    log.info('Garmin connected');
  } catch (error) {
    log.error('Failed to connect Garmin', { error });
    passwordInput.value = '';
    garminPendingCredentials = null;
    const message = error instanceof ApiError && error.message
      ? error.message
      : 'Failed to connect to Garmin. Check your credentials.';
    toast.error(message);
    restore();
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

  if (!garminPendingCredentials) {
    toast.error('Session expired. Please start the connection again.');
    garminMfaRequired = false;
    updateGarminSection();
    return;
  }

  const submitBtn = document.querySelector<HTMLButtonElement>('.settings-garmin-mfa-submit');
  if (submitBtn?.disabled) return;
  const restore = setBusy(submitBtn, 'Verifying...');

  try {
    log.debug('Submitting Garmin MFA code');
    await garmin.submitMfa(
      garminPendingCredentials.email,
      garminPendingCredentials.password,
      mfaCode,
    );

    markGarminConnected();
    log.info('Garmin connected via MFA');
  } catch (error) {
    log.error('Failed to submit Garmin MFA', { error });
    const message = error instanceof ApiError && error.message
      ? error.message
      : 'Invalid MFA code, please try again';
    toast.error(message);
    restore();
  }
}

/**
 * Handle Garmin disconnect button click
 */
async function handleGarminDisconnect(): Promise<void> {
  try {
    log.debug('Disconnecting Garmin');
    await garmin.disconnect();
    garminStatus = { ...DISCONNECTED };
    garminMfaRequired = false;
    updateGarminSection();
    toast.success('Garmin disconnected');
    log.info('Garmin disconnected');
  } catch (error) {
    log.error('Failed to disconnect Garmin', { error });
    toast.error('Failed to disconnect Garmin');
  }
}

/** Delegated click handling for the Garmin field's buttons. */
export function handleGarminClick(target: HTMLElement): void {
  if (target.classList.contains('settings-garmin-connect')) {
    void handleGarminConnect();
  }

  // Show login form (reconnect) or cancel MFA: back to the login form
  if (
    target.classList.contains('settings-garmin-show-login') ||
    target.classList.contains('settings-garmin-mfa-cancel')
  ) {
    resetGarminState({ ...DISCONNECTED });
    updateGarminSection();
  }

  if (target.classList.contains('settings-garmin-disconnect')) {
    void handleGarminDisconnect();
  }

  if (target.classList.contains('settings-garmin-mfa-submit')) {
    void handleGarminMfaSubmit();
  }
}
