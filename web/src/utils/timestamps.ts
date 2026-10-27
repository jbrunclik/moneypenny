/**
 * Compare ISO timestamps as instants, never as strings.
 *
 * The server sends instants in UTC with an offset ("...+00:00", since Oct 27
 * 2026) and optimistic entries created here use toISOString() ("...Z"). Data
 * cached before then can still hold the old LOCAL-naive strings without an
 * offset ("2026-10-26T12:34:56.123456"); as text those line up with the
 * others only in UTC, so a string comparison is off by the UTC offset.
 *
 * Assumption: a string WITHOUT an offset is such a legacy local-naive value,
 * read as browser-local time - browser and server share the household
 * timezone.
 */

// date, optional time (T or space), optional fraction, optional Z/±hh:mm
const ISO_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?)?(Z|[+-]\d{2}:?\d{2})?$/i;

const MS_PER_MINUTE = 60_000;

/** Offset suffix ("Z", "+01:00", "-0430") in minutes east of UTC. */
function offsetMinutes(suffix: string): number {
  if (suffix.toUpperCase() === 'Z') return 0;
  const digits = suffix.slice(1).replace(':', '');
  const minutes = Number(digits.slice(0, 2)) * 60 + Number(digits.slice(2));
  return suffix.startsWith('-') ? -minutes : minutes;
}

/**
 * Milliseconds since the epoch, keeping sub-millisecond digits (server
 * microseconds) as a fraction. NaN for an unparseable string.
 */
export function toMillis(iso: string): number {
  const match = ISO_PATTERN.exec(iso.trim());
  if (!match) return NaN;
  const [, y, mo, d, h = '0', mi = '0', s = '0', fraction = '', suffix] = match;
  const parts = [Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s)] as const;
  if (parts[1] > 11 || parts[2] < 1 || parts[2] > 31 || parts[3] > 23 || parts[4] > 59 || parts[5] > 59) {
    return NaN;
  }
  const fractionMs = fraction ? Number(`0.${fraction}`) * 1000 : 0;
  const wholeMs =
    suffix === undefined
      ? new Date(...parts).getTime()
      : Date.UTC(...parts) - offsetMinutes(suffix) * MS_PER_MINUTE;
  return wholeMs + fractionMs;
}

/**
 * Sort comparator for ISO timestamps: negative when `a` is earlier.
 * An unparseable timestamp sorts as the oldest; two of them compare equal.
 */
export function compareTimestamps(a: string, b: string): number {
  const ma = toMillis(a);
  const mb = toMillis(b);
  const aBad = Number.isNaN(ma);
  const bBad = Number.isNaN(mb);
  if (aBad || bBad) return Number(bBad) - Number(aBad);
  return Math.sign(ma - mb);
}
