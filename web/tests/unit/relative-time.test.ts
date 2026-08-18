/**
 * Unit tests for relative-time formatting and date grouping.
 */
import { describe, it, expect } from 'vitest';
import { formatRelativeTime, groupForDate } from '@/utils/relative-time';

const NOW = new Date('2026-08-18T12:00:00Z');

describe('formatRelativeTime', () => {
  it.each([
    ['2026-08-18T11:59:40Z', 'now'],
    ['2026-08-18T11:55:00Z', '5m'],
    ['2026-08-18T09:00:00Z', '3h'],
    ['2026-08-16T12:00:00Z', '2d'],
    ['2026-07-28T12:00:00Z', '3w'],
    ['2026-04-18T12:00:00Z', '4mo'],
    ['2025-08-01T12:00:00Z', '1y'],
  ])('%s -> %s', (iso, expected) => {
    expect(formatRelativeTime(iso, NOW)).toBe(expected);
  });
});

describe('groupForDate', () => {
  it.each([
    // Wide margins to stay timezone-safe
    ['2026-08-18T11:00:00Z', 'Today'],
    ['2026-08-17T10:00:00Z', 'Yesterday'],
    ['2026-08-13T12:00:00Z', 'Previous 7 days'],
    ['2026-07-25T12:00:00Z', 'Previous 30 days'],
    ['2026-01-01T12:00:00Z', 'Older'],
  ])('%s -> %s', (iso, expected) => {
    expect(groupForDate(iso, NOW)).toBe(expected);
  });
});
