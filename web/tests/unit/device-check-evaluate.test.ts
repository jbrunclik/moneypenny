/**
 * Device check verdicts with fake measurements: every threshold the runner
 * reports against, on both sides of its tolerance.
 */
import { describe, expect, it } from 'vitest';
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
} from '@/core/device-checks/evaluate';
import { skipReason } from '@/core/device-checks/scenarios';
import { summarize } from '@/core/device-checks/runner';

const noPan = { windowScrollY: 0, viewportOffsetTop: 0 };

// Device-verified geometry (docs/ui/mobile-and-pwa.md): iPhone, iOS 26
const standaloneKeyboard = { trueViewportHeightPx: 874, visualViewportHeightPx: 471, safeAreaTopPx: 62, standalone: true };
const safariKeyboard = { trueViewportHeightPx: 654, visualViewportHeightPx: 363, safeAreaTopPx: 0, standalone: false };

describe('evaluateBottom', () => {
  it('passes at the bottom within 2px', () => {
    expect(evaluateBottom({ renderedMessages: 50, distanceFromBottomPx: 1.5, ...noPan })).toEqual({
      status: 'passed',
      failures: [],
    });
  });

  it('fails above the bottom, with the distance', () => {
    const v = evaluateBottom({ renderedMessages: 50, distanceFromBottomPx: 40, ...noPan });
    expect(v.status).toBe('failed');
    expect(v.failures).toEqual(['ended 40px above the bottom']);
  });

  it('fails on a stranded window pan or an empty list', () => {
    const v = evaluateBottom({ renderedMessages: 0, distanceFromBottomPx: 0, windowScrollY: 291, viewportOffsetTop: 0 });
    expect(v.failures).toEqual(['no messages rendered', 'window scrolled by 291px']);
  });
});

describe('evaluateAnchor', () => {
  it('passes on the anchor within 3px', () => {
    expect(evaluateAnchor({ anchorOffsetPx: -2.5, anchored: true, ...noPan }).status).toBe('passed');
  });

  it('says how far and which way the turn missed', () => {
    expect(evaluateAnchor({ anchorOffsetPx: 9, anchored: true, ...noPan }).failures).toEqual([
      'turn 9px below the anchor',
    ]);
    expect(evaluateAnchor({ anchorOffsetPx: -12, anchored: false, ...noPan }).failures).toEqual([
      'the app does not report the turn as anchored',
      'turn 12px above the anchor',
    ]);
  });
});

describe('keyboard formula', () => {
  it('matches the device-verified insets', () => {
    expect(expectedKeyboardInset(standaloneKeyboard)).toBe(341 + 50);
    expect(expectedKeyboardInset(safariKeyboard)).toBe(291);
  });

  it('is 0 at rest and for small shrinks (browser chrome)', () => {
    expect(expectedKeyboardInset({ ...standaloneKeyboard, visualViewportHeightPx: 812 })).toBe(0);
    expect(expectedKeyboardInset({ ...safariKeyboard, visualViewportHeightPx: 600 })).toBe(0);
  });

  it('puts the composer the accessory pill above the keyboard in standalone, flush in a tab', () => {
    // standalone: app bottom 874 - 391 = 483, keyboard top 471 + 62 = 533
    expect(composerGap(standaloneKeyboard, 483)).toBe(expectedComposerGap(true));
    expect(composerGap(safariKeyboard, 363)).toBe(expectedComposerGap(false));
  });
});

describe('evaluateKeyboardOpen', () => {
  const good = {
    insetPx: 391,
    expectedInsetPx: 391,
    composerGapPx: 50,
    expectedGapPx: 50,
    turnMovedPx: 0,
    ...noPan,
  };

  it('passes on the formula, the pill gap and a turn that stayed', () => {
    expect(evaluateKeyboardOpen(good).status).toBe('passed');
    expect(evaluateKeyboardOpen({ ...good, turnMovedPx: null, composerGapPx: 45 }).status).toBe('passed');
  });

  it('fails a stale inset, a hidden composer, a pan and a moved turn', () => {
    const v = evaluateKeyboardOpen({
      ...good,
      insetPx: 341,
      composerGapPx: 38,
      viewportOffsetTop: 341,
      turnMovedPx: -120,
    });
    expect(v.failures).toEqual([
      'inset 341px, the formula gives 391px',
      'composer 12px behind the keyboard',
      'visual viewport panned by 341px',
      'anchored turn moved -120px',
    ]);
  });

  it('fails an inset that never appeared, and a gap above the composer', () => {
    const v = evaluateKeyboardOpen({ ...good, insetPx: 0, composerGapPx: 70 });
    expect(v.failures).toEqual([
      'keyboard inset stayed 0',
      'inset 0px, the formula gives 391px',
      '20px gap between the composer and the keyboard',
    ]);
  });
});

