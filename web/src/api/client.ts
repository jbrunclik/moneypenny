import {
  PaginationDirection,
  type AuthResponse,
  type ChatResponse,
  type Conversation,
  type ConversationDetailResponse,
  type ConversationsResponse,
  type ConversationsPagination,
  type CostHistoryResponse,
  type ConversationCostResponse,
  type ErrorResponse,
  type FileUpload,
  type MemoriesResponse,
  type Memory,
  type Message,
  type MessageCostResponse,
  type MessagesResponse,
  type MessagesPagination,
  type MonthlyCostResponse,
  type ModelsResponse,
  type PlannerConversation,
  type PlannerDashboard,
  type PlannerResetResponse,
  type PlannerSyncResponse,
  type SearchResponse,
  type StreamEvent,
  type SyncResponse,
  type TodoistAuthUrl,
  type TodoistConnectResponse,
  type TodoistStatus,
  type CalendarAuthUrl,
  type CalendarConnectResponse,
  type CalendarListResponse,
  type CalendarStatus,
  type SelectedCalendarsResponse,
  type UploadConfig,
  type User,
  type UserSettings,
  type VersionResponse,
} from '../types/api';
import {
  API_DEFAULT_TIMEOUT_MS,
  API_CHAT_TIMEOUT_MS,
  API_STREAM_READ_TIMEOUT_MS,
  API_MAX_RETRIES,
  API_RETRY_INITIAL_DELAY_MS,
  API_RETRY_MAX_DELAY_MS,
  API_RETRY_JITTER_FACTOR,
  API_RETRYABLE_STATUS_CODES,
  STORAGE_KEY_APP_STATE,
  STORAGE_KEY_LEGACY_TOKEN,
  THUMBNAIL_POLL_INITIAL_DELAY_MS,
  THUMBNAIL_POLL_MAX_DELAY_MS,
  THUMBNAIL_POLL_MAX_ATTEMPTS,
} from '../config';
import { createLogger } from '../utils/logger';

const log = createLogger('api');

/**
 * Extended API error with additional metadata for error handling.
 */
class ApiError extends Error {
  /** HTTP status code */
  status: number;
  /** Error code from backend (e.g., 'TIMEOUT', 'AUTH_REQUIRED') */
  code: string;
  /** Whether this error can be retried */
  retryable: boolean;
  /** Whether this is a timeout error */
  isTimeout: boolean;
  /** Whether this is a network error (no response) */
  isNetworkError: boolean;
  /** Whether this is an authentication error (requires re-auth) */
  isAuthError: boolean;
  /** Whether the token has expired (subset of auth errors) */
  isTokenExpired: boolean;

  constructor(
    message: string,
    status: number,
    options: {
      code?: string;
      retryable?: boolean;
      isTimeout?: boolean;
      isNetworkError?: boolean;
    } = {}
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = options.code || 'UNKNOWN';
    this.retryable = options.retryable ?? API_RETRYABLE_STATUS_CODES.includes(status);
    this.isTimeout = options.isTimeout ?? false;
    this.isNetworkError = options.isNetworkError ?? false;
    // Auth error detection based on error codes
    this.isTokenExpired = options.code === 'AUTH_EXPIRED';
    this.isAuthError = status === 401 || ['AUTH_REQUIRED', 'AUTH_INVALID', 'AUTH_EXPIRED'].includes(options.code || '');
  }
}

/**
 * Parse error response from backend and create ApiError.
 */
function parseErrorResponse(data: unknown, status: number): ApiError {
  // Handle structured error format from backend
  if (data && typeof data === 'object' && 'error' in data) {
    const err = (data as { error: { code?: string; message?: string; retryable?: boolean } }).error;
    if (typeof err === 'object' && err !== null) {
      return new ApiError(
        err.message || 'Request failed',
        status,
        {
          code: err.code,
          retryable: err.retryable,
          isTimeout: err.code === 'TIMEOUT',
        }
      );
    }
  }
  return new ApiError('Request failed', status);
}

