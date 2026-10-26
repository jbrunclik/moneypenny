/**
 * Viewport measurements (core/keyboard/metrics.ts): the true viewport
 * height per environment, standalone detection, and when a visual-viewport
 * shrink counts as a keyboard and how big an inset it gets.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { isStandaloneDisplay, measureKeyboardInset, trueViewportHeight } from '@/core/keyboard/metrics';
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
