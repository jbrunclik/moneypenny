/**
 * Field telemetry for iOS layout regressions.
 *
 * The keyboard and scroll code can only be verified on a real iPhone, and a
 * regression used to surface as a family member's screenshot days later. This
 * module checks a few layout invariants during normal use and reports a
 * violation (kind "layout", through core/error-reporting.ts) so the admin page
 * shows, per build, whether a new build broke something.
 *
 * Observe only: it reads geometry and never writes styles or scrolls. It
 * checks at settled moments - LAYOUT_CHECK_SETTLE_MS after the last viewport
 * event with the geometry unchanged, never mid-animation - and a failure must
 * still hold LAYOUT_CHECK_CONFIRM_MS later (the keyboard code's settle poller
 * gets to fix it first). Each invariant and shape is sent once per page load,
 * at most LAYOUT_REPORTS_PER_PAGE_MAX, LAYOUT_REPORT_MIN_INTERVAL_MS apart.
 * Touch devices only. What each check means: docs/ui/mobile-and-pwa.md.
 */
import type { LayoutCheckDetail } from '../api/client-errors';
import { isIOS } from '../components/MessageInput';
import { isTurnAnchored, turnAnchorDrift } from '../components/messages/turn-anchor';
import {
  KEYBOARD_BUILD_MARKER,
  KEYBOARD_STANDALONE_ACCESSORY_PX,
  LAYOUT_ANCHOR_DRIFT_TOLERANCE_PX,
  LAYOUT_CHECK_CONFIRM_MS,
  LAYOUT_CHECK_SETTLE_MS,
  LAYOUT_COMPOSER_GAP_TOLERANCE_PX,
  LAYOUT_INSET_TOLERANCE_PX,
  LAYOUT_REPORT_MIN_INTERVAL_MS,
  LAYOUT_REPORTS_PER_PAGE_MAX,
  LAYOUT_SCROLL_BOTTOM_TOLERANCE_PX,
} from '../config';
import { addScrollDebugListener, isSmoothScrolling, userScrolledSince } from '../utils/dom';
import { reportLayoutCheck } from './error-reporting';
import { isStandaloneDisplay, measureKeyboardInset } from './keyboard/metrics';
import { isTouchActive } from './keyboard/touch-guard';

type Invariant = LayoutCheckDetail['invariant'];
type Measurements = Record<string, number>;

interface Violation {
  invariant: Invariant;
  shape: string;
  measurements: Measurements;
}

/** What the previous settled check saw: the anchor rule compares against it. */
interface Settled {
  inset: number;
  // When the view was last seen resting on an anchored turn (null: it wasn't)
  anchorRestAt: number | null;
}

let controller: AbortController | null = null;

/** This page load's checks: pending timers, the last settled state, what went out. */
interface Session {
  settleTimer: ReturnType<typeof setTimeout> | null;
  confirmTimer: ReturnType<typeof setTimeout> | null;
  settled: Settled;
  sent: Set<string>;
  reportsSent: number;
  lastReportAt: number;
}

const session: Session = {
  settleTimer: null,
  confirmTimer: null,
  settled: { inset: 0, anchorRestAt: null },
  sent: new Set<string>(),
  reportsSent: 0,
  lastReportAt: Number.NEGATIVE_INFINITY,
};

function appliedInset(): number {
  return parseFloat(document.documentElement.style.getPropertyValue('--keyboard-inset')) || 0;
}

function messagesList(): HTMLElement | null {
  return document.getElementById('messages');
}

function windowScroll(): number {
  return Math.max(window.scrollY, document.scrollingElement?.scrollTop ?? 0);
}

/** The numbers every report carries. */
function viewportNumbers(viewport: VisualViewport): Measurements {
  return {
    inner_height: window.innerHeight,
    vv_height: viewport.height,
    vv_offset_top: viewport.offsetTop,
    keyboard_inset: appliedInset(),
    scroll_y: windowScroll(),
  };
}

function geometryKey(viewport: VisualViewport): string {
  return [viewport.height, viewport.offsetTop, viewport.scale, window.innerHeight, windowScroll(), appliedInset()].join('|');
}

/** iOS version: Safari's Version/ token, else the OS token (frozen at 18.6 on iOS 26). */
function iosVersion(): string | null {
  const ua = navigator.userAgent;
  const version = /Version\/(\d+(?:\.\d+)?)/.exec(ua)?.[1] ?? null;
  const os = /OS (\d+)_(\d+)/.exec(ua);
  return version ?? (os ? `${os[1]}.${os[2]}` : null);
}

