/**
 * Device check verdicts: pure functions from a scenario's measurements to
 * passed/failed with the reasons. Kept apart from the measuring (measure.ts,
 * and keyboard/metrics.ts for the keyboard model both checkers share) so
 * every threshold is unit-tested with fake numbers.
 */
import {
  DEVICE_CHECK_ANCHOR_TOLERANCE_PX,
  DEVICE_CHECK_BOTTOM_TOLERANCE_PX,
  DEVICE_CHECK_GAP_TOLERANCE_PX,
  DEVICE_CHECK_INSET_TOLERANCE_PX,
  DEVICE_CHECK_LAYOUT_TOLERANCE_PX,
  DEVICE_CHECK_PAN_TOLERANCE_PX,
  DEVICE_CHECK_TURN_MOVE_TOLERANCE_PX,
} from '../../config';

export interface Verdict {
  status: 'passed' | 'failed';
  failures: string[];
}

/** Window pan: iOS scrolls the window / pans the visual viewport for its caret reveal. */
export interface PanMeasure {
  windowScrollY: number;
  viewportOffsetTop: number;
}

type Check = readonly [ok: boolean, failure: string];

function verdict(checks: readonly Check[]): Verdict {
  const failures = checks.filter(([ok]) => !ok).map(([, failure]) => failure);
  return { status: failures.length ? 'failed' : 'passed', failures };
}

const px = (n: number): string => `${Math.round(n * 10) / 10}px`;

function panChecks(m: PanMeasure): Check[] {
  return [
    [Math.abs(m.windowScrollY) <= DEVICE_CHECK_PAN_TOLERANCE_PX, `window scrolled by ${px(m.windowScrollY)}`],
    [
      Math.abs(m.viewportOffsetTop) <= DEVICE_CHECK_PAN_TOLERANCE_PX,
      `visual viewport panned by ${px(m.viewportOffsetTop)}`,
    ],
  ];
}

export interface BottomMeasure extends PanMeasure {
  renderedMessages: number;
  distanceFromBottomPx: number;
}

/** A long conversation opened at its bottom. */
export function evaluateBottom(m: BottomMeasure): Verdict {
  return verdict([
    [m.renderedMessages > 0, 'no messages rendered'],
    [
      m.distanceFromBottomPx <= DEVICE_CHECK_BOTTOM_TOLERANCE_PX,
      `ended ${px(m.distanceFromBottomPx)} above the bottom`,
    ],
    ...panChecks(m),
  ]);
}

export interface AnchorMeasure extends PanMeasure {
  /** The turn's top in the view minus scroll-padding-top (+ = below the anchor) */
  anchorOffsetPx: number;
  anchored: boolean;
}

/** Send-to-top: the turn sits just under the header. */
export function evaluateAnchor(m: AnchorMeasure): Verdict {
  const where = m.anchorOffsetPx > 0 ? 'below' : 'above';
  return verdict([
    [m.anchored, 'the app does not report the turn as anchored'],
    [
      Math.abs(m.anchorOffsetPx) <= DEVICE_CHECK_ANCHOR_TOLERANCE_PX,
      `turn ${px(Math.abs(m.anchorOffsetPx))} ${where} the anchor`,
    ],
    ...panChecks(m),
  ]);
}

export interface KeyboardOpenMeasure extends PanMeasure {
  insetPx: number;
  expectedInsetPx: number;
  composerGapPx: number;
  expectedGapPx: number;
  /** How far the anchored turn moved; null when no turn was anchored */
  turnMovedPx: number | null;
  /** Where it ended: its top in the view minus scroll-padding-top (+ = below the anchor line) */
  turnFromAnchorPx: number | null;
}

function turnMovedFailure(m: KeyboardOpenMeasure): string {
  const moved = `anchored turn moved ${px(m.turnMovedPx ?? 0)}`;
  if (m.turnFromAnchorPx === null) return moved;
  if (Math.abs(m.turnFromAnchorPx) <= DEVICE_CHECK_ANCHOR_TOLERANCE_PX) return `${moved}, ending on the anchor line`;
  const where = m.turnFromAnchorPx < 0 ? 'above the anchor line (under the header)' : 'below the anchor line';
  return `${moved}, ending ${px(Math.abs(m.turnFromAnchorPx))} ${where}`;
}

function gapCheck(m: { composerGapPx: number; expectedGapPx: number }): Check {
  const off = m.composerGapPx - m.expectedGapPx;
  const failure =
    off < 0
      ? `composer ${px(-off)} behind the keyboard`
      : `${px(off)} gap between the composer and the keyboard`;
  return [Math.abs(off) <= DEVICE_CHECK_GAP_TOLERANCE_PX, failure];
}

