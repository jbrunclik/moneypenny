/**
 * Jobs: the one list of everything that runs on a schedule - items set from
 * chats and standing jobs (agents) - and the standing chat editor's CRUD,
 * runs and approvals. Pause, resume and cancel live in api/schedules.ts (a
 * job is a scheduled item).
 */
import type {
  CreateJobRequest,
  JobConversationSyncResponse,
  JobDetail,
  JobRunsListResponse,
  JobsOverviewResponse,
  RunJobResponse,
  UpdateJobRequest,
} from '../types/api';
import { request, requestWithRetry } from './http';

export const jobs = {
  /** Every job, needs attention first, with recent runs and next run. */
  async overview(): Promise<JobsOverviewResponse> {
    return requestWithRetry<JobsOverviewResponse>('/api/jobs');
  },

  /** A new standing chat with its job. */
  async create(data: CreateJobRequest): Promise<JobDetail> {
    return request<JobDetail>('/api/jobs', { method: 'POST', body: JSON.stringify(data) });
  },

  /** A standing chat and its job, as the editor shows it. */
  async get(jobId: string): Promise<JobDetail> {
    return requestWithRetry<JobDetail>(`/api/jobs/${jobId}`);
  },

  /** Change a standing chat: only the fields sent change. */
  async update(jobId: string, data: UpdateJobRequest): Promise<JobDetail> {
    return request<JobDetail>(`/api/jobs/${jobId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
      retry: true,
    });
  },

  /** Delete a standing chat with its job, runs and notes. */
  async delete(jobId: string): Promise<void> {
    await request<{ status: string }>(`/api/jobs/${jobId}`, { method: 'DELETE', retry: true });
  },

  /** Run a standing chat's job now. */
  async run(jobId: string): Promise<RunJobResponse> {
    return request<RunJobResponse>(`/api/jobs/${jobId}/run`, { method: 'POST' });
  },

  /** The user opened the standing chat: its messages so far are read. */
  async markViewed(jobId: string): Promise<void> {
    await request<{ status: string }>(`/api/jobs/${jobId}/viewed`, { method: 'POST' });
  },

  /** A standing job's recent runs. */
  async runs(jobId: string): Promise<JobRunsListResponse> {
    return requestWithRetry<JobRunsListResponse>(`/api/jobs/${jobId}/runs`);
  },

  /** The standing chat's message count and updated_at, for live sync. */
  async syncConversation(jobId: string): Promise<JobConversationSyncResponse> {
    return requestWithRetry<JobConversationSyncResponse>(`/api/jobs/${jobId}/conversation/sync`);
  },

  /** Approve a run's request: once, or always for that tool. */
  async approveRequest(approvalId: string, always: boolean = false): Promise<void> {
    await request<{ status: string }>(`/api/approvals/${approvalId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ always }),
    });
  },

  /** Reject a run's request. */
  async rejectRequest(approvalId: string): Promise<void> {
    await request<{ status: string }>(`/api/approvals/${approvalId}/reject`, { method: 'POST' });
  },
};
