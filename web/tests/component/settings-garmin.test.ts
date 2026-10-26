/**
 * Garmin Connect settings field: loading, login form, connected and
 * expired-session states; connecting with and without the MFA step (the
 * credentials are kept only until the MFA code is submitted), cancelling
 * MFA, disconnecting, and the error toasts (an ApiError's own message
 * wins over the generic one).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const api = vi.hoisted(() => ({
  connect: vi.fn<(email: string, password: string) => Promise<{ mfa_required?: boolean }>>(),
  submitMfa: vi.fn<(email: string, password: string, code: string) => Promise<unknown>>(),
  disconnect: vi.fn<() => Promise<void>>(),
}));
const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock('@/api/integrations', () => ({ garmin: api }));
vi.mock('@/components/Toast', () => ({ toast: toastMock }));

import { handleGarminClick, renderGarminField, resetGarminState } from '@/components/settings/garmin';
import { POPUP_ID } from '@/components/settings/shared';
import { ApiError } from '@/api/http';

const DISCONNECTED = { connected: false, connected_at: null, needs_reconnect: false };

/** Render the field inside the settings popup (rerenderField looks it up there). */
function mount(): HTMLElement {
  const popup = document.createElement('div');
  popup.id = POPUP_ID;
  popup.append(renderGarminField());
  document.body.replaceChildren(popup);
  return document.getElementById(POPUP_ID) as HTMLElement;
}

function q<T extends HTMLElement>(selector: string): T {
  const el = document.querySelector<T>(selector);
  if (!el) throw new Error(`${selector} not rendered`);
  return el;
}

function fillLogin(email: string, password: string): void {
  q<HTMLInputElement>('.settings-garmin-email').value = email;
  q<HTMLInputElement>('.settings-garmin-password').value = password;
}

function click(selector: string): void {
  handleGarminClick(q(selector));
}

beforeEach(() => {
  vi.clearAllMocks();
  api.connect.mockResolvedValue({ mfa_required: false });
  api.submitMfa.mockResolvedValue({});
  api.disconnect.mockResolvedValue(undefined);
  resetGarminState({ ...DISCONNECTED });
});

describe('garmin settings rendering', () => {
  it('shows a loading line before the status is known', () => {
    resetGarminState(null);
    expect(mount().querySelector('.settings-garmin-loading')).not.toBeNull();
  });

  it('shows the login form when disconnected', () => {
    const popup = mount();
    expect(popup.querySelector('.settings-garmin-login-form')).not.toBeNull();
    expect(popup.querySelector('.settings-garmin-disconnect')).toBeNull();
  });

  it('shows Disconnect when connected', () => {
    resetGarminState({ connected: true, connected_at: '2026-01-01', needs_reconnect: false });
    const popup = mount();
    expect(popup.querySelector('.settings-garmin-connected')).not.toBeNull();
    expect(popup.querySelector('.settings-garmin-disconnect')).not.toBeNull();
  });

  it('offers Reconnect for an expired session, which goes back to the login form', () => {
    resetGarminState({ connected: true, connected_at: '2026-01-01', needs_reconnect: true });
    mount();
    expect(document.querySelector('.settings-garmin-needs-reconnect')).not.toBeNull();
    click('.settings-garmin-show-login');
    expect(document.querySelector('.settings-garmin-login-form')).not.toBeNull();
  });
});

