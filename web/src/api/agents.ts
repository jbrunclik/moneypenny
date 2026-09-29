/**
 * Autonomous agents API and AI-assist helpers for the agent editor.
 */
import {
  type Agent,
  type AgentConversationSyncResponse,
  type AgentExecutionsListResponse,
  type AgentsListResponse,
  type CommandCenterResponse,
  type CreateAgentRequest,
  type EnhancePromptRequest,
  type EnhancePromptResponse,
  type ParseScheduleResponse,
  type TriggerAgentResponse,
  type UpdateAgentRequest,
} from '../types/api';
import { request, requestWithRetry } from './http';

// Autonomous agents endpoints
export const agents = {
  /**
   * List all autonomous agents for the current user.
   */
  async list(): Promise<Agent[]> {
    const data = await requestWithRetry<AgentsListResponse>('/api/agents');
    return data.agents;
  },

  /**
   * Create a new autonomous agent.
   * Automatically creates a dedicated conversation for the agent.
   */
  async create(data: CreateAgentRequest): Promise<Agent> {
    return request<Agent>('/api/agents', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  /**
   * Get a specific agent by ID.
   */
  async get(agentId: string): Promise<Agent> {
    return requestWithRetry<Agent>(`/api/agents/${agentId}`);
  },

  /**
   * Update an agent's configuration.
   */
  async update(agentId: string, data: UpdateAgentRequest): Promise<Agent> {
    return request<Agent>(`/api/agents/${agentId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
      retry: true,
    });
  },

  /**
   * Delete an agent and its dedicated conversation.
   */
  async delete(agentId: string): Promise<void> {
    await request<{ status: string }>(`/api/agents/${agentId}`, {
      method: 'DELETE',
      retry: true,
    });
  },

  /**
   * Manually trigger an agent to run.
   */
  async run(agentId: string): Promise<TriggerAgentResponse> {
    return request<TriggerAgentResponse>(`/api/agents/${agentId}/run`, {
      method: 'POST',
    });
  },

  /**
   * Mark an agent's conversation as viewed.
   * Resets the unread count for the agent.
   */
  async markViewed(agentId: string): Promise<void> {
    await request<{ status: string }>(`/api/agents/${agentId}/mark-viewed`, {
      method: 'POST',
    });
  },

  /**
   * Get execution history for an agent.
   */
  async getExecutions(agentId: string): Promise<AgentExecutionsListResponse> {
    return requestWithRetry<AgentExecutionsListResponse>(`/api/agents/${agentId}/executions`);
  },

  /**
   * Sync agent conversation - returns message count and updated_at for detecting external updates.
   */
  async syncConversation(agentId: string): Promise<AgentConversationSyncResponse> {
    return requestWithRetry<AgentConversationSyncResponse>(`/api/agents/${agentId}/conversation/sync`);
  },

  /**
   * Get command center dashboard data.
   * Includes all agents, pending approvals, and recent executions.
   */
  async getCommandCenter(): Promise<CommandCenterResponse> {
    return requestWithRetry<CommandCenterResponse>('/api/agents/command-center');
  },

  /**
   * Approve a pending approval request.
   */
  async approveRequest(approvalId: string): Promise<void> {
    await request<{ status: string }>(`/api/approvals/${approvalId}/approve`, {
      method: 'POST',
    });
  },

  /**
   * Reject a pending approval request.
   */
  async rejectRequest(approvalId: string): Promise<void> {
    await request<{ status: string }>(`/api/approvals/${approvalId}/reject`, {
      method: 'POST',
    });
  },
};

// AI Assist endpoints
export const aiAssist = {
  /**
   * Parse a natural language schedule description into a cron expression.
   * Uses an LLM to interpret the input.
   * @param naturalLanguage - Natural language description (e.g., "every day at 9am")
   * @param timezone - IANA timezone for interpreting the schedule (default: UTC)
   */
  async parseSchedule(naturalLanguage: string, timezone: string = 'UTC'): Promise<ParseScheduleResponse> {
    return request<ParseScheduleResponse>('/api/ai-assist/parse-schedule', {
      method: 'POST',
      body: JSON.stringify({
        natural_language: naturalLanguage,
        timezone,
      }),
    });
  },

  /**
   * Enhance a system prompt using AI.
   * Takes a basic prompt and improves it with clearer instructions.
   * @param prompt - Current system prompt to enhance
   * @param agentName - Name of the agent (for context)
   */
  async enhancePrompt(
    prompt: string,
    agentName: string,
    toolPermissions?: string[]
  ): Promise<EnhancePromptResponse> {
    const body: EnhancePromptRequest = {
      prompt,
      agent_name: agentName,
    };

    if (toolPermissions !== undefined) {
      body.tool_permissions = toolPermissions;
    }

    return request<EnhancePromptResponse>('/api/ai-assist/enhance-prompt', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },
};
