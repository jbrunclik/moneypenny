/**
 * In-flight stream persistence (resume after crash/reload).
 *
 * Remembers which assistant message each conversation is currently streaming
 * so a page that dies mid-turn can replay the server's stream journal after
 * reload (see resumeInflightStreamIfAny in stream-resume.ts).
 */

// Map keyed by conversation id: conversations can stream CONCURRENTLY, so a
// single entry would be overwritten by the next stream and cleared by
// whichever stream finishes first. Entries expire client-side well within
// the server journal TTL and the map is pruned on every write/read.
const INFLIGHT_STREAMS_KEY = 'inflight-streams';
export const INFLIGHT_STREAM_MAX_AGE_MS = 30 * 60 * 1000; // journal TTL is 1h server-side

export interface InflightStream {
  messageId: string;
  ts: number;
}

function readInflightStreams(): Record<string, InflightStream> {
  try {
    const raw = localStorage.getItem(INFLIGHT_STREAMS_KEY);
    if (!raw) return {};
    const map = JSON.parse(raw) as Record<string, InflightStream>;
    const now = Date.now();
    const fresh: Record<string, InflightStream> = {};
    for (const [convId, entry] of Object.entries(map)) {
      if (entry?.messageId && now - entry.ts <= INFLIGHT_STREAM_MAX_AGE_MS) {
        fresh[convId] = entry;
      }
    }
    return fresh;
  } catch {
    return {};
  }
}

function writeInflightStreams(map: Record<string, InflightStream>): void {
  try {
    if (Object.keys(map).length === 0) {
      localStorage.removeItem(INFLIGHT_STREAMS_KEY);
    } else {
      localStorage.setItem(INFLIGHT_STREAMS_KEY, JSON.stringify(map));
    }
  } catch {
    // Quota/privacy-mode failures only cost the reload-resume nicety
  }
}

export function persistInflightStream(convId: string, messageId: string): void {
  const map = readInflightStreams();
  map[convId] = { messageId, ts: Date.now() };
  writeInflightStreams(map);
}

export function clearInflightStream(convId: string): void {
  const map = readInflightStreams();
  if (convId in map) {
    delete map[convId];
    writeInflightStreams(map);
  }
}

/** Drop every entry (logout: another account must not resume these turns). */
export function clearAllInflightStreams(): void {
  writeInflightStreams({});
}

export function readInflightStream(convId: string): InflightStream | null {
  return readInflightStreams()[convId] ?? null;
}