/**
 * Create an AbortSignal that times out after the specified duration.
 */
function createTimeoutSignal(timeoutMs: number): AbortSignal {
  const controller = new AbortController();
  setTimeout(() => controller.abort(), timeoutMs);
  return controller.signal;
}

/**
 * Calculate delay for exponential backoff with jitter.
 */
function calculateRetryDelay(attempt: number): number {
  // Exponential backoff: delay * 2^attempt
  const delay = Math.min(
    API_RETRY_INITIAL_DELAY_MS * Math.pow(2, attempt),
    API_RETRY_MAX_DELAY_MS
  );
  // Add jitter to prevent thundering herd
  const jitter = delay * API_RETRY_JITTER_FACTOR * (Math.random() * 2 - 1);
  return Math.round(delay + jitter);
}

/**
 * Sleep for specified milliseconds.
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getToken(): string | null {
  // Try Zustand persisted store first
  const stored = localStorage.getItem(STORAGE_KEY_APP_STATE);
  if (stored) {
    try {
      const parsed = JSON.parse(stored);
      if (parsed.state?.token) {
        return parsed.state.token;
      }
    } catch {
      // Ignore parse errors
    }
  }
  // Fallback to legacy direct token storage
  return localStorage.getItem(STORAGE_KEY_LEGACY_TOKEN);
}

interface RequestOptions extends RequestInit {
  /** Request timeout in milliseconds */
  timeout?: number;
  /** Enable retry with exponential backoff (only for GET requests) */
  retry?: boolean;
  /** Maximum number of retries (default: 3) */
  maxRetries?: number;
}

/**
 * Make a request with timeout and optional retry support.
 */
async function request<T>(
  url: string,
  options: RequestOptions = {}
): Promise<T> {
  const {
    timeout = API_DEFAULT_TIMEOUT_MS,
    retry = false,
    maxRetries = API_MAX_RETRIES,
    ...fetchOptions
  } = options;

  const token = getToken();

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...fetchOptions.headers,
  };

  if (token) {
    (headers as Record<string, string>)['Authorization'] = `Bearer ${token}`;
  }

  // Retry logic - only enable if explicitly requested
  // Safe methods: GET (always), DELETE (idempotent), PATCH with same data (idempotent)
  // Unsafe methods: POST (creates new resources), PUT with different data
  const isRetryable = retry;
  let lastError: ApiError | null = null;
  const method = fetchOptions.method || 'GET';

  log.debug('API request', { method, url });
  const startTime = performance.now();

  for (let attempt = 0; attempt <= (isRetryable ? maxRetries : 0); attempt++) {
    try {
      // Add timeout via AbortSignal
      const signal = createTimeoutSignal(timeout);

      const response = await fetch(url, {
        ...fetchOptions,
        headers,
        signal,
      });

      let data: unknown;
      try {
        data = await response.json();
      } catch {
        // Response body was not valid JSON
        data = null;
      }

      if (!response.ok) {
        throw parseErrorResponse(data, response.status);
      }

      const duration = Math.round(performance.now() - startTime);
      log.debug('API response', { method, url, status: response.status, durationMs: duration });

      return data as T;
    } catch (error) {
      // Handle AbortError (timeout)
      if (error instanceof Error && error.name === 'AbortError') {
        lastError = new ApiError(
          'Request timed out. Please try again.',
          0,
          { code: 'TIMEOUT', retryable: true, isTimeout: true }
        );
      }
      // Handle network errors (no response)
      else if (error instanceof TypeError && error.message.includes('fetch')) {
        lastError = new ApiError(
          'Network error. Please check your connection.',
          0,
          { code: 'NETWORK_ERROR', retryable: true, isNetworkError: true }
        );
      }
      // Handle ApiError from response parsing
      else if (error instanceof ApiError) {
        lastError = error;
      }
      // Handle unknown errors
      else {
        lastError = new ApiError(
          error instanceof Error ? error.message : 'Request failed',
          0
        );
      }

      // Only retry if the error is retryable and we have attempts left
      if (isRetryable && lastError.retryable && attempt < maxRetries) {
        const delay = calculateRetryDelay(attempt);
        log.debug('Retrying request', {
          attempt: attempt + 1,
          maxRetries,
          url,
          delayMs: delay,
          error: lastError.message,
          code: lastError.code,
        });
        await sleep(delay);
        continue;
      }

      throw lastError;
    }
  }

  // Should never reach here, but TypeScript needs it
  throw lastError || new ApiError('Request failed', 0);
}

