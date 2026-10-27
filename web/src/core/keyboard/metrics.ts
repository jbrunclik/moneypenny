/**
 * Viewport measurements for the keyboard pinning and the two layout checkers
 * - the field telemetry (core/layout-checks.ts) and the on-device runner
 * (core/device-checks/) - so all three read the same numbers and judge them
 * by one model: the true viewport height, standalone display, the top safe
 * area, the keyboard inset (the formula and the applied value), the window
 * pan and the composer's gap to the keyboard.
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
function safeAreaTop(): number {
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

/** The viewport geometry the keyboard formula reads (docs/ui/mobile-and-pwa.md). */
export interface KeyboardGeometry {
  trueViewportHeightPx: number;
  visualViewportHeightPx: number;
  /** The visual viewport's pan below the layout viewport's top (0 at rest) */
  visualViewportOffsetTopPx: number;
  safeAreaTopPx: number;
  standalone: boolean;
}

export function keyboardGeometry(viewport: VisualViewport | null = window.visualViewport): KeyboardGeometry {
  return {
    trueViewportHeightPx: trueViewportHeight(),
    visualViewportHeightPx: viewport?.height ?? window.innerHeight,
    visualViewportOffsetTopPx: viewport?.offsetTop ?? 0,
    safeAreaTopPx: safeAreaTop(),
    standalone: isStandaloneDisplay(),
  };
}

/** How far the visual viewport is shorter than the true viewport, beyond the top safe area. */
function keyboardShrink(g: KeyboardGeometry): number {
  return Math.max(0, Math.round(g.trueViewportHeightPx - g.visualViewportHeightPx - g.safeAreaTopPx));
}

/**
 * The inset for a keyboard of this geometry (0 below KEYBOARD_INSET_MIN_PX);
 * standalone adds the input-assistant pill's allowance. Pure: the device
 * checks recompute it from measured numbers.
 */
export function keyboardInsetFor(g: KeyboardGeometry): number {
  const shrink = keyboardShrink(g);
  if (shrink < KEYBOARD_INSET_MIN_PX) return 0;
  return shrink + (g.standalone ? KEYBOARD_STANDALONE_ACCESSORY_PX : 0);
}

/**
 * The space between the composer's bottom and the keyboard's top, in layout
 * px: the keyboard's top is the visual viewport's bottom - its pan plus its
 * height - lowered by the top safe area, which the visual viewport leaves
 * out in standalone (0 in browser tabs). Positive: a band above the
 * keyboard; negative: the composer under it.
 */
export function composerGap(g: KeyboardGeometry, composerBottomPx: number): number {
  return g.visualViewportOffsetTopPx + g.visualViewportHeightPx + g.safeAreaTopPx - composerBottomPx;
}

/** The gap a correctly pinned composer leaves: the pill's allowance in standalone, else 0. */
export function expectedComposerGap(standalone: boolean): number {
  return standalone ? KEYBOARD_STANDALONE_ACCESSORY_PX : 0;
}

/** The --keyboard-inset keyboard-viewport.ts applied on <html>. */
export function appliedKeyboardInset(): number {
  return parseFloat(document.documentElement.style.getPropertyValue('--keyboard-inset')) || 0;
}

/** How far the window is scrolled (iOS pans it for a caret reveal; never legitimately). */
export function windowScrollY(): number {
  return Math.max(window.scrollY, document.scrollingElement?.scrollTop ?? 0);
}

/**
 * The keyboard's extent and whether it counts as one (see update below).
 * The layout checks compare its inset with the applied one.
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
  const geometry = keyboardGeometry(viewport);
  const shrink = keyboardShrink(geometry);
  // Editable-focused is the normal signal, but iOS can fire the resize
  // BEFORE focus lands - a shrink this large is unambiguously a keyboard
  // regardless (browser chrome is far smaller), and missing it leaves
  // the composer hidden behind the keyboard
  const keyboardLikely =
    viewport.scale === 1 &&
    (isEditableElement(document.activeElement) || shrink >= KEYBOARD_DEFINITE_SHRINK_PX);
  // Standalone: the visual viewport excludes only the keyboard - iOS's
  // floating input-assistant pill hovers over page content unreported
  // and would cover the composer's bottom edge (Safari tabs exclude it);
  // keyboardInsetFor adds its allowance
  const inset = keyboardLikely ? keyboardInsetFor(geometry) : 0;
  return { shrink, keyboardLikely, inset };
}
