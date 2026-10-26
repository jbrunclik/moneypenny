/**
 * Device check measurements and waits: what the scenarios read off the live
 * layout. The viewport probes are keyboard-viewport.ts's own, so a check
 * reads the same numbers the keyboard handling decides on.
 *
 * core/layout-checks.ts (the field telemetry) measures similar invariants;
 * the two can share one measurement module later.
 */
import { isStandaloneDisplay, safeAreaTop, trueViewportHeight } from '../keyboard-viewport';
import { DEVICE_CHECK_SETTLE_MS, DEVICE_CHECK_SETTLE_TIMEOUT_MS } from '../../config';
import type { KeyboardGeometry, PanMeasure } from './evaluate';

const POLL_MS = 50;

/** Thrown out of a wait when the run is stopped. */
export class DeviceCheckAbortedError extends Error {
  constructor() {
    super('Device checks stopped');
    this.name = 'DeviceCheckAbortedError';
  }
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DeviceCheckAbortedError());
      return;
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    const onAbort = (): void => {
      clearTimeout(timer);
      reject(new DeviceCheckAbortedError());
    };
    signal.addEventListener('abort', onAbort, { once: true });
  });
}

/** Poll until `condition` holds; false when it timed out. */
export async function waitUntil(condition: () => boolean, timeoutMs: number, signal: AbortSignal): Promise<boolean> {
  const deadline = performance.now() + timeoutMs;
  while (!condition()) {
    if (performance.now() >= deadline) return false;
    await wait(POLL_MS, signal);
  }
  return true;
}

/**
 * Wait until `read` returns the same value for `stableMs` (or the timeout
 * passes) and return that value: layout that is still moving (a glide, the
 * keyboard's delayed holds) is never measured.
 */
export async function waitForStable(
  read: () => number,
  signal: AbortSignal,
  stableMs = DEVICE_CHECK_SETTLE_MS,
  timeoutMs = DEVICE_CHECK_SETTLE_TIMEOUT_MS
): Promise<number> {
  const deadline = performance.now() + timeoutMs;
  let value = read();
  let since = performance.now();
  while (performance.now() - since < stableMs && performance.now() < deadline) {
    await wait(POLL_MS, signal);
    const next = read();
    if (Math.abs(next - value) > 0.5) {
      value = next;
      since = performance.now();
    }
  }
  return value;
}

export function panMeasure(): PanMeasure {
  return {
    windowScrollY: Math.max(window.scrollY, document.scrollingElement?.scrollTop ?? 0),
    viewportOffsetTop: window.visualViewport?.offsetTop ?? 0,
  };
}

export function distanceFromBottom(container: HTMLElement): number {
  return Math.max(0, container.scrollHeight - container.scrollTop - container.clientHeight);
}

/** The applied --keyboard-inset (keyboard-viewport.ts writes it on <html>). */
export function keyboardInset(): number {
  return parseFloat(document.documentElement.style.getPropertyValue('--keyboard-inset')) || 0;
}

export function keyboardGeometry(): KeyboardGeometry {
  return {
    trueViewportHeightPx: trueViewportHeight(),
    visualViewportHeightPx: window.visualViewport?.height ?? window.innerHeight,
    safeAreaTopPx: safeAreaTop(),
    standalone: isStandaloneDisplay(),
  };
}

/** Resolved env(safe-area-inset-bottom) in px. */
export function safeAreaBottom(): number {
  const probe = document.createElement('div');
  probe.style.cssText =
    'position:fixed;visibility:hidden;pointer-events:none;height:env(safe-area-inset-bottom,0px);width:1px;';
  document.body.appendChild(probe);
  const height = probe.offsetHeight;
  probe.remove();
  return height;
}

function bottomOf(selector: string): number {
  return document.querySelector(selector)?.getBoundingClientRect().bottom ?? 0;
}

/** The composer bar's bottom edge (viewport px). */
export function composerBottom(): number {
  return bottomOf('.input-area');
}

/** The app shell's height and bottom edge (viewport px). */
export function appRect(): { height: number; bottom: number } {
  const rect = document.getElementById('app')?.getBoundingClientRect();
  return { height: rect?.height ?? 0, bottom: rect?.bottom ?? 0 };
}

/** The element's top in the list's visible area, layout-based (entrance animations transform). */
export function topInView(container: HTMLElement, el: HTMLElement): number {
  const top =
    el.offsetParent === container
      ? el.offsetTop
      : el.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop;
  return top - container.scrollTop;
}

export function scrollPaddingTop(container: HTMLElement): number {
  return parseFloat(getComputedStyle(container).scrollPaddingTop) || 0;
}

/** Round for storage: 0.1px is plenty and keeps the history readable. */
export function round(n: number): number {
  return Math.round(n * 10) / 10;
}
