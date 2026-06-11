/**
 * Low-level HTTP machinery for the API client: ApiError, auth token lookup,
 * timeout/retry policy and the request helpers every domain module uses.
 */

import {
  API_DEFAULT_TIMEOUT_MS,
  API_CHAT_TIMEOUT_MS,
  API_MAX_RETRIES,
  API_RETRY_INITIAL_DELAY_MS,
  API_RETRY_MAX_DELAY_MS,
  API_RETRY_JITTER_FACTOR,
  API_RETRYABLE_STATUS_CODES,
  STORAGE_KEY_APP_STATE,
  STORAGE_KEY_LEGACY_TOKEN,
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

export { ApiError, getToken, request, requestWithRetry, requestWithProgress };
