/**
 * Timestamps compare as instants, not strings: the server sends local-naive
 * ISO strings for conversation data while the client creates optimistic ones
 * with toISOString() ("...Z"), and the two only line up as text in UTC.
 * Pinned to the household timezone so the tests mean the same on any machine.
 */
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { compareTimestamps, toMillis } from '@/utils/timestamps';

const originalTz = process.env.TZ;
beforeAll(() => {
  process.env.TZ = 'Europe/Prague';
});
afterAll(() => {
  process.env.TZ = originalTz;
});

describe('toMillis', () => {
  it('parses a UTC "Z" string as UTC', () => {
    expect(toMillis('2026-10-26T11:00:00.000Z')).toBe(Date.UTC(2026, 9, 26, 11, 0, 0));
  });

  it('parses an explicit offset', () => {
    expect(toMillis('2026-10-26T12:00:00+01:00')).toBe(Date.UTC(2026, 9, 26, 11, 0, 0));
    expect(toMillis('2026-10-26T06:30:00-04:30')).toBe(Date.UTC(2026, 9, 26, 11, 0, 0));
  });

  it('parses a server local-naive string as local time', () => {
    // Winter time (CET, UTC+1) and summer time (CEST, UTC+2)
    expect(toMillis('2026-10-26T12:00:00')).toBe(Date.UTC(2026, 9, 26, 11, 0, 0));
    expect(toMillis('2026-07-01T12:00:00')).toBe(Date.UTC(2026, 6, 1, 10, 0, 0));
  });

  it('keeps microseconds as a fraction of a millisecond', () => {
    expect(toMillis('2026-10-26T12:00:00.123456')).toBeCloseTo(Date.UTC(2026, 9, 26, 11, 0, 0) + 123.456, 3);
    expect(toMillis('2026-10-26T12:00:00.5')).toBe(Date.UTC(2026, 9, 26, 11, 0, 0) + 500);
  });

  it('accepts the space separator of str(datetime)', () => {
    expect(toMillis('2026-10-26 12:00:00')).toBe(toMillis('2026-10-26T12:00:00'));
  });

  it('returns NaN for an unparseable string', () => {
    expect(toMillis('')).toBeNaN();
    expect(toMillis('not a date')).toBeNaN();
    expect(toMillis('2026-13-45T99:00:00')).toBeNaN();
  });
});

describe('compareTimestamps', () => {
  it('orders a "Z" string against local-naive ones by instant, not text', () => {
    // 11:30Z is 12:30 Prague: after 12:00 local, although "11:30Z" < "12:00" as text
    expect(compareTimestamps('2026-10-26T11:30:00.000Z', '2026-10-26T12:00:00')).toBeGreaterThan(0);
    expect(compareTimestamps('2026-10-26T12:00:00', '2026-10-26T11:30:00.000Z')).toBeLessThan(0);
    expect(compareTimestamps('2026-10-26T11:00:00.000Z', '2026-10-26T12:00:00')).toBe(0);
  });

  it('orders microseconds against milliseconds', () => {
    expect(compareTimestamps('2026-10-26T12:00:00.123456', '2026-10-26T12:00:00.123')).toBeGreaterThan(0);
    expect(compareTimestamps('2026-10-26T12:00:00.123', '2026-10-26T12:00:00.123000')).toBe(0);
    expect(compareTimestamps('2026-10-26T12:00:00.1234', '2026-10-26T12:00:00.1235')).toBeLessThan(0);
  });

  it('orders across the spring-forward gap and the fall-back hour', () => {
    // Mar 29 2026: 02:00 CET jumps to 03:00 CEST - 01:59 local is 00:59Z, 03:00 local is 01:00Z
    expect(compareTimestamps('2026-03-29T01:59:00', '2026-03-29T03:00:00')).toBeLessThan(0);
    expect(toMillis('2026-03-29T03:00:00') - toMillis('2026-03-29T01:59:00')).toBe(60_000);
    // Oct 25 2026: 03:00 CEST falls back to 02:00 CET - 03:30 local (CET) is 02:30Z
    expect(compareTimestamps('2026-10-25T03:30:00', '2026-10-25T02:15:00.000Z')).toBeGreaterThan(0);
    expect(toMillis('2026-10-25T03:30:00')).toBe(Date.UTC(2026, 9, 25, 2, 30, 0));
  });

  it('sorts an invalid timestamp as the oldest, and two invalid ones as equal', () => {
    expect(compareTimestamps('garbage', '1970-01-01T00:00:00Z')).toBeLessThan(0);
    expect(compareTimestamps('2026-10-26T12:00:00', '')).toBeGreaterThan(0);
    expect(compareTimestamps('garbage', '')).toBe(0);
  });

  it('works as a sort comparator over mixed formats', () => {
    const sorted = ['2026-10-26T12:30:00', '2026-10-26T11:00:00.000Z', 'bad', '2026-10-26T11:45:00'].sort(
      compareTimestamps
    );
    expect(sorted).toEqual(['bad', '2026-10-26T11:45:00', '2026-10-26T11:00:00.000Z', '2026-10-26T12:30:00']);
  });
});
