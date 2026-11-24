/**
 * Projects API: folders of chats with shared instructions, memory and
 * documents, and moving chats in and out of them.
 */
import {
  type BulkMoveRequest,
  type Conversation,
  type ConversationsPagination,
  type ConversationsResponse,
  type CreateProjectRequest,
  type Person,
  type Project,
  type ProjectDetail,
  type ProjectsListResponse,
  type UpdateProjectRequest,
} from '../types/api';
import { toConversation } from './conversations';
import { request, requestWithRetry } from './http';

export const projects = {
  /** The projects the user owns or was added to, and the owned-projects cap. */
  async list(): Promise<ProjectsListResponse> {
    return requestWithRetry<ProjectsListResponse>('/api/projects');
  },

  async get(projectId: string): Promise<ProjectDetail> {
    return requestWithRetry<ProjectDetail>(`/api/projects/${projectId}`);
  },

  async create(body: CreateProjectRequest): Promise<Project> {
    // POST - no retry (creates a new project)
    return request<Project>('/api/projects', { method: 'POST', body: JSON.stringify(body) });
  },

  async update(projectId: string, body: UpdateProjectRequest): Promise<Project> {
    return request<Project>(`/api/projects/${projectId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
      retry: true,
    });
  },

  async remove(projectId: string): Promise<void> {
    // DELETE is idempotent, safe to retry
    await request<{ status: string }>(`/api/projects/${projectId}`, { method: 'DELETE', retry: true });
  },

  async restore(projectId: string): Promise<void> {
    await request<{ status: string }>(`/api/projects/${projectId}/restore`, { method: 'POST' });
  },

  async deleted(): Promise<Project[]> {
    const data = await requestWithRetry<{ projects: Project[] }>('/api/projects/deleted');
    return data.projects;
  },

  /** The user's own chats in the project, a page at a time (unread counts included). */
  async conversations(
    projectId: string,
    cursor?: string | null
  ): Promise<{ conversations: Conversation[]; pagination: ConversationsPagination }> {
    const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : '';
    const data = await requestWithRetry<ConversationsResponse>(`/api/projects/${projectId}/conversations${query}`);
    return {
      conversations: data.conversations.map((conv) => toConversation(conv, true)),
      pagination: data.pagination,
    };
  },

  async addMember(projectId: string, userId: string): Promise<Project> {
    return request<Project>(`/api/projects/${projectId}/members/${userId}`, { method: 'PUT', retry: true });
  },

  /** Remove a member (owner), or leave (the member's own id). */
  async removeMember(projectId: string, userId: string): Promise<void> {
    await request<{ status: string }>(`/api/projects/${projectId}/members/${userId}`, {
      method: 'DELETE',
      retry: true,
    });
  },

  /** The family members a project can be shared with. */
  async people(): Promise<Person[]> {
    const data = await requestWithRetry<{ people: Person[] }>('/api/projects/people');
    return data.people;
  },

  /** File a chat under a project, or take it out (null). */
  async moveChat(conversationId: string, projectId: string | null): Promise<void> {
    await request<{ status: string }>(`/api/conversations/${conversationId}/project`, {
      method: 'PUT',
      body: JSON.stringify({ project_id: projectId }),
      retry: true,
    });
  },

  async bulkMove(body: BulkMoveRequest): Promise<string[]> {
    // Idempotent server-side (a moved chat moves again to the same place)
    const data = await request<{ moved_ids: string[] }>('/api/conversations/bulk-move', {
      method: 'POST',
      body: JSON.stringify(body),
      retry: true,
    });
    return data.moved_ids;
  },
};
