/**
 * Jobs: the one list of everything that runs on a schedule - items set from
 * chats and standing jobs (agents). Pause, resume, run and cancel live in
 * api/schedules.ts (a job is a scheduled item).
 */
import type { JobsOverviewResponse } from '../types/api';
import { requestWithRetry } from './http';

export const jobs = {
  /** Every job, needs attention first, with recent runs and next run. */
  async overview(): Promise<JobsOverviewResponse> {
    return requestWithRetry<JobsOverviewResponse>('/api/jobs');
  },
};
