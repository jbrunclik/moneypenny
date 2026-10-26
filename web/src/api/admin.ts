/**
 * Admin page and spend status API (S12).
 */
import type {
  AdminOverview,
  DeviceCheckFixture,
  DeviceCheckRun,
  DeviceCheckRunRequest,
  SpendStatus,
} from '../types/api';
import { request, requestWithRetry } from './http';

export const admin = {
  /** Everything the admin page shows (403 for non-admins). */
  async getOverview(): Promise<AdminOverview> {
    return requestWithRetry<AdminOverview>('/api/admin/overview');
  },

  /** The signed-in user's spend today against the warning threshold. */
  async getSpendStatus(): Promise<SpendStatus> {
    return requestWithRetry<SpendStatus>('/api/users/me/spend-status');
  },

  /** Device check runs, newest first. */
  async listDeviceCheckRuns(limit = 20): Promise<DeviceCheckRun[]> {
    const body = await requestWithRetry<{ runs: DeviceCheckRun[] }>(`/api/admin/device-check-runs?limit=${limit}`);
    return body.runs;
  },

  /** Store a finished device check run. */
  async saveDeviceCheckRun(run: DeviceCheckRunRequest): Promise<DeviceCheckRun> {
    return request<DeviceCheckRun>('/api/admin/device-check-runs', {
      method: 'POST',
      body: JSON.stringify(run),
    });
  },

  /** A fresh fixture conversation (a crashed run's leftover is purged first). */
  async createDeviceCheckFixture(): Promise<DeviceCheckFixture> {
    return request<DeviceCheckFixture>('/api/admin/device-check-fixture', { method: 'POST' });
  },

  /** Permanently delete the fixture conversations. */
  async deleteDeviceCheckFixture(): Promise<void> {
    await request<null>('/api/admin/device-check-fixture', { method: 'DELETE', retry: true });
  },
};
