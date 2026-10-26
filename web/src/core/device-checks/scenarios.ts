/**
 * The device check scenarios: a registry run in order by runner.ts. Each
 * drives the app's real code paths (the conversation open, the batch
 * loader's send-to-top anchoring, the keyboard handling, the scroll button),
 * measures, and leaves the verdict to evaluate.ts. Add a scenario by adding
 * an entry; see `requires` for the keyboard steps.
 */
import { addMessageToUI, showLoadingIndicator } from '../../components/messages';
import {
  isAtTurnAnchor,
  isTurnAnchored,
  turnAnchorDrift,
  turnAnchorEventCounts,
  turnAnchorExtra,
} from '../../components/messages/turn-anchor';
import { isSmoothScrolling } from '../../utils/dom';
import type { DeviceCheckMeasurements, DeviceCheckStatus } from '../../types/api';
import {
  DEVICE_CHECK_KEYBOARD_APPEAR_MS,
  DEVICE_CHECK_SETTLE_TIMEOUT_MS,
  KEYBOARD_BUILD_MARKER,
  KEYBOARD_INSET_MIN_PX,
} from '../../config';
import {
  composerGap,
  evaluateAnchor,
  evaluateBottom,
  evaluateKeyboardClose,
  evaluateKeyboardOpen,
  evaluateScrollButton,
  expectedComposerGap,
  expectedKeyboardInset,
  summarizeUserAgent,
  type Verdict,
} from './evaluate';
import {
  appRect,
  composerBottom,
  distanceFromBottom,
  keyboardGeometry,
  keyboardInset,
  listSnapshot,
  panMeasure,
  round,
  safeAreaBottom,
  scrollPaddingTop,
  snapshotMeasurements,
  topInView,
  waitForStable,
  waitUntil,
} from './measure';

export interface DeviceCheckContext {
  container: HTMLElement;
  signal: AbortSignal;
  /** Show the big tap button; `onTap` runs inside the tap (keyboard focus) */
  askTap(label: string, onTap: () => void): Promise<void>;
  /** State one scenario leaves for the next */
  shared: { turnEl: HTMLElement | null; keyboardShown: boolean };
}

interface ScenarioOutcome {
  status: DeviceCheckStatus;
  measurements: DeviceCheckMeasurements;
  notes: string[];
}

export interface DeviceCheckScenario {
  id: string;
  title: string;
  /**
   * Skipped without one: a software keyboard on the device (not on a
   * desktop), or the keyboard actually up (an earlier step opened it)
   */
  requires: 'software-keyboard' | 'keyboard-up' | null;
  run(ctx: DeviceCheckContext): Promise<ScenarioOutcome>;
}

/** The id of the local, never-sent user message the send-to-top check adds. */
const DEVICE_CHECK_TURN_ID = 'device-check-turn';

function fromVerdict(verdict: Verdict, measurements: DeviceCheckMeasurements): ScenarioOutcome {
  return { status: verdict.status, measurements, notes: verdict.failures };
}

function composer(): HTMLTextAreaElement | null {
  const el = document.getElementById('message-input');
  return el instanceof HTMLTextAreaElement ? el : null;
}

/** Whether this device types on an on-screen keyboard (iOS, Android). */
export function hasSoftwareKeyboard(): boolean {
  const ua = navigator.userAgent;
  const iPadOs = navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1;
  return /iPhone|iPad|iPod|Android/.test(ua) || iPadOs;
}

/** The environment, also stored as the run's own environment. */
export function captureEnvironment(): DeviceCheckMeasurements {
  const g = keyboardGeometry();
  return {
    build_marker: KEYBOARD_BUILD_MARKER,
    app_version: document.getElementById('app')?.dataset.version ?? null,
    standalone: g.standalone,
    ua_summary: summarizeUserAgent(navigator.userAgent, navigator.platform, navigator.maxTouchPoints),
    software_keyboard: hasSoftwareKeyboard(),
    inner_width: window.innerWidth,
    inner_height: window.innerHeight,
    visual_viewport_height: round(g.visualViewportHeightPx),
    true_viewport_height: g.trueViewportHeightPx,
    screen_height: window.screen.height,
    safe_area_top: g.safeAreaTopPx,
    safe_area_bottom: safeAreaBottom(),
    device_pixel_ratio: window.devicePixelRatio,
  };
}

async function settleList(ctx: DeviceCheckContext): Promise<void> {
  await waitUntil(() => !isSmoothScrolling(), DEVICE_CHECK_SETTLE_TIMEOUT_MS, ctx.signal);
  await waitForStable(() => ctx.container.scrollHeight, ctx.signal);
  await waitForStable(() => ctx.container.scrollTop, ctx.signal);
}

const environment: DeviceCheckScenario = {
  id: 'environment',
  title: 'Environment',
  requires: null,
  run: () => Promise.resolve({ status: 'passed', measurements: captureEnvironment(), notes: [] }),
};

