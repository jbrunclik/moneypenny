/**
 * Browser errors reach the server (core/error-reporting.ts): uncaught errors,
 * unhandled rejections and error-level log entries, once each per page load,
 * capped, only when signed in, and never with the log context.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clientErrors } from '@/api/client-errors';
import { getToken } from '@/api/http';
import { initErrorReporting, stopErrorReporting } from '@/core/error-reporting';
import { ERROR_REPORTS_PER_PAGE_MAX } from '@/config';
import { createLogger } from '@/utils/logger';

vi.mock('@/api/client-errors', () => ({ clientErrors: { report: vi.fn() } }));
vi.mock('@/api/http', async (original) => ({
  ...(await original<typeof import('@/api/http')>()),
  getToken: vi.fn(),
}));

const report = vi.mocked(clientErrors.report);

function throwUncaught(message: string): void {
  const error = new Error(message);
  window.dispatchEvent(new ErrorEvent('error', { message, error }));
}

describe('error reporting', () => {
  beforeEach(() => {
    report.mockReset().mockResolvedValue(undefined);
    vi.mocked(getToken).mockReturnValue('token');
    document.body.innerHTML = '<div id="app" data-version="1.2.3"></div>';
    window.location.hash = '#/chat/abc?q=private';
    vi.spyOn(console, 'error').mockImplementation(() => {});
    initErrorReporting();
  });

  afterEach(() => {
    stopErrorReporting();
    vi.restoreAllMocks();
  });

  it('reports an uncaught error with where and which build', () => {
    throwUncaught('x is undefined');
    expect(report).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'error',
        message: 'x is undefined',
        path: '#/chat/abc',
        app_version: '1.2.3',
      })
    );
    expect(report.mock.calls[0]![0].stack).toContain('x is undefined');
  });

  it('reports an unhandled rejection', () => {
    const event = new Event('unhandledrejection') as PromiseRejectionEvent;
    Object.defineProperty(event, 'reason', { value: new TypeError('boom') });
    window.dispatchEvent(event);
    expect(report).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'unhandled_rejection', message: 'TypeError: boom' })
    );
  });

  it('reports an error-level log entry without its context', () => {
    createLogger('sync').error('Sync failed', { error: new Error('503'), draft: 'secret text' });
    const sent = report.mock.calls[0]![0];
    expect(sent).toMatchObject({ kind: 'logged', message: '[sync] Sync failed: 503' });
    expect(JSON.stringify(sent)).not.toContain('secret text');
  });

  it('sends the same error once per page load', () => {
    throwUncaught('again');
    throwUncaught('again');
    expect(report).toHaveBeenCalledTimes(1);
  });

  it('stops after the cap', () => {
    for (let i = 0; i < ERROR_REPORTS_PER_PAGE_MAX + 5; i++) throwUncaught(`error ${i}`);
    expect(report).toHaveBeenCalledTimes(ERROR_REPORTS_PER_PAGE_MAX);
  });

  it('sends nothing when signed out', () => {
    vi.mocked(getToken).mockReturnValue(null);
    throwUncaught('before login');
    expect(report).not.toHaveBeenCalled();
  });

  it('swallows a failed report instead of reporting it', async () => {
    report.mockRejectedValue(new Error('offline'));
    throwUncaught('first');
    await Promise.resolve();
    await Promise.resolve();
    expect(report).toHaveBeenCalledTimes(1);
  });
});
