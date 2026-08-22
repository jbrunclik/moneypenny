/**
 * Unit tests for haptic feedback (progressive enhancement - vibrate is
 * Android-only; iOS Safari has no API and must not throw).
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { hapticTick, hapticSuccess, hapticError } from '@/utils/haptics';

describe('haptics', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('tick vibrates briefly when the API is available', () => {
    const vibrate = vi.fn();
    vi.stubGlobal('navigator', { vibrate });
    hapticTick();
    expect(vibrate).toHaveBeenCalledTimes(1);
    const ms = vibrate.mock.calls[0][0];
    expect(ms).toBeGreaterThan(0);
    expect(ms).toBeLessThanOrEqual(50);
  });

  it('success and error use distinct multi-pulse patterns', () => {
    const vibrate = vi.fn();
    vi.stubGlobal('navigator', { vibrate });
    hapticSuccess();
    hapticError();
    expect(vibrate).toHaveBeenCalledTimes(2);
    const [success] = vibrate.mock.calls[0];
    const [error] = vibrate.mock.calls[1];
    expect(Array.isArray(success)).toBe(true);
    expect(Array.isArray(error)).toBe(true);
    expect(success).not.toEqual(error);
  });

  it('falls back to the iOS switch-toggle trick when vibrate is missing', () => {
    vi.stubGlobal('navigator', {});
    const labelClick = vi.spyOn(HTMLLabelElement.prototype, 'click');
    hapticTick();
    // A hidden switch-checkbox is injected and its LABEL is clicked -
    // iOS fires the haptic only for label-driven toggles, not input.click()
    const input = document.querySelector('input[switch]');
    expect(input).not.toBeNull();
    expect(input?.closest('label')).not.toBeNull();
    expect(labelClick).toHaveBeenCalled();
  });

  it('does nothing (and does not throw) without a DOM or vibrate', () => {
    vi.stubGlobal('navigator', {});
    expect(() => hapticTick()).not.toThrow();
    expect(() => hapticSuccess()).not.toThrow();
    expect(() => hapticError()).not.toThrow();
  });
});