/** With the keyboard up, the composer sits right on top of it (or the pill). */
function composerGap(viewport: VisualViewport): Violation | null {
  const composer = document.querySelector('.input-area');
  if (appliedInset() <= 0 || measureKeyboardInset(viewport).inset <= 0) return null;
  if (!(composer instanceof HTMLElement) || composer.classList.contains('hidden')) return null;
  const rect = composer.getBoundingClientRect();
  if (rect.height === 0) return null;
  // Standalone: iOS's input-assistant pill floats inside the visual viewport
  const accessory = isStandaloneDisplay() ? KEYBOARD_STANDALONE_ACCESSORY_PX : 0;
  // Positive: a dead band above the keyboard; negative: the composer under it
  const deviation = viewport.offsetTop + viewport.height - accessory - rect.bottom;
  if (Math.abs(deviation) <= LAYOUT_COMPOSER_GAP_TOLERANCE_PX) return null;
  return {
    invariant: 'composer_gap',
    shape: deviation > 0 ? 'gap' : 'overlap',
    measurements: { composer_top: rect.top, composer_bottom: rect.bottom, deviation },
  };
}

/** The window is never legitimately scrolled (keyboard-viewport resets it). */
function strandedPan(): Violation | null {
  const scrolled = windowScroll();
  if (isTouchActive() || scrolled <= 1) return null;
  return {
    invariant: 'stranded_pan',
    shape: appliedInset() > 0 ? 'keyboard-open' : 'keyboard-closed',
    measurements: { deviation: scrolled },
  };
}

/** The applied --keyboard-inset matches the formula for the settled viewport. */
function insetMismatch(viewport: VisualViewport): Violation | null {
  const applied = appliedInset();
  const { inset: expected, shrink } = measureKeyboardInset(viewport);
  const deviation = applied - expected;
  if (Math.abs(deviation) <= LAYOUT_INSET_TOLERANCE_PX) return null;
  const shape = expected === 0 ? 'stuck' : applied === 0 ? 'missing' : 'off';
  return { invariant: 'inset_mismatch', shape, measurements: { expected_inset: expected, shrink, deviation } };
}

/** An anchored turn the view rested on stays on its anchor as the keyboard moves. */
function anchorDrift(before: Settled): Violation | null {
  const container = messagesList();
  const keyboardUp = appliedInset() > 0;
  if (!container || before.anchorRestAt === null || keyboardUp === (before.inset > 0)) return null;
  // The user scrolling owns the position; a glide in flight lands on its own
  if (!isTurnAnchored() || userScrolledSince(before.anchorRestAt) || isSmoothScrolling()) return null;
  const drift = turnAnchorDrift(container);
  if (drift === null || Math.abs(drift) <= LAYOUT_ANCHOR_DRIFT_TOLERANCE_PX) return null;
  return {
    invariant: 'anchor_drift',
    shape: keyboardUp ? 'keyboard-open' : 'keyboard-close',
    measurements: { deviation: drift },
  };
}

function settledViolations(viewport: VisualViewport, before: Settled): Violation[] {
  // Pinch zoom moves everything on purpose
  if (viewport.scale !== 1) return [];
  return [composerGap(viewport), strandedPan(), insetMismatch(viewport), anchorDrift(before)].filter(
    (v): v is Violation => v !== null
  );
}

function report(viewport: VisualViewport, violation: Violation): void {
  const key = `${violation.invariant}|${violation.shape}`;
  const now = Date.now();
  if (session.sent.has(key) || session.reportsSent >= LAYOUT_REPORTS_PER_PAGE_MAX) return;
  // Too soon after the last one: not marked sent, so a later repeat goes out
  if (now - session.lastReportAt < LAYOUT_REPORT_MIN_INTERVAL_MS) return;
  const measurements = { ...viewportNumbers(viewport), ...violation.measurements };
  const rounded = Object.fromEntries(Object.entries(measurements).map(([k, v]) => [k, Math.round(v * 10) / 10]));
  const delivered = reportLayoutCheck({
    invariant: violation.invariant,
    shape: violation.shape,
    build_marker: KEYBOARD_BUILD_MARKER,
    standalone: isStandaloneDisplay(),
    ios_version: iosVersion(),
    measurements: rounded,
  });
  if (!delivered) return;
  session.sent.add(key);
  session.reportsSent += 1;
  session.lastReportAt = now;
}

