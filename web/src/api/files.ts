/**
 * Files API: uploads, file fetches, and thumbnail polling.
 */
import {
  API_DEFAULT_TIMEOUT_MS,
  THUMBNAIL_POLL_INITIAL_DELAY_MS,
  THUMBNAIL_POLL_MAX_DELAY_MS,
  THUMBNAIL_POLL_MAX_ATTEMPTS,
} from '../config';
import { createLogger } from '../utils/logger';
import { ApiError, getToken, fetchWithConnectTimeout } from './http';

const log = createLogger('api');

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
      // Per-attempt connect timeout - a single hung request would otherwise
      // freeze the poll loop (the attempt counter never advances)
      const response = await fetchWithConnectTimeout(
        `/api/messages/${messageId}/files/${fileIndex}/thumbnail`,
        {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        },
        API_DEFAULT_TIMEOUT_MS
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
    // Connect timeout only - large file bodies may legitimately take longer
    const response = await fetchWithConnectTimeout(
      `/api/messages/${messageId}/files/${fileIndex}`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      },
      API_DEFAULT_TIMEOUT_MS
    );

    if (!response.ok) {
      throw new ApiError('Failed to fetch file', response.status);
    }

    return response.blob();
  },
};