const longConversation: DeviceCheckScenario = {
  id: 'long-conversation',
  title: 'Long conversation opens at the bottom',
  requires: null,
  async run(ctx) {
    await waitUntil(() => ctx.container.querySelector('.message') !== null, DEVICE_CHECK_SETTLE_TIMEOUT_MS, ctx.signal);
    await settleList(ctx);
    const m = {
      renderedMessages: ctx.container.querySelectorAll('.message').length,
      distanceFromBottomPx: round(distanceFromBottom(ctx.container)),
      ...panMeasure(),
    };
    return fromVerdict(evaluateBottom(m), {
      rendered_messages: m.renderedMessages,
      distance_from_bottom_px: m.distanceFromBottomPx,
      scroll_height: ctx.container.scrollHeight,
      client_height: ctx.container.clientHeight,
      window_scroll_y: m.windowScrollY,
      viewport_offset_top: round(m.viewportOffsetTop),
    });
  },
};

const sendToTop: DeviceCheckScenario = {
  id: 'send-to-top',
  title: 'Send-to-top anchors the turn',
  requires: null,
  async run(ctx) {
    // The batch send's own UI steps with nothing sent: the user bubble,
    // then the loader, which anchors the turn exactly as a real send does
    addMessageToUI(
      { id: DEVICE_CHECK_TURN_ID, role: 'user', content: 'Device check: a sent message', created_at: new Date().toISOString() },
      ctx.container
    );
    const turnEl = ctx.container.lastElementChild;
    if (!(turnEl instanceof HTMLElement)) {
      return { status: 'error', measurements: {}, notes: ['the message did not render'] };
    }
    showLoadingIndicator();
    ctx.shared.turnEl = turnEl;
    await settleList(ctx);
    const offset = topInView(ctx.container, turnEl) - scrollPaddingTop(ctx.container);
    const m = { anchorOffsetPx: round(offset), anchored: isTurnAnchored(), ...panMeasure() };
    return fromVerdict(evaluateAnchor(m), {
      anchor_offset_px: m.anchorOffsetPx,
      anchored: m.anchored,
      scroll_padding_top_px: scrollPaddingTop(ctx.container),
      window_scroll_y: m.windowScrollY,
      viewport_offset_top: round(m.viewportOffsetTop),
    });
  },
};

function keyboardMeasurements(): {
  geometry: ReturnType<typeof keyboardGeometry>;
  gap: number;
  expectedGap: number;
} {
  const geometry = keyboardGeometry();
  return {
    geometry,
    gap: round(composerGap(geometry, composerBottom())),
    expectedGap: expectedComposerGap(geometry.standalone),
  };
}

/** Which anchor holds ran during the step (deltas of turn-anchor.ts's counters). */
function anchorEventDeltas(before: ReturnType<typeof turnAnchorEventCounts>): Record<string, number> {
  const after = turnAnchorEventCounts();
  return {
    holds_keyboard: after.keyboard - before.keyboard,
    holds_keyboard_delayed: after['keyboard-delayed'] - before['keyboard-delayed'],
    holds_composer: after.composer - before.composer,
    holds_resize: after.resize - before.resize,
    resize_refits: after['resize-refit'] - before['resize-refit'],
    resize_retargets: after['resize-retarget'] - before['resize-retarget'],
  };
}

/** The anchor's state after the keyboard opened: where the turn sits and why. */
function anchorAfter(container: HTMLElement, turnEl: HTMLElement | null): DeviceCheckMeasurements {
  const drift = turnAnchorDrift(container);
  const extra = turnAnchorExtra();
  return {
    anchored_after: isTurnAnchored(),
    at_anchor_after: isAtTurnAnchor(container),
    anchor_drift_px: drift === null ? null : round(drift),
    // The turn's expected top relative to the anchor line (0, or above it for a message taller than the band)
    anchor_expected_top_px: extra === null ? null : round(-extra),
    turn_from_anchor_px: turnEl ? round(topInView(container, turnEl) - scrollPaddingTop(container)) : null,
  };
}

