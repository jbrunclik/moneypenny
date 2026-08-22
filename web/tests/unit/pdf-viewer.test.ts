/**
 * Unit tests for PDF viewer helpers (pure math - rendering itself is
 * covered by E2E where a real canvas exists).
 */
import { describe, it, expect } from 'vitest';
import { computeFitWidthScale, clampPageCount } from '@/components/pdf-viewer-utils';

describe('computeFitWidthScale', () => {
  it('scales a page to fill the container width', () => {
    expect(computeFitWidthScale(1000, 500)).toBe(2);
    expect(computeFitWidthScale(300, 600)).toBe(0.5);
  });

  it('caps the scale so huge containers do not explode canvas memory', () => {
    expect(computeFitWidthScale(10000, 100)).toBeLessThanOrEqual(4);
  });

  it('never returns a non-positive scale', () => {
    expect(computeFitWidthScale(0, 500)).toBeGreaterThan(0);
    expect(computeFitWidthScale(500, 0)).toBeGreaterThan(0);
  });
});

describe('clampPageCount', () => {
  it('passes small documents through', () => {
    expect(clampPageCount(12)).toEqual({ pages: 12, truncated: false });
  });

  it('caps very long documents and reports truncation', () => {
    const result = clampPageCount(500);
    expect(result.pages).toBeLessThan(500);
    expect(result.truncated).toBe(true);
  });
});
