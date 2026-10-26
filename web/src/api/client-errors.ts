/**
 * Browser error reports (see core/error-reporting.ts).
 */
import type { components } from '../types/api';
import { request } from './http';

export type ClientErrorReport = components['schemas']['ClientErrorReport'];
export type LayoutCheckDetail = components['schemas']['ClientErrorReport.LayoutCheckDetail'];

export const clientErrors = {
  async report(body: ClientErrorReport): Promise<void> {
    await request<null>('/api/client-errors', { method: 'POST', body: JSON.stringify(body) });
  },
};
