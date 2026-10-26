/**
 * In-flight batch turn persistence (resume after crash/reload).
 *
 * Remembers which user message each conversation's batch turn is answering
 * so a page that dies mid-turn can wait for the reply after reload (see
 * resumeInflightBatchIfAny in batch-resume.ts).
 */

// Map keyed by conversation id: batch turns can run in several conversations
// at once. A turn older than this is not worth waiting for after a reload.
const INFLIGHT_BATCH_KEY = 'inflight-batch-turns';
export const INFLIGHT_BATCH_MAX_AGE_MS = 30 * 60 * 1000;

export interface InflightBatch {
  messageId: string;
  ts: number;
}

function readInflightBatches(): Record<string, InflightBatch> {
  try {
    const map = JSON.parse(localStorage.getItem(INFLIGHT_BATCH_KEY) || '{}') as Record<string, InflightBatch>;
    const now = Date.now();
    return Object.fromEntries(
      Object.entries(map).filter(([, e]) => e?.messageId && now - e.ts <= INFLIGHT_BATCH_MAX_AGE_MS)
    );
  } catch {
    return {};
  }
}

function writeInflightBatches(map: Record<string, InflightBatch>): void {
  try {
    if (Object.keys(map).length === 0) {
      localStorage.removeItem(INFLIGHT_BATCH_KEY);
    } else {
      localStorage.setItem(INFLIGHT_BATCH_KEY, JSON.stringify(map));
    }
  } catch {
    // Quota/privacy-mode failures only cost the reload-resume nicety
  }
}

/** Remember the user message a batch turn is answering (before the request). */
export function persistInflightBatch(convId: string, messageId: string): void {
  const map = readInflightBatches();
  map[convId] = { messageId, ts: Date.now() };
  writeInflightBatches(map);
}

/** Forget the conversation's entry (only if it is still `messageId`'s, when given). */
export function clearInflightBatch(convId: string, messageId?: string): void {
  const map = readInflightBatches();
  if (convId in map && (messageId === undefined || map[convId]?.messageId === messageId)) {
    delete map[convId];
    writeInflightBatches(map);
  }
}

/** Whether this page sent a batch turn here that has not been answered yet. */
export function hasInflightBatch(convId: string): boolean {
  return convId in readInflightBatches();
}

/** Drop every entry (logout: another account must not wait on these turns). */
export function clearAllInflightBatches(): void {
  writeInflightBatches({});
}

export function readInflightBatch(convId: string): InflightBatch | null {
  return readInflightBatches()[convId] ?? null;
}
