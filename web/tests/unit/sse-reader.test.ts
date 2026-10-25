/**
 * SSE reader for chat streams: splits `data:` lines across arbitrary chunk
 * boundaries, skips junk, and times out a silently dropped connection.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { API_STREAM_READ_TIMEOUT_MS } from '@/config';
import { ApiError } from '@/api/http';
import { readSseEvents } from '@/api/sse';
import type { StreamEvent } from '@/types/api';

const encoder = new TextEncoder();

/** A Response whose body yields the given chunks (strings or raw bytes). */
function responseOf(chunks: (string | Uint8Array)[]): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(typeof chunk === 'string' ? encoder.encode(chunk) : chunk);
      }
      controller.close();
    },
  });
  return new Response(body);
}

async function collect(response: Response): Promise<StreamEvent[]> {
  const events: StreamEvent[] = [];
  for await (const event of readSseEvents(response, 'conv-1')) {
    events.push(event);
  }
  return events;
}

const line = (event: object) => `data: ${JSON.stringify(event)}\n\n`;

describe('readSseEvents', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('yields each data line as a parsed event', async () => {
    const events = await collect(
      responseOf([line({ type: 'token', text: 'Hel' }) + line({ type: 'token', text: 'lo' })])
    );
    expect(events).toEqual([
      { type: 'token', text: 'Hel' },
      { type: 'token', text: 'lo' },
    ]);
  });

  it('reassembles an event split across chunks', async () => {
    const full = line({ type: 'token', text: 'split here' });
    const events = await collect(responseOf([full.slice(0, 9), full.slice(9, 20), full.slice(20)]));
    expect(events).toEqual([{ type: 'token', text: 'split here' }]);
  });

  it('decodes a multi-byte character split across chunks', async () => {
    const bytes = encoder.encode(line({ type: 'token', text: 'cena 5 €' }));
    const cut = bytes.indexOf(0xe2) + 1; // inside the 3-byte euro sign
    const events = await collect(responseOf([bytes.slice(0, cut), bytes.slice(cut)]));
    expect(events).toEqual([{ type: 'token', text: 'cena 5 €' }]);
  });

  it('parses a final line that has no trailing newline', async () => {
    const events = await collect(responseOf(['data: {"type":"done"}']));
    expect(events).toEqual([{ type: 'done' }]);
  });

  it('skips non-data lines and invalid JSON', async () => {
    const events = await collect(
      responseOf([': keepalive\n', 'event: ping\n', 'data: {not json\n', line({ type: 'done' })])
    );
    expect(events).toEqual([{ type: 'done' }]);
  });

  it('throws when the response has no body', async () => {
    await expect(collect(new Response(null))).rejects.toThrow('No response body');
  });

  it('times out a read that never completes and cancels the reader', async () => {
    vi.useFakeTimers();
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({ cancel }); // never enqueues
    const pending = collect(new Response(body));
    const assertion = expect(pending).rejects.toSatisfy(
      (error) => error instanceof ApiError && error.isTimeout === true
    );
    await vi.advanceTimersByTimeAsync(API_STREAM_READ_TIMEOUT_MS + 1);
    await assertion;
    expect(cancel).toHaveBeenCalled();
  });

  it('rethrows a user abort as is', async () => {
    const abort = new DOMException('aborted', 'AbortError');
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        controller.error(abort);
      },
    });
    await expect(collect(new Response(body))).rejects.toBe(abort);
  });
});
