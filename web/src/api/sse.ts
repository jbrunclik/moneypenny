/**
 * SSE event reader for chat streaming responses.
 *
 * Wraps the response body reader with a per-read timeout so a silently
 * dropped connection cannot hang the client forever.
 */

import { API_STREAM_READ_TIMEOUT_MS } from '../config';
import type { StreamEvent } from '../types/api';
import { createLogger } from '../utils/logger';
import { ApiError } from './http';

const log = createLogger('api');

export async function* readSseEvents(
  response: Response,
  conversationId: string
): AsyncGenerator<StreamEvent> {
    const maybeReader = response.body?.getReader();
    if (!maybeReader) {
      throw new Error('No response body');
    }
    // Capture in const to satisfy TypeScript's type narrowing in closures
    const reader = maybeReader;

    const decoder = new TextDecoder();
    let buffer = '';

    /**
     * Read with timeout - wraps reader.read() with a per-read timeout.
     * This prevents hanging indefinitely if the connection drops silently.
     * Uses a flag to prevent race conditions between timeout and successful read.
     */
    async function readWithTimeout(): Promise<ReadableStreamReadResult<Uint8Array>> {
      return new Promise((resolve, reject) => {
        let settled = false;

        const timeoutId = setTimeout(() => {
          if (!settled) {
            settled = true;
            reader.cancel().catch(() => {}); // Cancel the reader on timeout
            reject(new ApiError(
              'Stream read timed out. The connection may have been lost.',
              0,
              // Use 'TIMEOUT' for consistency with other timeout errors
              { code: 'TIMEOUT', retryable: false, isTimeout: true }
            ));
          }
        }, API_STREAM_READ_TIMEOUT_MS);

        reader.read().then(
          (result) => {
            if (!settled) {
              settled = true;
              clearTimeout(timeoutId);
              resolve(result);
            }
          },
          (error) => {
            if (!settled) {
              settled = true;
              clearTimeout(timeoutId);
              reject(error);
            }
          }
        );
      });
    }

    try {
      while (true) {
        const { done, value } = await readWithTimeout();

        if (value) {
          buffer += decoder.decode(value, { stream: !done });
        }

        // Process all complete lines in the buffer
        const lines = buffer.split('\n');
        // Keep the last incomplete line in the buffer (unless stream is done)
        buffer = done ? '' : (lines.pop() || '');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            try {
              yield JSON.parse(data) as StreamEvent;
            } catch {
              // Ignore invalid JSON
            }
          }
        }

        if (done) break;
      }
    } catch (error) {
      // Handle user-initiated abort - re-throw so caller can handle cleanup
      if (error instanceof Error && error.name === 'AbortError') {
        log.debug('Stream aborted by user', { conversationId });
        throw error;
      }
      // Yield an error event for all ApiErrors for consistency with SSE error handling
      if (error instanceof ApiError) {
        yield {
          type: 'error',
          message: error.message,
          code: error.code,
          retryable: error.retryable,
        } as StreamEvent;
      }
      throw error;
    }
}
