/**
 * Viewport measurements for the keyboard pinning and the layout and device
 * checks: the true viewport height, standalone display, the top safe area
 * and the keyboard inset.
 */
import {
  KEYBOARD_DEFINITE_SHRINK_PX,
  KEYBOARD_INSET_MIN_PX,
  KEYBOARD_STANDALONE_ACCESSORY_PX,
} from '../../config';
import { isEditableElement } from './touch-guard';

/**
 * The real usable viewport height. Every native measure lies in exactly
 * one environment (observed on device, Aug 2026):
 * - Safari browser: innerHeight is truthful (654 with chrome expanded);
 *   100vh lies (largest viewport, 743).
 * - Standalone PWA (black-translucent): 100vh is truthful (874, the full
 *   webview); innerHeight lies (874 minus the status bar = 812), leaving
 *   a permanent dead band at the bottom when trusted.
 * So: standalone reads a 100vh probe; browsers read innerHeight.
 */
export function trueViewportHeight(): number {
  if (!isStandaloneDisplay()) return window.innerHeight;
  let probe = document.getElementById('vh-probe');
  if (!probe) {
    probe = document.createElement('div');
    probe.id = 'vh-probe';
    probe.style.cssText =
      'position:fixed;top:0;left:0;width:1px;height:100vh;visibility:hidden;pointer-events:none;';
    document.body.appendChild(probe);
  }
  return probe.offsetHeight || window.innerHeight;
}

export function isStandaloneDisplay(): boolean {
  return (
    (navigator as Navigator & { standalone?: boolean }).standalone === true ||
    (typeof window.matchMedia === 'function' &&
      window.matchMedia('(display-mode: standalone)').matches)
  );
}

/** Resolved env(safe-area-inset-top) in px, via a probe element. */
export function safeAreaTop(): number {
  let probe = document.getElementById('sat-probe');
  if (!probe) {
    probe = document.createElement('div');
    probe.id = 'sat-probe';
    probe.style.cssText =
      'position:fixed;visibility:hidden;pointer-events:none;' +
      'height:env(safe-area-inset-top,0px);width:1px;';
    document.body.appendChild(probe);
  }
  return probe.offsetHeight;
}

/**
 * The keyboard's extent and whether it counts as one (see update below).
 * Exported for the layout checks, which compare it with the applied inset.
 */
export function measureKeyboardInset(viewport: VisualViewport): {
  shrink: number;
  keyboardLikely: boolean;
  inset: number;
} {
  // Pinch zoom also shrinks the visual viewport - never treat it as a
  // keyboard. Same for shrinks with no editable element focused
  // (rotations, browser chrome show/hide).
  // The overlap deliberately does NOT include viewport.offsetTop: pan
  // position churns per pixel while the user drags (welcome screen has
  // no inner scroll container, so drags pan the visual viewport), and an
  // offsetTop-dependent inset reflows the whole page mid-gesture - the
  // "extremely laggy scrolling with keyboard open" bug. Keyboard
  // GEOMETRY (the height terms below) is stable during pans; the
  // focus-pan itself is handled by the stale-pan recovery further down.
  // Keyboard extent - ONE formula for every environment, using only
  // measures that are stable per-state (device-verified across all six
  // captured states, Aug 2026): innerHeight is NOT among them - in
  // standalone it oscillates between 471 and 812 while the keyboard is
  // open (non-atomic resize), which made any innerHeight-based inset
  // flap and collapse the layout mid-focus (keyboard vanished).
  //   trueViewportHeight() - visualViewport.height - safeAreaTop()
  // - standalone keyboard: 874 - 471 - 62 = 341  (both captures)
  // - standalone rest (settled/pre-settle): 874-874-62 / 874-812-62 -> 0
  // - Safari keyboard: 654 - 363 - 0 = 291 (saT is 0 in browser tabs)
  // - Safari rest: 0
  const shrink = Math.max(
    0,
    Math.round(trueViewportHeight() - viewport.height - safeAreaTop())
  );
  // Editable-focused is the normal signal, but iOS can fire the resize
  // BEFORE focus lands - a shrink this large is unambiguously a keyboard
  // regardless (browser chrome is far smaller), and missing it leaves
  // the composer hidden behind the keyboard
  const keyboardLikely =
    viewport.scale === 1 &&
    (isEditableElement(document.activeElement) || shrink >= KEYBOARD_DEFINITE_SHRINK_PX);
  const overlap = keyboardLikely ? shrink : 0;
  // Standalone: the visual viewport excludes only the keyboard - iOS's
  // floating input-assistant pill hovers over page content unreported
  // and would cover the composer's bottom edge (Safari tabs exclude it)
  const accessory =
    overlap > 0 && isStandaloneDisplay() ? KEYBOARD_STANDALONE_ACCESSORY_PX : 0;
  const inset = overlap >= KEYBOARD_INSET_MIN_PX ? overlap + accessory : 0;
  return { shrink, keyboardLikely, inset };
}