function remember(): Settled {
  const container = messagesList();
  const drift = container && isTurnAnchored() ? turnAnchorDrift(container) : null;
  const resting = drift !== null && Math.abs(drift) <= LAYOUT_ANCHOR_DRIFT_TOLERANCE_PX;
  return { inset: appliedInset(), anchorRestAt: resting ? performance.now() : null };
}

/** The layout settled: check, and re-check failures once before reporting. */
function runSettledChecks(viewport: VisualViewport): void {
  const before = session.settled;
  const first = settledViolations(viewport, before);
  session.settled = remember();
  if (first.length === 0) return;
  session.confirmTimer = setTimeout(() => {
    session.confirmTimer = null;
    const again = settledViolations(viewport, before);
    for (const violation of again) {
      if (first.some((f) => f.invariant === violation.invariant && f.shape === violation.shape)) {
        report(viewport, violation);
      }
    }
  }, LAYOUT_CHECK_CONFIRM_MS);
}

function armSettle(viewport: VisualViewport): void {
  if (session.settleTimer) clearTimeout(session.settleTimer);
  const armedGeometry = geometryKey(viewport);
  session.settleTimer = setTimeout(() => {
    session.settleTimer = null;
    // iOS moves the viewport without an event at times: not settled yet
    if (geometryKey(viewport) !== armedGeometry) {
      armSettle(viewport);
      return;
    }
    runSettledChecks(viewport);
  }, LAYOUT_CHECK_SETTLE_MS);
}

/** Something moved: whatever was pending is mid-animation now. */
function onLayoutEvent(viewport: VisualViewport): void {
  if (session.confirmTimer) {
    clearTimeout(session.confirmTimer);
    session.confirmTimer = null;
  }
  armSettle(viewport);
}

/** A scroll to the bottom said it finished: it should have landed there. */
function checkScrollBottom(viewport: VisualViewport, gapAtDone: unknown, signal: AbortSignal): void {
  if (typeof gapAtDone !== 'number' || gapAtDone <= LAYOUT_SCROLL_BOTTOM_TOLERANCE_PX) return;
  const doneAt = performance.now();
  setTimeout(() => {
    const container = messagesList();
    if (!container || signal.aborted) return;
    // An anchored turn, the user, or another scroll owns the position now
    if (isTurnAnchored() || userScrolledSince(doneAt) || isSmoothScrolling()) return;
    const gap = container.scrollHeight - container.scrollTop - container.clientHeight;
    if (gap <= LAYOUT_SCROLL_BOTTOM_TOLERANCE_PX) return;
    report(viewport, { invariant: 'scroll_bottom_miss', shape: 'short', measurements: { deviation: gap } });
  }, LAYOUT_CHECK_CONFIRM_MS);
}

function shouldRun(): boolean {
  return isIOS() || Boolean(window.matchMedia?.('(pointer: coarse)').matches);
}

/** Start the checks (touch devices with a visualViewport only). */
export function initLayoutChecks(): void {
  stopLayoutChecks();
  const viewport = window.visualViewport;
  if (!viewport || !shouldRun()) return;
  controller = new AbortController();
  const { signal } = controller;
  const onEvent = (): void => onLayoutEvent(viewport);
  viewport.addEventListener('resize', onEvent, { signal });
  viewport.addEventListener('scroll', onEvent, { signal });
  window.addEventListener('resize', onEvent, { signal });
  window.addEventListener('scroll', onEvent, { passive: true, signal });
  document.addEventListener('focusin', onEvent, { signal });
  document.addEventListener('focusout', onEvent, { signal });
  const removeListener = addScrollDebugListener((event, data) => {
    if (event === 'bottom-done') checkScrollBottom(viewport, data.gap, signal);
    // A send glide just put the view on its anchored turn: no viewport event
    // marks that moment, and the anchor rule needs it
    if (event === 'glide-done') session.settled = { ...session.settled, anchorRestAt: remember().anchorRestAt };
  });
  signal.addEventListener('abort', removeListener);
  session.settled = remember();
  armSettle(viewport);
}

/** Stop and forget what was sent (tests, re-init). */
export function stopLayoutChecks(): void {
  controller?.abort();
  controller = null;
  if (session.settleTimer) clearTimeout(session.settleTimer);
  if (session.confirmTimer) clearTimeout(session.confirmTimer);
  session.settleTimer = null;
  session.confirmTimer = null;
  session.settled = { inset: 0, anchorRestAt: null };
  session.sent.clear();
  session.reportsSent = 0;
  session.lastReportAt = Number.NEGATIVE_INFINITY;
}
