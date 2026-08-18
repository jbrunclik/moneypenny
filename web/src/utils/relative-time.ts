/**
 * Relative-time formatting and date grouping for the conversation list.
 */

const MINUTE_MS = 60_000;
const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;

/**
 * Compact relative time: "now", "5m", "3h", "2d", "3w", "4mo", "1y".
 */
export function formatRelativeTime(iso: string, now: Date = new Date()): string {
  const diff = now.getTime() - new Date(iso).getTime();
  if (diff < MINUTE_MS) return 'now';
  if (diff < HOUR_MS) return `${Math.floor(diff / MINUTE_MS)}m`;
  if (diff < DAY_MS) return `${Math.floor(diff / HOUR_MS)}h`;
  if (diff < 7 * DAY_MS) return `${Math.floor(diff / DAY_MS)}d`;
  if (diff < 30 * DAY_MS) return `${Math.floor(diff / (7 * DAY_MS))}w`;
  if (diff < 365 * DAY_MS) return `${Math.floor(diff / (30 * DAY_MS))}mo`;
  return `${Math.floor(diff / (365 * DAY_MS))}y`;
}

/**
 * Date-group label for sidebar sections (local-time day boundaries).
 */
export function groupForDate(iso: string, now: Date = new Date()): string {
  const date = new Date(iso);
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfYesterday = new Date(startOfToday.getTime() - DAY_MS);
  if (date >= startOfToday) return 'Today';
  if (date >= startOfYesterday) return 'Yesterday';
  if (date >= new Date(startOfToday.getTime() - 7 * DAY_MS)) return 'Previous 7 days';
  if (date >= new Date(startOfToday.getTime() - 30 * DAY_MS)) return 'Previous 30 days';
  return 'Older';
}
