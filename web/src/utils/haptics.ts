/**
 * Haptic feedback - progressive enhancement.
 *
 * Android browsers implement navigator.vibrate. iOS Safari has no vibration
 * API, but since iOS 18 WebKit fires a light system haptic when a
 * `<input type="checkbox" switch>` control is toggled VIA ITS LABEL - a
 * JS click() on the input itself stays silent, a click() on the label
 * does not. We keep one visually-hidden switch+label around and click the
 * label as an iOS fallback.
 *
 * WebKit PR #38473 (Jan 2025) gates the switch haptic on TRANSIENT USER
 * ACTIVATION: it only fires within a few seconds of a real tap/click.
 * That suits our call sites (all gesture-driven) and means async calls
 * (e.g. an error toast from a network failure) are silent on iOS - by
 * design, script alone must not buzz the device. Non-standard and being
 * phased out (reportedly patched harder in iOS 26.5): treat iOS haptics
 * as a bonus on the versions that allow it, never rely on them.
 *
 * Usage guide (keep it tasteful - haptics lose meaning when everything
 * buzzes): tick for physical-feeling UI transitions the finger caused
 * (swipe snapping open, sheet opening, copy landing), success/error for
 * outcomes the user is waiting on (quiz verdicts, failures).
 */

const TICK_MS = 10;
// Short double pulse: "it worked"
const SUCCESS_PATTERN_MS = [15, 60, 15];
// Longer triple pulse: "something went wrong" - clearly distinct from success
const ERROR_PATTERN_MS = [40, 80, 40, 80, 40];
// The iOS switch trick has no duration control - approximate patterns by
// repeating ticks with this gap
const IOS_PULSE_GAP_MS = 90;

let iosHapticLabel: HTMLLabelElement | null = null;

function iosTick(): void {
  if (typeof document === 'undefined' || !document.body) return;
  if (!iosHapticLabel || !iosHapticLabel.isConnected) {
    iosHapticLabel = document.createElement('label');
    // Visually hidden but NOT display:none - WebKit still toggles (and
    // haptics) for clipped content, not for non-rendered content
    iosHapticLabel.style.cssText =
      'position:fixed;top:0;left:0;width:1px;height:1px;overflow:hidden;' +
      'clip-path:inset(50%);pointer-events:none;opacity:0;';
    iosHapticLabel.setAttribute('aria-hidden', 'true');
    const switchInput = document.createElement('input');
    switchInput.type = 'checkbox';
    switchInput.setAttribute('switch', '');
    switchInput.tabIndex = -1;
    iosHapticLabel.appendChild(switchInput);
    document.body.appendChild(iosHapticLabel);
  }
  iosHapticLabel.click();
}

function buzz(pattern: number | number[]): void {
  if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
    try {
      navigator.vibrate(pattern);
      return;
    } catch {
      // Some browsers throw on vibrate without user activation - fall through
    }
  }
  // iOS fallback: one tick per vibration segment of the pattern
  const pulses = Array.isArray(pattern) ? Math.ceil(pattern.length / 2) : 1;
  for (let i = 0; i < pulses; i++) {
    if (i === 0) {
      iosTick();
    } else {
      setTimeout(iosTick, i * IOS_PULSE_GAP_MS);
    }
  }
}

/** A single short tick, e.g. when a swipe row snaps open. */
export function hapticTick(): void {
  buzz(TICK_MS);
}

/** Positive outcome, e.g. a correct quiz answer. */
export function hapticSuccess(): void {
  buzz(SUCCESS_PATTERN_MS);
}

/** Negative outcome, e.g. a failed send or wrong quiz answer. */
export function hapticError(): void {
  buzz(ERROR_PATTERN_MS);
}
