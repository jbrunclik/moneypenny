/**
 * Browser errors reach the server (admin page, regular reviews) instead of
 * living only in one device's console.
 *
 * Uncaught errors, unhandled rejections and error-level log entries are sent
 * once each per page load, at most ERROR_REPORTS_PER_PAGE_MAX, and only for a
 * signed-in user. Sent: the kind, message, stack, route and build version -
 * never the log context, which can hold what the user wrote.
 */
import { clientErrors, type ClientErrorReport } from '../api/client-errors';
import { getToken } from '../api/http';
import { ERROR_REPORTS_PER_PAGE_MAX } from '../config';
import { setErrorSink } from '../utils/logger';

type Kind = ClientErrorReport['kind'];

const sent = new Set<string>();
let controller: AbortController | null = null;

function describe(reason: unknown): { message: string; stack: string | null } {
  if (reason instanceof Error) {
    return { message: `${reason.name}: ${reason.message}`, stack: reason.stack ?? null };
  }
  return { message: String(reason), stack: null };
}

function send(kind: Kind, message: string, stack: string | null): void {
  const key = `${kind}|${message}`;
  if (!getToken() || sent.has(key) || sent.size >= ERROR_REPORTS_PER_PAGE_MAX) return;
  sent.add(key);
  const report: ClientErrorReport = {
    kind,
    message,
    stack,
    path: window.location.hash.split('?')[0] || window.location.pathname,
    app_version: document.getElementById('app')?.dataset.version ?? null,
  };
  // Reporting a failed report would loop; a lost report is acceptable
  clientErrors.report(report).catch(() => {});
}

export function initErrorReporting(): void {
  stopErrorReporting();
  controller = new AbortController();
  const { signal } = controller;
  window.addEventListener(
    'error',
    (e) => {
      const stack = e.error instanceof Error ? (e.error.stack ?? null) : null;
      send('error', e.message || describe(e.error).message, stack);
    },
    { signal }
  );
  window.addEventListener(
    'unhandledrejection',
    (e) => {
      const { message, stack } = describe(e.reason);
      send('unhandled_rejection', message, stack);
    },
    { signal }
  );
  setErrorSink((loggerName, message, error) => {
    const detail = error ? `: ${error.message}` : '';
    send('logged', `[${loggerName}] ${message}${detail}`, error?.stack ?? null);
  });
}

/** Detach the listeners and forget what was sent (tests, re-init). */
export function stopErrorReporting(): void {
  controller?.abort();
  controller = null;
  setErrorSink(null);
  sent.clear();
}
