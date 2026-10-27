/**
 * Viewport measurements (core/keyboard/metrics.ts): the true viewport
 * height per environment, standalone detection, and when a visual-viewport
 * shrink counts as a keyboard and how big an inset it gets.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  appliedKeyboardInset,
  composerGap,
  expectedComposerGap,
  isStandaloneDisplay,
  keyboardInsetFor,
  measureKeyboardInset,
  trueViewportHeight,
  windowScrollY,
} from '@/core/keyboard/metrics';
import {
  KEYBOARD_DEFINITE_SHRINK_PX,
  KEYBOARD_INSET_MIN_PX,
  KEYBOARD_STANDALONE_ACCESSORY_PX,
} from '@/config';

const INNER_HEIGHT = 800;

function viewport(height: number, scale = 1): VisualViewport {
  return { height, scale } as VisualViewport;
}

function setStandalone(standalone: boolean): void {
  Object.defineProperty(navigator, 'standalone', { value: standalone, configurable: true });
}

function focusTextarea(): void {
  const textarea = document.createElement('textarea');
  document.body.appendChild(textarea);
  textarea.focus();
}

describe('keyboard metrics', () => {
  beforeEach(() => {
    document.body.replaceChildren();
    vi.stubGlobal('innerHeight', INNER_HEIGHT);
    setStandalone(false);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setStandalone(false);
  });

  it('detects a standalone (home-screen) display', () => {
    expect(isStandaloneDisplay()).toBe(false);
    setStandalone(true);
    expect(isStandaloneDisplay()).toBe(true);
  });

  it('reads innerHeight in a browser tab, a 100vh probe when standalone', () => {
    expect(trueViewportHeight()).toBe(INNER_HEIGHT);
    expect(document.getElementById('vh-probe')).toBeNull();

    setStandalone(true);
    // jsdom lays nothing out: the probe reads 0 and falls back to innerHeight
    expect(trueViewportHeight()).toBe(INNER_HEIGHT);
    expect(document.getElementById('vh-probe')).not.toBeNull();
  });

  it('a shrink with an editable focused is the keyboard', () => {
    focusTextarea();
    expect(measureKeyboardInset(viewport(INNER_HEIGHT - 300))).toEqual({ shrink: 300, keyboardLikely: true, inset: 300 });
  });

  it('adds the input-assistant pill when standalone', () => {
    setStandalone(true);
    focusTextarea();
    expect(measureKeyboardInset(viewport(INNER_HEIGHT - 300)).inset).toBe(300 + KEYBOARD_STANDALONE_ACCESSORY_PX);
  });

  it('ignores shrinks below the minimum (browser chrome)', () => {
    focusTextarea();
    expect(measureKeyboardInset(viewport(INNER_HEIGHT - (KEYBOARD_INSET_MIN_PX - 1))).inset).toBe(0);
  });

  it('ignores pinch zoom', () => {
    focusTextarea();
    expect(measureKeyboardInset(viewport(INNER_HEIGHT - 300, 2))).toMatchObject({ keyboardLikely: false, inset: 0 });
  });

  it('without focus only a definite shrink counts (the resize can precede focus)', () => {
    const small = KEYBOARD_DEFINITE_SHRINK_PX - 10;
    expect(measureKeyboardInset(viewport(INNER_HEIGHT - small))).toMatchObject({ keyboardLikely: false, inset: 0 });
    expect(measureKeyboardInset(viewport(INNER_HEIGHT - 300))).toMatchObject({ keyboardLikely: true, inset: 300 });
  });
});

// Device-verified geometry (docs/ui/mobile-and-pwa.md): iPhone, iOS 26
const standaloneKeyboard = {
  trueViewportHeightPx: 874,
  visualViewportHeightPx: 471,
  visualViewportOffsetTopPx: 0,
  safeAreaTopPx: 62,
  standalone: true,
};
const safariKeyboard = {
  trueViewportHeightPx: 654,
  visualViewportHeightPx: 363,
  visualViewportOffsetTopPx: 0,
  safeAreaTopPx: 0,
  standalone: false,
};

describe('the keyboard model both layout checkers share', () => {
  it('gives the device-verified insets', () => {
    expect(keyboardInsetFor(standaloneKeyboard)).toBe(341 + KEYBOARD_STANDALONE_ACCESSORY_PX);
    expect(keyboardInsetFor(safariKeyboard)).toBe(291);
  });

  it('is 0 at rest and for small shrinks (browser chrome)', () => {
    expect(keyboardInsetFor({ ...standaloneKeyboard, visualViewportHeightPx: 812 })).toBe(0);
    expect(keyboardInsetFor({ ...safariKeyboard, visualViewportHeightPx: 600 })).toBe(0);
  });

  it('puts the composer the accessory pill above the keyboard in standalone, flush in a tab', () => {
    // standalone: app bottom 874 - 391 = 483, keyboard top 471 + 62 = 533
    expect(composerGap(standaloneKeyboard, 483)).toBe(expectedComposerGap(true));
    expect(composerGap(safariKeyboard, 363)).toBe(expectedComposerGap(false));
  });

  it('reads a pinned standalone composer as pinned (the Oct 2026 false overlaps)', () => {
    // A production report: the field check, leaving out the top safe area,
    // saw this as a 62px overlap; the composer sat exactly on the pill
    const reported = { ...standaloneKeyboard, trueViewportHeightPx: 874, visualViewportHeightPx: 478 };
    expect(composerGap(reported, 490)).toBe(expectedComposerGap(true));
  });

  it('counts the visual viewport pan into the keyboard top', () => {
    const panned = { ...safariKeyboard, visualViewportOffsetTopPx: 40 };
    expect(composerGap(panned, 403)).toBe(0);
  });
});

describe('reads', () => {
  afterEach(() => {
    document.documentElement.style.removeProperty('--keyboard-inset');
  });

  it('reads the inset keyboard-viewport.ts writes on <html>', () => {
    expect(appliedKeyboardInset()).toBe(0);
    document.documentElement.style.setProperty('--keyboard-inset', '391px');
    expect(appliedKeyboardInset()).toBe(391);
  });

  it('reads the window scroll', () => {
    expect(windowScrollY()).toBe(0);
  });
});
