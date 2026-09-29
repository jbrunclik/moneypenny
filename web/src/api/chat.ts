/**
 * Chat API: streaming (SSE) and batch sends, stream resume.
 */
import {
  type ChatResponse,
  type ClientLocation,
  type ErrorResponse,
  type FileUpload,
  type StreamEvent,
} from '../types/api';
import { API_CHAT_CONNECT_TIMEOUT_MS, API_CHAT_TIMEOUT_MS } from '../config';
import { createLogger } from '../utils/logger';
import { ApiError, getToken, request, requestWithProgress, fetchWithConnectTimeout } from './http';
import { readSseEvents } from './sse';

const log = createLogger('api');

// Chat endpoints
export const chat = {
  async sendBatch(
    conversationId: string,
    message: string,
    files?: FileUpload[],
    forceTools?: string[],
    onUploadProgress?: (progress: number) => void,
    anonymousMode?: boolean,
    clientLocation?: ClientLocation | null,
    clientMessageId?: string,
    rerunMode?: 'regenerate' | 'continue'
  ): Promise<ChatResponse> {
    // POST - no auto-retry here; the caller retries explicitly and the
    // client_message_id makes that idempotent (server dedupes with 409)
    const url = `/api/conversations/${conversationId}/chat/batch`;
    const body = {
      message,
      files,
      force_tools: forceTools?.length ? forceTools : undefined,
      anonymous_mode: anonymousMode ?? false,
      client_location: clientLocation ?? undefined,
      client_message_id: clientMessageId,
      rerun_mode: rerunMode,
    };

    // Use XHR with progress callback when files are attached
    if (files && files.length > 0 && onUploadProgress) {
      return requestWithProgress<ChatResponse>(url, body, {
        timeout: API_CHAT_TIMEOUT_MS,
        onUploadProgress,
      });
    }

    // Use standard fetch for requests without files
    return request<ChatResponse>(url, {
      method: 'POST',
      timeout: API_CHAT_TIMEOUT_MS,
      body: JSON.stringify(body),
    });
  },

  async *stream(
    conversationId: string,
    message: string,
    files?: FileUpload[],
    forceTools?: string[],
    abortController?: AbortController,
    anonymousMode?: boolean,
    clientLocation?: ClientLocation | null,
    clientMessageId?: string,
    rerunMode?: 'regenerate' | 'continue'
  ): AsyncGenerator<StreamEvent> {
    log.debug('Starting stream', { conversationId, messageLength: message.length, fileCount: files?.length ?? 0 });
    const token = getToken();

    // Use provided controller or create new one for timeout
    const controller = abortController || new AbortController();
    // The initial POST must respond within the connect timeout even when the
    // caller owns the controller - otherwise a request that hangs before the
    // first byte (dead network, dropped connection) never surfaces an error.
    // A user-provided controller previously disabled ALL timeouts here.
    let connectTimedOut = false;
    const connectTimeoutMs = abortController ? API_CHAT_CONNECT_TIMEOUT_MS : API_CHAT_TIMEOUT_MS;
    const fetchTimeoutId = setTimeout(() => {
      connectTimedOut = true;
      controller.abort();
    }, connectTimeoutMs);

    let response: Response;
    try {
      response = await fetch(
        `/api/conversations/${conversationId}/chat/stream`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            message,
            files,
            force_tools: forceTools?.length ? forceTools : undefined,
            anonymous_mode: anonymousMode ?? false,
            client_location: clientLocation ?? undefined,
            client_message_id: clientMessageId,
            rerun_mode: rerunMode,
          }),
          signal: controller.signal,
        }
      );
      clearTimeout(fetchTimeoutId);
    } catch (error) {
      clearTimeout(fetchTimeoutId);
      if (error instanceof Error && error.name === 'AbortError') {
        // User-initiated abort (via the provided controller) - re-throw as AbortError
        if (abortController && !connectTimedOut) {
          throw error;
        }
        // Otherwise the connect timer fired
        throw new ApiError(
          'Request timed out before streaming started.',
          0,
          { code: 'TIMEOUT', retryable: true, isTimeout: true }
        );
      }
      // Classify connection failures like request() does so callers can
      // distinguish network errors from application errors. fetch rejects
      // with a TypeError whose message is engine-specific ("Failed to fetch"
      // in Chromium, "Load failed" in WebKit) - never match on the message.
      if (error instanceof TypeError) {
        throw new ApiError(
          'Network error. Please check your connection.',
          0,
          { code: 'NETWORK_ERROR', retryable: true, isNetworkError: true }
        );
      }
      throw error;
    }

    if (!response.ok) {
      const data = (await response.json()) as ErrorResponse;
      const errorMsg = typeof data.error === 'string' ? data.error : data.error?.message || 'Stream request failed';
      throw new ApiError(errorMsg, response.status);
    }

    yield* readSseEvents(response, conversationId);
  },

  /**
   * Resume an interrupted chat stream from the server-side event journal.
   * Replays events with seq > afterSeq, continues live, ends with done.
   */
  async *resumeStream(
    conversationId: string,
    messageId: string,
    afterSeq: number,
    abortController?: AbortController
  ): AsyncGenerator<StreamEvent> {
    log.info('Resuming stream', { conversationId, messageId, afterSeq });
    const token = getToken();
    const controller = abortController || new AbortController();

    // Connect timeout: a resume GET that hangs before the first byte would
    // otherwise stall the whole recovery loop forever (per-read timeouts in
    // readSseEvents only start once headers arrive)
    const response = await fetchWithConnectTimeout(
      `/api/conversations/${conversationId}/chat/stream/${messageId}/resume?after_seq=${afterSeq}`,
      {
        method: 'GET',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      },
      API_CHAT_CONNECT_TIMEOUT_MS,
      controller
    );

    if (!response.ok) {
      throw new ApiError(`Resume failed (${response.status})`, response.status);
    }

    yield* readSseEvents(response, conversationId);
  },
};
