/**
 * Startup timing reports (see core/startup/boot-timing.ts).
 */
import type { components } from '../types/api';
import { request } from './http';

export type ClientTimingReport = components['schemas']['ClientTimingReport'];

export const clientTiming = {
  async report(body: ClientTimingReport): Promise<void> {
    await request<null>('/api/client-timing', { method: 'POST', body: JSON.stringify(body) });
  },
};