/**
 * Wrapper for GET requests with automatic retry.
 */
async function requestWithRetry<T>(
  url: string,
  options: Omit<RequestOptions, 'retry'> = {}
): Promise<T> {
  return request<T>(url, { ...options, retry: true });
}

/**
 * Options for XHR requests with upload progress support.
 */
interface XhrRequestOptions {
  /** Request timeout in milliseconds */
  timeout?: number;
  /** Callback for upload progress (0-100) */
  onUploadProgress?: (progress: number) => void;
}

/**
 * Make a POST request using XMLHttpRequest for upload progress support.
 * Used when files are attached to get upload progress feedback.
 */
function requestWithProgress<T>(
  url: string,
  body: unknown,
  options: XhrRequestOptions = {}
): Promise<T> {
  const { timeout = API_CHAT_TIMEOUT_MS, onUploadProgress } = options;
  const token = getToken();

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    xhr.setRequestHeader('Content-Type', 'application/json');
    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    }
    xhr.timeout = timeout;

    // Track upload progress
    if (onUploadProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const progress = Math.round((event.loaded / event.total) * 100);
          onUploadProgress(progress);
        }
      };
    }

    xhr.onload = () => {
      let data: unknown;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        data = null;
      }

      if (xhr.status >= 200 && xhr.status < 300) {
        log.debug('XHR response', { url, status: xhr.status });
        resolve(data as T);
      } else {
        reject(parseErrorResponse(data, xhr.status));
      }
    };

    xhr.onerror = () => {
      reject(new ApiError(
        'Network error. Please check your connection.',
        0,
        { code: 'NETWORK_ERROR', retryable: true, isNetworkError: true }
      ));
    };

    xhr.ontimeout = () => {
      reject(new ApiError(
        'Request timed out. Please try again.',
        0,
        { code: 'TIMEOUT', retryable: true, isTimeout: true }
      ));
    };

    log.debug('XHR request', { url });
    xhr.send(JSON.stringify(body));
  });
}

// Auth endpoints
export const auth = {
  async getClientId(): Promise<string> {
    const data = await requestWithRetry<{ client_id: string }>('/auth/client-id');
    return data.client_id;
  },

  async googleLogin(credential: string): Promise<AuthResponse> {
    // POST - no retry (not idempotent)
    return request<AuthResponse>('/auth/google', {
      method: 'POST',
      body: JSON.stringify({ credential }),
    });
  },

  async me(): Promise<User> {
    const data = await requestWithRetry<{ user: User }>('/auth/me');
    return data.user;
  },

  async refreshToken(): Promise<string> {
    // POST - no retry (not idempotent, creates new token)
    const data = await request<{ token: string }>('/auth/refresh', {
      method: 'POST',
    });
    return data.token;
  },
};

