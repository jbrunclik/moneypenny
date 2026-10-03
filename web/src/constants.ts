/**
 * True constants - unit conversions and mathematical constants.
 *
 * These are fundamental constants that should never need to be changed.
 * For developer-configurable values, see config.ts.
 *
 * Guidelines:
 * - Only include truly immutable values (unit conversions)
 * - Use SCREAMING_SNAKE_CASE for constant names
 * - Include units in the constant name (e.g., _MS, _BYTES)
 */

// =============================================================================
// Time Constants (Base Units)
// =============================================================================

/** Milliseconds in one second */
export const MS_PER_SECOND = 1000;

/** Milliseconds in one minute */
export const MS_PER_MINUTE = 60 * MS_PER_SECOND;

/** Milliseconds in one hour */
export const MS_PER_HOUR = 60 * MS_PER_MINUTE;

/** Milliseconds in one day */
export const MS_PER_DAY = 24 * MS_PER_HOUR;

// =============================================================================
// Size Constants (Base Units)
// =============================================================================

/** Bytes in one kilobyte */
export const BYTES_PER_KB = 1024;

/** Bytes in one megabyte */
export const BYTES_PER_MB = 1024 * BYTES_PER_KB;
