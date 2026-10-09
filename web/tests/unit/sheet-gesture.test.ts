/**
 * Unit tests for bottom-sheet swipe-to-dismiss math (pure helpers; the
 * pointer wiring is exercised on-device - jsdom has no real gestures).
 */
import { describe, it, expect } from 'vitest';
import { sheetDragOffset, shouldDismissSheet } from '@/utils/sheet-gesture';

describe('sheetDragOffset', () => {
  it('follows the finger downward', () => {
    expect(sheetDragOffset(120)).toBe(120);
  });

  it('resists upward drags instead of lifting the sheet off its edge', () => {
    const up = sheetDragOffset(-100);
    expect(up).toBeLessThan(0);
    expect(up).toBeGreaterThan(-30);
  });
});

describe('shouldDismissSheet', () => {
  const height = 400;

  it('dismisses past ~a third of the height', () => {
    expect(shouldDismissSheet(130, 0.1, height)).toBe(true);
    expect(shouldDismissSheet(100, 0.1, height)).toBe(false);
  });

  it('dismisses on a fast downward flick even when short', () => {
    expect(shouldDismissSheet(60, 0.9, height)).toBe(true);
  });

  it('never dismisses on a tap-sized movement, however fast', () => {
    expect(shouldDismissSheet(10, 2, height)).toBe(false);
  });

  it('never dismisses on an upward flick', () => {
    expect(shouldDismissSheet(-80, -1.5, height)).toBe(false);
  });
});
