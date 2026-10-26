import { CHECK_ICON, WARNING_ICON, ACTIVITY_ICON } from '../../utils/icons';
import { garmin } from '../../api/integrations';
import { ApiError } from '../../api/http';
import { toast } from '../Toast';
import type { GarminStatus } from '../../types/api';
import { createElement } from '../../utils/dom';
import { useStore } from '../../state/store';
import { helper, log, rerenderField, settingsField, statusLine, textButton } from './shared';

const LABEL = 'Garmin Connect';

const DISCONNECTED: GarminStatus = { connected: false, connected_at: null, needs_reconnect: false };

/** The status and whether the login waits for an MFA code (store: settings slice). */
function setGarmin(status: GarminStatus | null, mfaRequired: boolean): void {
  const store = useStore.getState();
  store.setIntegrationStatus('garmin', status);
  store.setGarminMfaRequired(mfaRequired);
}

/**
 * Credentials retained in memory while we await the MFA code so we can
 * re-submit them together with the code. The MFA flow on the backend runs
 * a single full login per request (no cross-request state), which means we
 * have to resend email+password with the MFA code. Cleared after MFA
 * success, cancel, or any settled outcome. Kept here, out of the shared
 * store, so the password lives only as long as the MFA step.
 */
// UI-local (F2): the password must not reach the shared store
let garminPendingCredentials: { email: string; password: string } | null = null;

/** Adopt a freshly fetched status and drop any half-finished MFA flow. */
export function resetGarminState(status: GarminStatus | null): void {
  setGarmin(status, false);
  garminPendingCredentials = null;
}

/** The MFA step: the code input, Submit and Cancel. */
function mfaForm(): HTMLElement {
  return createElement('div', { class: 'settings-garmin-mfa' }, [
    helper('Garmin requires a verification code. Check your email or authenticator app.'),
    createElement('input', {
      type: 'text',
      class: 'settings-input settings-garmin-mfa-input',
      placeholder: 'Enter MFA code',
      maxlength: '10',
      autocomplete: 'one-time-code',
    }),
    createElement('div', { class: 'settings-garmin-actions' }, [
      textButton('btn btn-primary settings-garmin-mfa-submit', 'Submit'),
      textButton('btn btn-secondary settings-garmin-mfa-cancel', 'Cancel'),
    ]),
  ]);
}

/** The login form shown while disconnected. */
function loginForm(): HTMLElement {
  return createElement('div', { class: 'settings-garmin-disconnected' }, [
    helper('Connect your Garmin account to access health and training data'),
    createElement('div', { class: 'settings-garmin-login-form' }, [
      createElement('input', { type: 'email', class: 'settings-input settings-garmin-email', placeholder: 'Garmin email', autocomplete: 'email' }),
      createElement('input', {
        type: 'password',
        class: 'settings-input settings-garmin-password',
        placeholder: 'Garmin password',
        autocomplete: 'current-password',
      }),
      helper('Your password is used to create a session token and is never stored.', true),
      textButton('btn btn-primary settings-garmin-connect', 'Connect Garmin'),
    ]),
  ]);
}

/**
 * The Garmin Connect section
 */
function garminBody(status: GarminStatus | null, mfaRequired: boolean): HTMLElement[] {
  if (status === null) {
    return [createElement('div', { class: 'settings-garmin-loading' }, ['Loading Garmin status...'])];
  }

  if (mfaRequired) return [mfaForm()];

  if (status.connected && status.needs_reconnect) {
    return [
      createElement('div', { class: 'settings-garmin-needs-reconnect' }, [
        statusLine('garmin', 'warning', WARNING_ICON, 'Garmin session expired'),
        helper('Your Garmin session has expired. Please reconnect with your credentials.'),
        createElement('div', { class: 'settings-garmin-actions' }, [
          textButton('btn btn-primary btn-sm settings-garmin-show-login', 'Reconnect'),
          textButton('btn btn-secondary btn-sm settings-garmin-disconnect', 'Disconnect'),
        ]),
      ]),
    ];
  }

  if (status.connected) {
    return [
      createElement('div', { class: 'settings-garmin-connected' }, [
        statusLine('garmin', 'connected', CHECK_ICON, 'Connected'),
        textButton('btn btn-secondary btn-sm settings-garmin-disconnect', 'Disconnect'),
      ]),
    ];
  }

  return [loginForm()];
}

/** The whole Garmin field (label + status body). */
export function renderGarminField(): HTMLElement {
  const { integrationStatuses, garminMfaRequired } = useStore.getState();
  return settingsField('garmin', ACTIVITY_ICON, LABEL, garminBody(integrationStatuses.garmin, garminMfaRequired));
}

/**
 * Update Garmin section in the popup
 */
function updateGarminSection(): void {
  const { integrationStatuses, garminMfaRequired } = useStore.getState();
  rerenderField('garmin', ACTIVITY_ICON, LABEL, garminBody(integrationStatuses.garmin, garminMfaRequired));
}

/** Mark the Garmin account connected after a successful login. */
function markGarminConnected(): void {
  garminPendingCredentials = null;
  setGarmin({ connected: true, connected_at: new Date().toISOString(), needs_reconnect: false }, false);
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
      useStore.getState().setGarminMfaRequired(true);
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
    useStore.getState().setGarminMfaRequired(false);
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
    setGarmin({ ...DISCONNECTED }, false);
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