describe('garmin connect', () => {
  it('requires both email and password', () => {
    mount();
    fillLogin('me@example.com', '');
    click('.settings-garmin-connect');
    expect(api.connect).not.toHaveBeenCalled();
    expect(toastMock.error).toHaveBeenCalledWith('Please enter both email and password');
  });

  it('connects without MFA and shows the connected state', async () => {
    mount();
    fillLogin('  me@example.com ', 'secret');
    click('.settings-garmin-connect');
    await vi.waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Garmin connected successfully'));
    expect(api.connect).toHaveBeenCalledWith('me@example.com', 'secret');
    expect(document.querySelector('.settings-garmin-connected')).not.toBeNull();
  });

  it('ignores a second click while connecting', () => {
    api.connect.mockReturnValue(new Promise(() => undefined));
    mount();
    fillLogin('me@example.com', 'secret');
    click('.settings-garmin-connect');
    expect(q<HTMLButtonElement>('.settings-garmin-connect').disabled).toBe(true);
    expect(q('.settings-garmin-connect').textContent).toBe('Connecting...');
    click('.settings-garmin-connect');
    expect(api.connect).toHaveBeenCalledTimes(1);
  });

  it('asks for the MFA code and resends the credentials with it', async () => {
    api.connect.mockResolvedValue({ mfa_required: true });
    mount();
    fillLogin('me@example.com', 'secret');
    click('.settings-garmin-connect');
    await vi.waitFor(() => expect(document.querySelector('.settings-garmin-mfa')).not.toBeNull());

    q<HTMLInputElement>('.settings-garmin-mfa-input').value = ' 123456 ';
    click('.settings-garmin-mfa-submit');
    await vi.waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Garmin connected successfully'));
    expect(api.submitMfa).toHaveBeenCalledWith('me@example.com', 'secret', '123456');
    expect(document.querySelector('.settings-garmin-connected')).not.toBeNull();
  });

  it('requires an MFA code', async () => {
    api.connect.mockResolvedValue({ mfa_required: true });
    mount();
    fillLogin('me@example.com', 'secret');
    click('.settings-garmin-connect');
    await vi.waitFor(() => expect(document.querySelector('.settings-garmin-mfa')).not.toBeNull());
    click('.settings-garmin-mfa-submit');
    expect(toastMock.error).toHaveBeenCalledWith('Please enter the MFA code');
    expect(api.submitMfa).not.toHaveBeenCalled();
  });

  it('cancelling MFA drops the credentials and shows the login form', async () => {
    api.connect.mockResolvedValue({ mfa_required: true });
    mount();
    fillLogin('me@example.com', 'secret');
    click('.settings-garmin-connect');
    await vi.waitFor(() => expect(document.querySelector('.settings-garmin-mfa')).not.toBeNull());
    click('.settings-garmin-mfa-cancel');
    expect(document.querySelector('.settings-garmin-login-form')).not.toBeNull();
  });

  it('keeps the MFA form and re-enables Submit when the code is rejected', async () => {
    api.connect.mockResolvedValue({ mfa_required: true });
    api.submitMfa.mockRejectedValue(new ApiError('Wrong code', 400));
    mount();
    fillLogin('me@example.com', 'secret');
    click('.settings-garmin-connect');
    await vi.waitFor(() => expect(document.querySelector('.settings-garmin-mfa')).not.toBeNull());
    q<HTMLInputElement>('.settings-garmin-mfa-input').value = '000000';
    click('.settings-garmin-mfa-submit');
    await vi.waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Wrong code'));
    expect(q<HTMLButtonElement>('.settings-garmin-mfa-submit').disabled).toBe(false);
    expect(q('.settings-garmin-mfa-submit').textContent).toContain('Submit');
  });

  it('shows the server message on an ApiError and clears the password', async () => {
    api.connect.mockRejectedValue(new ApiError('Invalid credentials', 401));
    mount();
    fillLogin('me@example.com', 'secret');
    click('.settings-garmin-connect');
    await vi.waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Invalid credentials'));
    expect(q<HTMLInputElement>('.settings-garmin-password').value).toBe('');
    expect(q<HTMLButtonElement>('.settings-garmin-connect').disabled).toBe(false);
  });

  it('falls back to a generic message for other errors', async () => {
    api.connect.mockRejectedValue(new Error('network'));
    mount();
    fillLogin('me@example.com', 'secret');
    click('.settings-garmin-connect');
    await vi.waitFor(() =>
      expect(toastMock.error).toHaveBeenCalledWith('Failed to connect to Garmin. Check your credentials.')
    );
  });
});

describe('garmin disconnect', () => {
  beforeEach(() => {
    resetGarminState({ connected: true, connected_at: '2026-01-01', needs_reconnect: false });
  });

  it('disconnects and shows the login form', async () => {
    mount();
    click('.settings-garmin-disconnect');
    await vi.waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Garmin disconnected'));
    expect(document.querySelector('.settings-garmin-login-form')).not.toBeNull();
  });

  it('keeps the connected state when disconnecting fails', async () => {
    api.disconnect.mockRejectedValue(new Error('boom'));
    mount();
    click('.settings-garmin-disconnect');
    await vi.waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Failed to disconnect Garmin'));
    expect(document.querySelector('.settings-garmin-connected')).not.toBeNull();
  });
});