/** The keyboard opened: inset, composer on the keyboard, no pan, turn kept. */
export function evaluateKeyboardOpen(m: KeyboardOpenMeasure): Verdict {
  return verdict([
    [m.insetPx > 0, 'keyboard inset stayed 0'],
    [
      Math.abs(m.insetPx - m.expectedInsetPx) <= DEVICE_CHECK_INSET_TOLERANCE_PX,
      `inset ${px(m.insetPx)}, the formula gives ${px(m.expectedInsetPx)}`,
    ],
    gapCheck(m),
    ...panChecks(m),
    [
      m.turnMovedPx === null || Math.abs(m.turnMovedPx) <= DEVICE_CHECK_TURN_MOVE_TOLERANCE_PX,
      turnMovedFailure(m),
    ],
  ]);
}

export interface ScrollButtonMeasure extends PanMeasure {
  buttonShown: boolean;
  distanceFromBottomPx: number;
  composerGapPx: number;
  expectedGapPx: number;
}

/** The scroll-to-bottom button with the keyboard up. */
export function evaluateScrollButton(m: ScrollButtonMeasure): Verdict {
  return verdict([
    [m.buttonShown, 'the button did not show after scrolling away'],
    [
      m.distanceFromBottomPx <= DEVICE_CHECK_BOTTOM_TOLERANCE_PX,
      `ended ${px(m.distanceFromBottomPx)} above the bottom`,
    ],
    gapCheck(m),
    ...panChecks(m),
  ]);
}

export interface KeyboardCloseMeasure extends PanMeasure {
  insetPx: number;
  kbOpenClass: boolean;
  appHeightPx: number;
  trueViewportHeightPx: number;
  /** #app bottom minus the composer's bottom (+ = a band under the composer) */
  composerBottomGapPx: number;
}

/** The keyboard closed: the layout is back to full height with no gap. */
export function evaluateKeyboardClose(m: KeyboardCloseMeasure): Verdict {
  return verdict([
    [m.insetPx === 0, `keyboard inset stuck at ${px(m.insetPx)}`],
    [!m.kbOpenClass, 'kb-open is still set'],
    [
      Math.abs(m.appHeightPx - m.trueViewportHeightPx) <= DEVICE_CHECK_LAYOUT_TOLERANCE_PX,
      `app ${px(m.appHeightPx)} tall in a ${px(m.trueViewportHeightPx)} viewport`,
    ],
    [
      Math.abs(m.composerBottomGapPx) <= DEVICE_CHECK_LAYOUT_TOLERANCE_PX,
      `${px(m.composerBottomGapPx)} band under the composer`,
    ],
    ...panChecks(m),
  ]);
}

function operatingSystem(ua: string, iPadOs: boolean): string {
  const ios = /(?:iPhone|CPU) OS (\d+)[_.](\d+)/.exec(ua);
  if (ios) {
    // iOS 26 freezes the OS in the UA at 18.6; Safari's Version/ tracks the
    // real release (the standalone PWA sends no Version/: it shows the frozen one)
    const safari = /Version\/(\d+(?:\.\d+)?)/.exec(ua)?.[1];
    return `iOS ${safari ?? `${ios[1]}.${ios[2]}`}`;
  }
  if (iPadOs) return 'iPadOS';
  const android = /Android (\d+)/.exec(ua)?.[1];
  if (android) return `Android ${android}`;
  const desktops: ReadonlyArray<readonly [name: string, pattern: RegExp]> = [
    ['macOS', /Mac OS X/],
    ['Windows', /Windows/],
    ['Linux', /Linux/],
  ];
  return desktops.find(([, pattern]) => pattern.test(ua))?.[0] ?? 'Other';
}

const BROWSERS: ReadonlyArray<readonly [name: string, pattern: RegExp]> = [
  ['Edge', /Edg\/(\d+)/],
  ['Firefox', /(?:Firefox|FxiOS)\/(\d+)/],
  ['Chrome', /(?:Chrome|CriOS)\/(\d+)/],
  ['Safari', /Version\/(\d+(?:\.\d+)?)/],
];

/** "iOS 26.1 · Safari 26.1", "macOS · Chrome 141", ... for the run history. */
export function summarizeUserAgent(ua: string, platform = '', maxTouchPoints = 0): string {
  const os = operatingSystem(ua, platform === 'MacIntel' && maxTouchPoints > 1);
  for (const [name, pattern] of BROWSERS) {
    const match = pattern.exec(ua);
    if (match) return `${os} · ${name} ${match[1]}`;
  }
  return /AppleWebKit/.test(ua) ? `${os} · WebKit` : os;
}