const keyboardOpen: DeviceCheckScenario = {
  id: 'keyboard-open',
  title: 'Keyboard opens',
  requires: 'software-keyboard',
  async run(ctx) {
    const turnEl = ctx.shared.turnEl?.isConnected ? ctx.shared.turnEl : null;
    const turnBefore = turnEl ? topInView(ctx.container, turnEl) : null;
    const listBefore = listSnapshot(ctx.container);
    const eventsBefore = turnAnchorEventCounts();
    const input = composer();
    await ctx.askTap('Tap to open the keyboard', () => input?.focus());
    const shown = await waitUntil(
      () => keyboardGeometry().trueViewportHeightPx - (window.visualViewport?.height ?? 0) >= KEYBOARD_INSET_MIN_PX,
      DEVICE_CHECK_KEYBOARD_APPEAR_MS,
      ctx.signal
    );
    if (!shown) {
      return { status: 'skipped', measurements: {}, notes: ['no software keyboard appeared'] };
    }
    ctx.shared.keyboardShown = true;
    await waitForStable(keyboardInset, ctx.signal);
    await settleList(ctx);
    const { geometry, gap, expectedGap } = keyboardMeasurements();
    const anchor = anchorAfter(ctx.container, turnEl);
    const m = {
      insetPx: keyboardInset(),
      expectedInsetPx: expectedKeyboardInset(geometry),
      composerGapPx: gap,
      expectedGapPx: expectedGap,
      turnMovedPx: turnEl && turnBefore !== null ? round(topInView(ctx.container, turnEl) - turnBefore) : null,
      turnFromAnchorPx: typeof anchor.turn_from_anchor_px === 'number' ? anchor.turn_from_anchor_px : null,
      ...panMeasure(),
    };
    return fromVerdict(evaluateKeyboardOpen(m), {
      inset_px: m.insetPx,
      expected_inset_px: m.expectedInsetPx,
      composer_gap_px: m.composerGapPx,
      expected_gap_px: m.expectedGapPx,
      turn_moved_px: m.turnMovedPx,
      visual_viewport_height: round(geometry.visualViewportHeightPx),
      true_viewport_height: geometry.trueViewportHeightPx,
      safe_area_top: geometry.safeAreaTopPx,
      window_scroll_y: m.windowScrollY,
      viewport_offset_top: round(m.viewportOffsetTop),
      // Diagnostics: why a turn moved (list geometry, anchor state, holds)
      ...snapshotMeasurements(listBefore, 'before'),
      ...snapshotMeasurements(listSnapshot(ctx.container), 'after'),
      ...anchor,
      ...anchorEventDeltas(eventsBefore),
    });
  },
};

const scrollButton: DeviceCheckScenario = {
  id: 'scroll-button-keyboard',
  title: 'Scroll-to-bottom button with the keyboard up',
  requires: 'keyboard-up',
  async run(ctx) {
    ctx.container.scrollTop = 0;
    const button = document.querySelector<HTMLButtonElement>('.scroll-to-bottom');
    const buttonShown = await waitUntil(
      () => button !== null && !button.classList.contains('hidden'),
      DEVICE_CHECK_SETTLE_TIMEOUT_MS,
      ctx.signal
    );
    button?.click();
    await settleList(ctx);
    const { gap, expectedGap } = keyboardMeasurements();
    const m = {
      buttonShown,
      distanceFromBottomPx: round(distanceFromBottom(ctx.container)),
      composerGapPx: gap,
      expectedGapPx: expectedGap,
      ...panMeasure(),
    };
    return fromVerdict(evaluateScrollButton(m), {
      button_shown: buttonShown,
      distance_from_bottom_px: m.distanceFromBottomPx,
      composer_gap_px: gap,
      expected_gap_px: expectedGap,
      inset_px: keyboardInset(),
      window_scroll_y: m.windowScrollY,
      viewport_offset_top: round(m.viewportOffsetTop),
    });
  },
};

const keyboardClose: DeviceCheckScenario = {
  id: 'keyboard-close',
  title: 'Keyboard closes',
  requires: 'keyboard-up',
  async run(ctx) {
    await ctx.askTap('Tap to close the keyboard', () => composer()?.blur());
    await waitUntil(() => keyboardInset() === 0, DEVICE_CHECK_SETTLE_TIMEOUT_MS, ctx.signal);
    await waitForStable(() => appRect().height, ctx.signal);
    const app = appRect();
    const geometry = keyboardGeometry();
    const m = {
      insetPx: keyboardInset(),
      kbOpenClass: document.documentElement.classList.contains('kb-open'),
      appHeightPx: round(app.height),
      trueViewportHeightPx: geometry.trueViewportHeightPx,
      composerBottomGapPx: round(app.bottom - composerBottom()),
      ...panMeasure(),
    };
    return fromVerdict(evaluateKeyboardClose(m), {
      inset_px: m.insetPx,
      kb_open_class: m.kbOpenClass,
      app_height_px: m.appHeightPx,
      true_viewport_height: m.trueViewportHeightPx,
      composer_bottom_gap_px: m.composerBottomGapPx,
      window_scroll_y: m.windowScrollY,
      viewport_offset_top: round(m.viewportOffsetTop),
    });
  },
};

/** Why a scenario is skipped on this device right now, or null to run it. */
export function skipReason(
  requires: DeviceCheckScenario['requires'],
  softwareKeyboard: boolean,
  keyboardShown: boolean
): string | null {
  if (requires === null) return null;
  if (!softwareKeyboard) return 'no software keyboard';
  if (requires === 'keyboard-up' && !keyboardShown) return 'the keyboard did not open';
  return null;
}

/** The suite, in run order (the scroll button runs while the keyboard is still up). */
export const DEVICE_CHECK_SCENARIOS: readonly DeviceCheckScenario[] = [
  environment,
  longConversation,
  sendToTop,
  keyboardOpen,
  scrollButton,
  keyboardClose,
];
