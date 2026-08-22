/**
 * Unit tests for lightbox pinch-gesture math (pure helpers; the pointer
 * wiring is exercised on-device - jsdom has no real gesture support).
 */
import { describe, it, expect } from 'vitest';
import { computePinchScale, pointerDistance, pointerMidpoint } from '@/components/lightbox-gestures';
import { LIGHTBOX_ZOOM_MAX_SCALE } from '@/config';

describe('pointerDistance', () => {
  it('computes euclidean distance', () => {
    expect(pointerDistance({ x: 0, y: 0 }, { x: 3, y: 4 })).toBe(5);
  });
});

describe('pointerMidpoint', () => {
  it('computes the midpoint', () => {
    expect(pointerMidpoint({ x: 0, y: 0 }, { x: 10, y: 20 })).toEqual({ x: 5, y: 10 });
  });
});

describe('computePinchScale', () => {
  it('scales proportionally to the distance ratio', () => {
    expect(computePinchScale(1, 100, 200)).toBe(2);
    expect(computePinchScale(2, 100, 150)).toBe(3);
  });

  it('clamps to the configured maximum', () => {
    expect(computePinchScale(1, 50, 5000)).toBe(LIGHTBOX_ZOOM_MAX_SCALE);
  });

  it('never goes below 1 (fit-to-screen)', () => {
    expect(computePinchScale(2, 200, 50)).toBe(1);
  });

  it('ignores degenerate zero start distance', () => {
    expect(computePinchScale(2, 0, 100)).toBe(2);
  });
});
