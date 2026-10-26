/**
 * Rouvy settings field: loading, login form, connected and expired-session
 * states; connecting (both fields required, the button re-enabled on
 * failure), Reconnect back to the login form, and disconnecting.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const api = vi.hoisted(() => ({
  connect: vi.fn<(email: string, password: string) => Promise<{ connected: boolean }>>(),
  disconnect: vi.fn<() => Promise<void>>(),
}));
const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock('@/api/integrations', () => ({ rouvy: api }));
vi.mock('@/components/Toast', () => ({ toast: toastMock }));

import { handleRouvyClick, renderRouvyField, setRouvyStatus } from '@/components/settings/rouvy';
import { POPUP_ID } from '@/components/settings/shared';

function mount(): void {
  document.body.innerHTML = `<div id="${POPUP_ID}">${renderRouvyField()}</div>`;
}

function q<T extends HTMLElement>(selector: string): T {
  const el = document.querySelector<T>(selector);
  if (!el) throw new Error(`${selector} not rendered`);
  return el;
}

function fillLogin(email: string, password: string): void {
  q<HTMLInputElement>('.settings-rouvy-email').value = email;
  q<HTMLInputElement>('.settings-rouvy-password').value = password;
}

beforeEach(() => {
  vi.clearAllMocks();
  api.connect.mockResolvedValue({ connected: true });
  api.disconnect.mockResolvedValue(undefined);
  setRouvyStatus({ connected: false, connected_at: null, needs_reconnect: false });
});

describe('rouvy settings rendering', () => {
  it('shows a loading line before the status is known', () => {
    setRouvyStatus(null);
    mount();
    expect(document.querySelector('.settings-rouvy-loading')).not.toBeNull();
  });

  it('shows the login form when disconnected', () => {
    mount();
    expect(document.querySelector('.settings-rouvy-login-form')).not.toBeNull();
  });

  it('shows Disconnect when connected', () => {
    setRouvyStatus({ connected: true, connected_at: '2026-01-01', needs_reconnect: false });
    mount();
    expect(document.querySelector('.settings-rouvy-connected .settings-rouvy-disconnect')).not.toBeNull();
  });

  it('offers Reconnect for an expired session, which shows the login form', () => {
    setRouvyStatus({ connected: true, connected_at: '2026-01-01', needs_reconnect: true });
    mount();
    handleRouvyClick(q('.settings-rouvy-show-login'));
    expect(document.querySelector('.settings-rouvy-login-form')).not.toBeNull();
  });
});

describe('rouvy connect', () => {
  it('requires both email and password', () => {
    mount();
    fillLogin('   ', 'secret');
    handleRouvyClick(q('.settings-rouvy-connect'));
    expect(api.connect).not.toHaveBeenCalled();
    expect(toastMock.error).toHaveBeenCalledWith('Enter your Rouvy email and password');
  });

  it('connects with the trimmed email and shows the connected state', async () => {
    mount();
    fillLogin(' rider@example.com ', 'secret');
    handleRouvyClick(q('.settings-rouvy-connect'));
    await vi.waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Rouvy connected'));
    expect(api.connect).toHaveBeenCalledWith('rider@example.com', 'secret');
    expect(document.querySelector('.settings-rouvy-connected')).not.toBeNull();
  });

  it('shows the error and re-enables the button when connecting fails', async () => {
    api.connect.mockRejectedValue(new Error('Rouvy login failed'));
    mount();
    fillLogin('rider@example.com', 'wrong');
    handleRouvyClick(q('.settings-rouvy-connect'));
    expect(q<HTMLButtonElement>('.settings-rouvy-connect').disabled).toBe(true);
    await vi.waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Rouvy login failed'));
    expect(q<HTMLButtonElement>('.settings-rouvy-connect').disabled).toBe(false);
  });

  it('uses a generic message for a non-Error rejection', async () => {
    api.connect.mockRejectedValue('nope');
    mount();
    fillLogin('rider@example.com', 'wrong');
    handleRouvyClick(q('.settings-rouvy-connect'));
    await vi.waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Failed to connect Rouvy'));
  });
});

describe('rouvy disconnect', () => {
  beforeEach(() => {
    setRouvyStatus({ connected: true, connected_at: '2026-01-01', needs_reconnect: false });
  });

  it('disconnects and shows the login form', async () => {
    mount();
    handleRouvyClick(q('.settings-rouvy-disconnect'));
    await vi.waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Rouvy disconnected'));
    expect(document.querySelector('.settings-rouvy-login-form')).not.toBeNull();
  });

  it('keeps the connected state when disconnecting fails', async () => {
    api.disconnect.mockRejectedValue(new Error('boom'));
    mount();
    handleRouvyClick(q('.settings-rouvy-disconnect'));
    await vi.waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Failed to disconnect Rouvy'));
    expect(document.querySelector('.settings-rouvy-connected')).not.toBeNull();
  });
});
