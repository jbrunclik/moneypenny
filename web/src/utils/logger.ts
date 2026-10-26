/**
 * Structured logging utility for the frontend.
 *
 * Provides consistent, environment-aware logging with support for:
 * - Log levels (debug, info, warn, error)
 * - Structured context fields
 * - Development-only debug logging
 * - Request ID correlation
 *
 * Usage:
 *   import { logger, createLogger } from './utils/logger';
 *
 *   // Use the default logger
 *   logger.info('User logged in', { userId: '123' });
 *   logger.error('Failed to fetch', { error, url });
 *
 *   // Create a named logger for a module
 *   const log = createLogger('auth');
 *   log.debug('Token refresh scheduled', { expiresIn: 3600 });
 */

import { LOG_LEVEL, LOG_LEVELS, type LogLevel } from '../config';

/** Context fields that can be attached to log entries */
interface LogContext {
  [key: string]: unknown;
}

/** Structure of a log entry */
interface LogEntry {
  timestamp: string;
  level: LogLevel;
  logger: string;
  message: string;
  [key: string]: unknown;
}

/** Global request ID for correlation (set per request lifecycle) */
// UI-local (F2): the request id for log correlation
let currentRequestId: string | null = null;

/**
 * Set the current request ID for log correlation.
 * Call this at the start of a request lifecycle (e.g., API call).
 */
export function setRequestId(requestId: string | null): void {
  currentRequestId = requestId;
}

/**
 * Get the current request ID.
 */
export function getRequestId(): string | null {
  return currentRequestId;
}

/**
 * Receives every error-level entry: the logger's name, the message and the
 * first Error in its context. Set by core/error-reporting (utils cannot call
 * the API itself); the context is never passed on - it can hold content.
 */
export type ErrorSink = (loggerName: string, message: string, error?: Error) => void;

// UI-local (F2): injected by startup (F1)
let errorSink: ErrorSink | null = null;

export function setErrorSink(sink: ErrorSink | null): void {
  errorSink = sink;
}

function notifyErrorSink(loggerName: string, message: string, context?: LogContext): void {
  if (!errorSink) return;
  const error = Object.values(context ?? {}).find((v): v is Error => v instanceof Error);
  try {
    errorSink(loggerName, message, error);
  } catch {
    // A broken sink must never break the caller's error handling
  }
}

/**
 * Generate a unique request ID.
 */
export function generateRequestId(): string {
  return `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}

/**
 * Check if a log level should be output based on current config.
 */
function shouldLog(level: LogLevel): boolean {
  return LOG_LEVELS[level] >= LOG_LEVELS[LOG_LEVEL];
}

/**
 * Format a log entry as a structured object.
 */
function formatLogEntry(
  level: LogLevel,
  loggerName: string,
  message: string,
  context?: LogContext
): LogEntry {
  const entry: LogEntry = {
    timestamp: new Date().toISOString(),
    level,
    logger: loggerName,
    message,
  };

  // Add request ID if available
  if (currentRequestId) {
    entry.requestId = currentRequestId;
  }

  // Add context fields
  if (context) {
    for (const [key, value] of Object.entries(context)) {
      // Handle Error objects specially
      if (value instanceof Error) {
        entry[key] = {
          name: value.name,
          message: value.message,
          stack: value.stack,
        };
      } else {
        entry[key] = value;
      }
    }
  }

  return entry;
}

/**
 * Output a log entry to the console.
 * In production, outputs structured JSON. In development, uses formatted console output.
 */
function outputLog(level: LogLevel, entry: LogEntry): void {
  const isDev = import.meta.env.DEV;

  if (isDev) {
    // In development, use colored console output for readability
    // Note: Use console.log for debug level since console.debug is often hidden by default
    const prefix = `[${entry.logger}]`;
    // Extract message and context, excluding metadata fields from rest
    const { message, ...contextWithMeta } = entry;
    // Remove metadata fields to get just the context
    const { timestamp: _, level: __, logger: ___, ...rest } = contextWithMeta;
    void _; void __; void ___; // Suppress unused variable warnings
    const hasContext = Object.keys(rest).length > 0;

    switch (level) {
      case 'debug':
        // Use console.log instead of console.debug (which is hidden by default in most browsers)
        if (hasContext) {
          console.log(`%c${prefix}`, 'color: #888', message, rest);
        } else {
          console.log(`%c${prefix}`, 'color: #888', message);
        }
        break;
      case 'info':
        if (hasContext) {
          console.log(`%c${prefix}`, 'color: #0099ff', message, rest);
        } else {
          console.log(`%c${prefix}`, 'color: #0099ff', message);
        }
        break;
      case 'warn':
        if (hasContext) {
          console.warn(prefix, message, rest);
        } else {
          console.warn(prefix, message);
        }
        break;
      case 'error':
        if (hasContext) {
          console.error(prefix, message, rest);
        } else {
          console.error(prefix, message);
        }
        break;
    }
  } else {
    // In production, output structured JSON for log aggregation
    const jsonStr = JSON.stringify(entry);
    switch (level) {
      case 'debug':
        console.debug(jsonStr);
        break;
      case 'info':
        console.info(jsonStr);
        break;
      case 'warn':
        console.warn(jsonStr);
        break;
      case 'error':
        console.error(jsonStr);
        break;
    }
  }
}

/**
 * Logger interface with methods for each log level.
 */
export interface Logger {
  /** Log debug information (development only by default) */
  debug(message: string, context?: LogContext): void;
  /** Log informational messages */
  info(message: string, context?: LogContext): void;
  /** Log warnings */
  warn(message: string, context?: LogContext): void;
  /** Log errors */
  error(message: string, context?: LogContext): void;
}

/**
 * Create a named logger instance.
 *
 * @param name - The logger name (typically the module name)
 * @returns A Logger instance
 *
 * @example
 * const log = createLogger('auth');
 * log.info('User authenticated', { userId: '123' });
 */
export function createLogger(name: string): Logger {
  return {
    debug(message: string, context?: LogContext): void {
      if (shouldLog('debug')) {
        const entry = formatLogEntry('debug', name, message, context);
        outputLog('debug', entry);
      }
    },

    info(message: string, context?: LogContext): void {
      if (shouldLog('info')) {
        const entry = formatLogEntry('info', name, message, context);
        outputLog('info', entry);
      }
    },

    warn(message: string, context?: LogContext): void {
      if (shouldLog('warn')) {
        const entry = formatLogEntry('warn', name, message, context);
        outputLog('warn', entry);
      }
    },

    error(message: string, context?: LogContext): void {
      if (shouldLog('error')) {
        const entry = formatLogEntry('error', name, message, context);
        outputLog('error', entry);
      }
      notifyErrorSink(name, message, context);
    },
  };
}

/** Default logger instance for general use */
export const logger = createLogger('app');

// Log the current log level on initialization (always visible)
if (import.meta.env.DEV) {
  console.info(`[logger] Initialized with LOG_LEVEL='${LOG_LEVEL}'`);
}