describe('evaluateScrollButton', () => {
  const good = { buttonShown: true, distanceFromBottomPx: 0, composerGapPx: 0, expectedGapPx: 0, ...noPan };

  it('passes at the bottom with the composer on the keyboard', () => {
    expect(evaluateScrollButton(good).status).toBe('passed');
  });

  it('fails a hidden button or a short landing', () => {
    expect(evaluateScrollButton({ ...good, buttonShown: false, distanceFromBottomPx: 220 }).failures).toEqual([
      'the button did not show after scrolling away',
      'ended 220px above the bottom',
    ]);
  });
});

describe('evaluateKeyboardClose', () => {
  const good = {
    insetPx: 0,
    kbOpenClass: false,
    appHeightPx: 874,
    trueViewportHeightPx: 874,
    composerBottomGapPx: 0,
    ...noPan,
  };

  it('passes when the layout is back to full height', () => {
    expect(evaluateKeyboardClose(good).status).toBe('passed');
  });

  it('fails a stuck inset, a short app and a dead band', () => {
    const v = evaluateKeyboardClose({ ...good, insetPx: 391, kbOpenClass: true, appHeightPx: 483, composerBottomGapPx: 34 });
    expect(v.failures).toEqual([
      'keyboard inset stuck at 391px',
      'kb-open is still set',
      'app 483px tall in a 874px viewport',
      '34px band under the composer',
    ]);
  });
});

describe('summarizeUserAgent', () => {
  it('reads iOS Safari from its Version (the OS token is frozen at 18.6 on iOS 26)', () => {
    const ua =
      'Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.1 Mobile/15E148 Safari/604.1';
    expect(summarizeUserAgent(ua)).toBe('iOS 26.1 · Safari 26.1');
  });

  it('reads the standalone PWA (no Version/) as WebKit', () => {
    const ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148';
    expect(summarizeUserAgent(ua)).toBe('iOS 18.6 · WebKit');
  });

  it('reads desktop browsers and iPadOS', () => {
    const chrome =
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
    expect(summarizeUserAgent(chrome)).toBe('macOS · Chrome 141');
    const ipad = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15';
    expect(summarizeUserAgent(ipad, 'MacIntel', 5)).toBe('iPadOS · Safari 26.0');
    expect(summarizeUserAgent('Mozilla/5.0 (Linux; Android 15) Chrome/140.0 Mobile')).toBe('Android 15 · Chrome 140');
  });
});

describe('skipReason', () => {
  it('runs everything without requirements', () => {
    expect(skipReason(null, false, false)).toBeNull();
  });

  it('skips keyboard steps without a software keyboard', () => {
    expect(skipReason('software-keyboard', false, false)).toBe('no software keyboard');
    expect(skipReason('keyboard-up', false, false)).toBe('no software keyboard');
  });

  it('skips keyboard-up steps when the keyboard never opened', () => {
    expect(skipReason('software-keyboard', true, false)).toBeNull();
    expect(skipReason('keyboard-up', true, false)).toBe('the keyboard did not open');
    expect(skipReason('keyboard-up', true, true)).toBeNull();
  });
});

describe('summarize', () => {
  it('counts an error as failed, like the server', () => {
    const r = (status: 'passed' | 'failed' | 'skipped' | 'error') => ({
      id: status,
      title: status,
      status,
      duration_ms: 1,
      measurements: {},
      notes: [],
    });
    expect(summarize([r('passed'), r('error'), r('failed'), r('skipped')])).toEqual({
      passed: 1,
      failed: 2,
      skipped: 1,
    });
  });
});