// Conversation endpoints
export const conversations = {
  /**
   * List conversations with pagination.
   * @param limit - Number of conversations to return
   * @param cursor - Cursor for fetching next page
   */
  async list(
    limit?: number,
    cursor?: string | null
  ): Promise<{ conversations: Conversation[]; pagination: ConversationsPagination }> {
    const params = new URLSearchParams();
    if (limit) params.set('limit', limit.toString());
    if (cursor) params.set('cursor', cursor);
    const query = params.toString();
    const data = await requestWithRetry<ConversationsResponse>(
      `/api/conversations${query ? `?${query}` : ''}`
    );
    // Map snake_case message_count to camelCase messageCount
    return {
      conversations: data.conversations.map((conv) => ({
        ...conv,
        messageCount: (conv as { message_count?: number }).message_count,
      })),
      pagination: data.pagination,
    };
  },

  /**
   * Get a conversation with paginated messages.
   * @param id - Conversation ID
   * @param messageLimit - Number of messages to return
   * @param messageCursor - Cursor for fetching older/newer messages
   * @param direction - PaginationDirection.OLDER or PaginationDirection.NEWER
   */
  async get(
    id: string,
    messageLimit?: number,
    messageCursor?: string | null,
    direction?: PaginationDirection
  ): Promise<ConversationDetailResponse> {
    const params = new URLSearchParams();
    if (messageLimit) params.set('message_limit', messageLimit.toString());
    if (messageCursor) params.set('message_cursor', messageCursor);
    if (direction) params.set('direction', direction);
    const query = params.toString();
    return requestWithRetry<ConversationDetailResponse>(
      `/api/conversations/${id}${query ? `?${query}` : ''}`
    );
  },

  /**
   * Get paginated messages for a conversation.
   * This is a dedicated endpoint, more efficient than get() when only messages are needed.
   * @param id - Conversation ID
   * @param limit - Number of messages to return
   * @param cursor - Cursor for fetching older/newer messages
   * @param direction - PaginationDirection.OLDER or PaginationDirection.NEWER
   */
  async getMessages(
    id: string,
    limit?: number,
    cursor?: string | null,
    direction?: PaginationDirection
  ): Promise<{ messages: Message[]; pagination: MessagesPagination }> {
    const params = new URLSearchParams();
    if (limit) params.set('limit', limit.toString());
    if (cursor) params.set('cursor', cursor);
    if (direction) params.set('direction', direction);
    const query = params.toString();
    return requestWithRetry<MessagesResponse>(
      `/api/conversations/${id}/messages${query ? `?${query}` : ''}`
    );
  },

  /**
   * Get messages around a specific message (for search result navigation).
   * Loads a window of messages centered on the target message, enabling
   * bi-directional pagination from that position.
   * @param id - Conversation ID
   * @param messageId - Target message ID to center around
   * @param limit - Total messages to return (split between before/after target)
   */
  async getMessagesAround(
    id: string,
    messageId: string,
    limit?: number
  ): Promise<{ messages: Message[]; pagination: MessagesPagination }> {
    const params = new URLSearchParams();
    params.set('around_message_id', messageId);
    if (limit) params.set('limit', limit.toString());
    return requestWithRetry<MessagesResponse>(
      `/api/conversations/${id}/messages?${params.toString()}`
    );
  },

  async create(model?: string): Promise<Conversation> {
    // POST - no retry (not idempotent - creates new resource)
    return request<Conversation>('/api/conversations', {
      method: 'POST',
      body: JSON.stringify({ model }),
    });
  },

  async update(
    id: string,
    data: { title?: string; model?: string }
  ): Promise<void> {
    // PATCH is idempotent (same update = same result), safe to retry
    await request<{ status: string }>(`/api/conversations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
      retry: true,
    });
  },

  async delete(id: string): Promise<void> {
    // DELETE is idempotent (deleting already deleted = same result), safe to retry
    await request<{ status: string }>(`/api/conversations/${id}`, {
      method: 'DELETE',
      retry: true,
    });
  },

  /**
   * Sync conversations with the server.
   * @param since - ISO timestamp to get conversations updated since (null for full sync)
   * @param full - Force full sync even with since parameter (for delete detection)
   */
  async sync(since: string | null, full: boolean = false): Promise<SyncResponse> {
    const params = new URLSearchParams();
    if (since) params.set('since', since);
    if (full) params.set('full', 'true');
    const query = params.toString();
    return requestWithRetry<SyncResponse>(`/api/conversations/sync${query ? `?${query}` : ''}`);
  },
};

// Message endpoints
export const messages = {
  async delete(id: string): Promise<void> {
    // DELETE is idempotent (deleting already deleted = same result), safe to retry
    await request<{ status: string }>(`/api/messages/${id}`, {
      method: 'DELETE',
      retry: true,
    });
  },
};

// Chat endpoints
export const chat = {
  async sendBatch(
    conversationId: string,
    message: string,
    files?: FileUpload[],
    forceTools?: string[],
    onUploadProgress?: (progress: number) => void,
    anonymousMode?: boolean
  ): Promise<ChatResponse> {
    // POST - no retry (not idempotent - could duplicate message)
    // Use longer timeout for chat (image generation, complex tool chains)
    const url = `/api/conversations/${conversationId}/chat/batch`;
    const body = {
      message,
      files,
      force_tools: forceTools?.length ? forceTools : undefined,
      anonymous_mode: anonymousMode ?? false,
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
    anonymousMode?: boolean
  ): AsyncGenerator<StreamEvent> {
    log.debug('Starting stream', { conversationId, messageLength: message.length, fileCount: files?.length ?? 0 });
    const token = getToken();

    // Use provided controller or create new one for timeout
    const controller = abortController || new AbortController();
    // Only set timeout if using internal controller (not user-provided)
    const fetchTimeoutId = abortController
      ? null
      : setTimeout(() => controller.abort(), API_CHAT_TIMEOUT_MS);

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
          }),
          signal: controller.signal,
        }
      );
      if (fetchTimeoutId) clearTimeout(fetchTimeoutId);
    } catch (error) {
      if (fetchTimeoutId) clearTimeout(fetchTimeoutId);
      if (error instanceof Error && error.name === 'AbortError') {
        // If user provided controller, this is a user-initiated abort - re-throw as AbortError
        if (abortController) {
          throw error;
        }
        // Otherwise it's a timeout
        throw new ApiError(
          'Request timed out before streaming started.',
          0,
          { code: 'TIMEOUT', retryable: true, isTimeout: true }
        );
      }
      throw error;
    }

    if (!response.ok) {
      const data = (await response.json()) as ErrorResponse;
      const errorMsg = typeof data.error === 'string' ? data.error : data.error?.message || 'Stream request failed';
      throw new ApiError(errorMsg, response.status);
    }

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
  },
};

// Models endpoint
export const models = {
  async list(): Promise<ModelsResponse> {
    return requestWithRetry<ModelsResponse>('/api/models');
  },
};

// Config endpoint
export const config = {
  async getUploadConfig(): Promise<UploadConfig> {
    return requestWithRetry<UploadConfig>('/api/config/upload');
  },
};

// File endpoints
export const files = {
  getThumbnailUrl(messageId: string, fileIndex: number): string {
    return `/api/messages/${messageId}/files/${fileIndex}/thumbnail`;
  },

  getFileUrl(messageId: string, fileIndex: number): string {
    return `/api/messages/${messageId}/files/${fileIndex}`;
  },

  async fetchThumbnail(messageId: string, fileIndex: number): Promise<Blob> {
    const token = getToken();
    let attempts = 0;
    let delay = THUMBNAIL_POLL_INITIAL_DELAY_MS;

    const fetchWithRetry = async (): Promise<Blob> => {
      const response = await fetch(
        `/api/messages/${messageId}/files/${fileIndex}/thumbnail`,
        {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        }
      );

      // Handle 202 Accepted - thumbnail is still being generated
      if (response.status === 202) {
        attempts++;
        if (attempts >= THUMBNAIL_POLL_MAX_ATTEMPTS) {
          log.warn('Thumbnail generation timed out after max attempts', {
            messageId,
            fileIndex,
            attempts,
          });
          throw new ApiError('Thumbnail generation timed out', 408);
        }

        log.debug('Thumbnail pending, polling...', {
          messageId,
          fileIndex,
          attempt: attempts,
          delay,
        });

        // Wait with exponential backoff
        await new Promise((resolve) => setTimeout(resolve, delay));
        delay = Math.min(delay * 2, THUMBNAIL_POLL_MAX_DELAY_MS);
        return fetchWithRetry();
      }

      if (!response.ok) {
        throw new ApiError('Failed to fetch thumbnail', response.status);
      }

      return response.blob();
    };

    return fetchWithRetry();
  },

  async fetchFile(messageId: string, fileIndex: number): Promise<Blob> {
    const token = getToken();
    const response = await fetch(
      `/api/messages/${messageId}/files/${fileIndex}`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }
    );

    if (!response.ok) {
      throw new ApiError('Failed to fetch file', response.status);
    }

    return response.blob();
  },
};

// Version endpoint (no auth required)
export const version = {
  async get(): Promise<VersionResponse> {
    const response = await fetch('/api/version');
    return response.json() as Promise<VersionResponse>;
  },
};

// Cost tracking endpoints
export const costs = {
  async getConversationCost(conversationId: string): Promise<ConversationCostResponse> {
    return requestWithRetry<ConversationCostResponse>(`/api/conversations/${conversationId}/cost`);
  },

  async getMonthlyCost(year?: number, month?: number): Promise<MonthlyCostResponse> {
    const params = new URLSearchParams();
    if (year) params.set('year', year.toString());
    if (month) params.set('month', month.toString());
    const query = params.toString();
    return requestWithRetry<MonthlyCostResponse>(`/api/users/me/costs/monthly${query ? `?${query}` : ''}`);
  },

  async getCostHistory(limit?: number): Promise<CostHistoryResponse> {
    const params = new URLSearchParams();
    if (limit) params.set('limit', limit.toString());
    const query = params.toString();
    return requestWithRetry<CostHistoryResponse>(`/api/users/me/costs/history${query ? `?${query}` : ''}`);
  },

  async getMessageCost(messageId: string): Promise<MessageCostResponse> {
    return requestWithRetry<MessageCostResponse>(`/api/messages/${messageId}/cost`);
  },
};

// Memory endpoints
export const memories = {
  async list(): Promise<Memory[]> {
    const data = await requestWithRetry<MemoriesResponse>('/api/memories');
    return data.memories;
  },

  async delete(memoryId: string): Promise<void> {
    // DELETE is idempotent, safe to retry
    await request<{ status: string }>(`/api/memories/${memoryId}`, {
      method: 'DELETE',
      retry: true,
    });
  },
};

// Settings endpoints
export const settings = {
  async get(): Promise<UserSettings> {
    return requestWithRetry<UserSettings>('/api/users/me/settings');
  },

  async update(data: Partial<UserSettings>): Promise<void> {
    // PATCH is idempotent (same update = same result), safe to retry
    await request<{ status: string }>('/api/users/me/settings', {
      method: 'PATCH',
      body: JSON.stringify(data),
      retry: true,
    });
  },
};

// Todoist integration endpoints
export const todoist = {
  /**
   * Get the Todoist OAuth authorization URL.
   * Returns a URL to redirect the user to and a state token for CSRF protection.
   */
  async getAuthUrl(): Promise<TodoistAuthUrl> {
    return requestWithRetry<TodoistAuthUrl>('/auth/todoist/auth-url');
  },

  /**
   * Exchange Todoist OAuth code for access token and connect the account.
   * @param code - The authorization code from Todoist callback
   * @param state - The state token for CSRF validation (client should verify this)
   */
  async connect(code: string, state: string): Promise<TodoistConnectResponse> {
    return request<TodoistConnectResponse>('/auth/todoist/connect', {
      method: 'POST',
      body: JSON.stringify({ code, state }),
    });
  },

  /**
   * Disconnect the user's Todoist account.
   */
  async disconnect(): Promise<void> {
    await request<{ status: string }>('/auth/todoist/disconnect', {
      method: 'POST',
    });
  },

  /**
   * Get the current Todoist connection status.
   */
  async getStatus(): Promise<TodoistStatus> {
    return requestWithRetry<TodoistStatus>('/auth/todoist/status');
  },
};

// Google Calendar integration endpoints
export const calendar = {
  async getAuthUrl(): Promise<CalendarAuthUrl> {
    return requestWithRetry<CalendarAuthUrl>('/auth/calendar/auth-url');
  },

  async connect(code: string, state: string): Promise<CalendarConnectResponse> {
    return request<CalendarConnectResponse>('/auth/calendar/connect', {
      method: 'POST',
      body: JSON.stringify({ code, state }),
    });
  },

  async disconnect(): Promise<void> {
    await request<{ status: string }>('/auth/calendar/disconnect', {
      method: 'POST',
    });
  },

  async getStatus(): Promise<CalendarStatus> {
    return requestWithRetry<CalendarStatus>('/auth/calendar/status');
  },

  async listCalendars(): Promise<CalendarListResponse> {
    return requestWithRetry<CalendarListResponse>('/auth/calendar/calendars');
  },

  async getSelectedCalendars(): Promise<SelectedCalendarsResponse> {
    return requestWithRetry<SelectedCalendarsResponse>('/auth/calendar/selected-calendars');
  },

  async updateSelectedCalendars(calendarIds: string[]): Promise<SelectedCalendarsResponse> {
    return request<SelectedCalendarsResponse>('/auth/calendar/selected-calendars', {
      method: 'PUT',
      body: JSON.stringify({ calendar_ids: calendarIds }),
    });
  },
};

// Search endpoints
export const search = {
  /**
   * Search across all conversations and messages.
   *
   * @param query - Search query string
   * @param limit - Maximum results to return (default: 20, max: 50)
   * @param offset - Number of results to skip for pagination
   * @returns Search results with conversation info and message snippets
   */
  async query(query: string, limit: number = 20, offset: number = 0): Promise<SearchResponse> {
    const params = new URLSearchParams({
      q: query,
      limit: String(limit),
      offset: String(offset),
    });
    return requestWithRetry<SearchResponse>(`/api/search?${params}`);
  },
};

// Planner endpoints
export const planner = {
  /**
   * Get the planner dashboard with events and tasks for the next 7 days.
   * Includes overdue tasks and integration connection status.
   * @param forceRefresh If true, bypasses cache and fetches fresh data
   */
  async getDashboard(forceRefresh: boolean = false): Promise<PlannerDashboard> {
    const url = forceRefresh ? '/api/planner?force_refresh=true' : '/api/planner';
    return requestWithRetry<PlannerDashboard>(url);
  },

  /**
   * Get or create the user's planner conversation.
   * If a reset is due (after 4am), messages will be cleared automatically.
   * @returns The planner conversation with messages and was_reset flag
   */
  async getConversation(): Promise<PlannerConversation> {
    return requestWithRetry<PlannerConversation>('/api/planner/conversation');
  },

  /**
   * Reset the planner conversation (clear all messages).
   * Physically deletes messages but preserves cost data for accuracy.
   */
  async reset(): Promise<PlannerResetResponse> {
    return request<PlannerResetResponse>('/api/planner/reset', {
      method: 'POST',
    });
  },

  /**
   * Get planner conversation state for real-time synchronization.
   * Returns conversation metadata (message count, last reset) to detect
   * external updates, resets, or deletion in other tabs/devices.
   */
  async sync(): Promise<PlannerSyncResponse> {
    return requestWithRetry<PlannerSyncResponse>('/api/planner/sync');
  },
};

export { ApiError };
