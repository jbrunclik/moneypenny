/**
 * App-level API: available models, upload config, deployed version.
 */
import { type ModelsResponse, type UploadConfig, type VersionResponse } from '../types/api';
import { API_DEFAULT_TIMEOUT_MS } from '../config';
import { requestWithRetry, fetchWithConnectTimeout } from './http';

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

// Version endpoint (no auth required)
export const version = {
  async get(): Promise<VersionResponse> {
    const response = await fetchWithConnectTimeout('/api/version', {}, API_DEFAULT_TIMEOUT_MS);
    return response.json() as Promise<VersionResponse>;
  },
};
