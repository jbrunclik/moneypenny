/**
 * One-shot scroll position writes that are checked on the next frame.
 *
 * iOS may ignore a `scrollTop` write while the list still coasts from a
 * flick (TODO "Scroll: iOS dropped writes"). These writes keep the reader's
 * place when content above them changes height - a prepended page, an image
 * or an artifact growing, a thinking block collapsing - so a dropped one
 * shows as a jump. This only measures (counts per source, read by the
 * device checks); it never retries, which could fight a real user scroll.
 */
import { SCROLL_WRITE_MIN_VERIFY_PX } from '../config';

export type ScrollWriteSource = 'pagination-prepend' | 'image-growth' | 'artifact-resize' | 'thinking-collapse';

interface LastWrite {
  fromPx: number;
  targetPx: number;
  actualPx: number;
  landed: boolean;
}

export interface ScrollWriteStats {
  /** Every write */
  writes: number;
  /** Writes large enough to tell a drop from the list coasting on */
  verified: number;
  dropped: number;
  /** The largest distance a dropped write ended from its target */
  maxMissPx: number;
  last: LastWrite | null;
}

const SOURCES: readonly ScrollWriteSource[] = [
  'pagination-prepend',
  'image-growth',
  'artifact-resize',
  'thinking-collapse',
];

function emptyStats(): Record<ScrollWriteSource, ScrollWriteStats> {
  return Object.fromEntries(
    SOURCES.map((source) => [source, { writes: 0, verified: 0, dropped: 0, maxMissPx: 0, last: null }])
  ) as Record<ScrollWriteSource, ScrollWriteStats>;
}

// UI-local (F2): per-page measurement counters, read by the device checks; never app state
let stats = emptyStats();

/**
 * Set `container.scrollTop` to `target` and check on the next frame whether
 * it landed: it did when the position is closer to the (reachable) target
 * than to where it was, which still holds while the list coasts on.
 */
export function writeScrollTop(container: HTMLElement, target: number, source: ScrollWriteSource): void {
  const from = container.scrollTop;
  container.scrollTop = target;
  const entry = stats[source];
  entry.writes++;
  const reachable = Math.max(0, Math.min(target, container.scrollHeight - container.clientHeight));
  if (Math.abs(reachable - from) < SCROLL_WRITE_MIN_VERIFY_PX) return;
  requestAnimationFrame(() => {
    const actual = container.scrollTop;
    const landed = Math.abs(actual - reachable) <= Math.abs(actual - from);
    entry.verified++;
    if (!landed) {
      entry.dropped++;
      entry.maxMissPx = Math.max(entry.maxMissPx, Math.round(Math.abs(actual - reachable)));
    }
    entry.last = { fromPx: Math.round(from), targetPx: Math.round(reachable), actualPx: Math.round(actual), landed };
  });
}

/** A snapshot of the counts per source (the device checks diff two of them). */
export function scrollWriteStats(): Record<ScrollWriteSource, ScrollWriteStats> {
  return structuredClone(stats);
}

export function _resetScrollWriteStats(): void {
  stats = emptyStats();
}
