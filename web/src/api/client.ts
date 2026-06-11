import {
  PaginationDirection,
  type Agent,
  type AgentConversationSyncResponse,
  type AgentExecutionsListResponse,
  type AgentsListResponse,
  type AuthResponse,
  type ChatResponse,
  type CommandCenterResponse,
  type Conversation,
  type ConversationDetailResponse,
  type ConversationsResponse,
  type ConversationsPagination,
  type CostHistoryResponse,
  type ConversationCostResponse,
  type CreateAgentRequest,
  type EnhancePromptRequest,
  type EnhancePromptResponse,
  type ErrorResponse,
  type KVKeysResponse,
  type KVNamespacesResponse,
  type KVValueResponse,
  type FileUpload,
  type MemoriesResponse,
  type Memory,
  type Message,
  type MessageCostResponse,
  type MessagesResponse,
  type MessagesPagination,
  type MonthlyCostResponse,
  type ModelsResponse,
  type ParseScheduleResponse,
  type PlannerConversation,
  type PlannerDashboard,
  type PlannerResetResponse,
  type PlannerSyncResponse,
  type SportsConversation,
  type SportsProgram,
  type SportsProgramsResponse,
  type SportsResetResponse,
  type LanguageConversation,
  type LanguageProgram,
  type LanguageProgramsResponse,
  type LanguageResetResponse,
  type SearchResponse,
  type StreamEvent,
  type SyncResponse,
  type TodoistAuthUrl,
  type TodoistConnectResponse,
  type TodoistStatus,
  type TriggerAgentResponse,
  type CalendarAuthUrl,
  type CalendarConnectResponse,
  type CalendarListResponse,
  type CalendarStatus,
  type GarminConnectResponse,
  type GarminStatus,
  type SelectedCalendarsResponse,
  type UpdateAgentRequest,
  type UploadConfig,
  type User,
  type UserSettings,
  type VersionResponse,
} from '../types/api';
import {
  API_CHAT_TIMEOUT_MS,
  THUMBNAIL_POLL_INITIAL_DELAY_MS,
  THUMBNAIL_POLL_MAX_DELAY_MS,
  THUMBNAIL_POLL_MAX_ATTEMPTS,
} from '../config';
import { createLogger } from '../utils/logger';
import { ApiError, getToken, request, requestWithRetry, requestWithProgress } from './http';
import { readSseEvents } from './sse';

const log = createLogger('api');

// Auth endpoints
export const auth = {
  async getClientId(): Promise<string> {
    const data = await requestWithRetry<{ client_id: string }>('/auth/client-id');
    return data.client_id;
  },

  async googleLogin(credential: string): Promise<AuthResponse> {
    // POST - no retry (not idempotent)
    return request<AuthResponse>('/auth/google', {
      method: 'POST',
      body: JSON.stringify({ credential }),
    });
  },

  async me(): Promise<User> {
    const data = await requestWithRetry<{ user: User }>('/auth/me');
    return data.user;
  },

  async refreshToken(): Promise<string> {
    // POST - no retry (not idempotent, creates new token)
    const data = await request<{ token: string }>('/auth/refresh', {
      method: 'POST',
    });
    return data.token;
  },
};

// Conversation endpoints
export const conversations = {
  /**
   * List conversations with pagination.
   * @param limit - Number of conversations to return
   * @param cursor - Cursor for fetching next page
   */
  async list(
    limit?: number,
    cursor?: string | null
  ): Promise<{ conversations: Conversation[]; pagination: ConversationsPagination }> {
    const params = new URLSearchParams();
    if (limit) params.set('limit', limit.toString());
    if (cursor) params.set('cursor', cursor);
    const query = params.toString();
    const data = await requestWithRetry<ConversationsResponse>(
      `/api/conversations${query ? `?${query}` : ''}`
    );
    // Map snake_case message_count to camelCase messageCount
    return {
      conversations: data.conversations.map((conv) => ({
        ...conv,
        messageCount: (conv as { message_count?: number }).message_count,
      })),
      pagination: data.pagination,
    };
  },

  /**
   * Get a conversation with paginated messages.
   * @param id - Conversation ID
   * @param messageLimit - Number of messages to return
   * @param messageCursor - Cursor for fetching older/newer messages
   * @param direction - PaginationDirection.OLDER or PaginationDirection.NEWER
   */
  async get(
    id: string,
    messageLimit?: number,
    messageCursor?: string | null,
    direction?: PaginationDirection
  ): Promise<ConversationDetailResponse> {
    const params = new URLSearchParams();
    if (messageLimit) params.set('message_limit', messageLimit.toString());
    if (messageCursor) params.set('message_cursor', messageCursor);
    if (direction) params.set('direction', direction);
    const query = params.toString();
    return requestWithRetry<ConversationDetailResponse>(
      `/api/conversations/${id}${query ? `?${query}` : ''}`
    );
  },

  /**
   * Get paginated messages for a conversation.
   * This is a dedicated endpoint, more efficient than get() when only messages are needed.
   * @param id - Conversation ID
   * @param limit - Number of messages to return
   * @param cursor - Cursor for fetching older/newer messages
   * @param direction - PaginationDirection.OLDER or PaginationDirection.NEWER
   */
  async getMessages(
    id: string,
    limit?: number,
    cursor?: string | null,
    direction?: PaginationDirection
  ): Promise<{ messages: Message[]; pagination: MessagesPagination }> {
    const params = new URLSearchParams();
    if (limit) params.set('limit', limit.toString());
    if (cursor) params.set('cursor', cursor);
    if (direction) params.set('direction', direction);
    const query = params.toString();
    return requestWithRetry<MessagesResponse>(
      `/api/conversations/${id}/messages${query ? `?${query}` : ''}`
    );
  },

  /**
   * Get messages around a specific message (for search result navigation).
   * Loads a window of messages centered on the target message, enabling
   * bi-directional pagination from that position.
   * @param id - Conversation ID
   * @param messageId - Target message ID to center around
   * @param limit - Total messages to return (split between before/after target)
   */
  async getMessagesAround(
    id: string,
    messageId: string,
    limit?: number
  ): Promise<{ messages: Message[]; pagination: MessagesPagination }> {
    const params = new URLSearchParams();
    params.set('around_message_id', messageId);
    if (limit) params.set('limit', limit.toString());
    return requestWithRetry<MessagesResponse>(
      `/api/conversations/${id}/messages?${params.toString()}`
    );
  },

  /**
   * Get a single message by ID.
   * Used for stream recovery when the connection drops but the message was saved server-side.
   * @param messageId - The message ID to fetch
   */
  async getMessage(messageId: string): Promise<Message> {
    return requestWithRetry<Message>(`/api/messages/${messageId}`);
  },

  async create(model?: string): Promise<Conversation> {
    // POST - no retry (not idempotent - creates new resource)
    return request<Conversation>('/api/conversations', {
      method: 'POST',
      body: JSON.stringify({ model }),
    });
  },

  async update(
    id: string,
    data: { title?: string; model?: string }
  ): Promise<void> {
    // PATCH is idempotent (same update = same result), safe to retry
    await request<{ status: string }>(`/api/conversations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
      retry: true,
    });
  },

  async delete(id: string): Promise<void> {
    // DELETE is idempotent (deleting already deleted = same result), safe to retry
    await request<{ status: string }>(`/api/conversations/${id}`, {
      method: 'DELETE',
      retry: true,
    });
  },

  async archive(id: string): Promise<void> {
    await request<{ status: string }>(`/api/conversations/${id}/archive`, {
      method: 'POST',
      retry: true,
    });
  },

  async unarchive(id: string): Promise<void> {
    await request<{ status: string }>(`/api/conversations/${id}/unarchive`, {
      method: 'POST',
      retry: true,
    });
  },

  async listArchived(
    limit?: number,
    cursor?: string | null
  ): Promise<{ conversations: Conversation[]; pagination: ConversationsPagination }> {
    const params = new URLSearchParams();
    if (limit) params.set('limit', limit.toString());
    if (cursor) params.set('cursor', cursor);
    const query = params.toString();
    const data = await requestWithRetry<ConversationsResponse>(
      `/api/conversations/archived${query ? `?${query}` : ''}`
    );
    return {
      conversations: data.conversations.map((conv) => ({
        ...conv,
        messageCount: (conv as { message_count?: number }).message_count,
      })),
      pagination: data.pagination,
    };
  },

  /**
   * Sync conversations with the server.
   * @param since - ISO timestamp to get conversations updated since (null for full sync)
   * @param full - Force full sync even with since parameter (for delete detection)
   */
  async sync(since: string | null, full: boolean = false): Promise<SyncResponse> {
    const params = new URLSearchParams();
    if (since) params.set('since', since);
    if (full) params.set('full', 'true');
    const query = params.toString();
    return requestWithRetry<SyncResponse>(`/api/conversations/sync${query ? `?${query}` : ''}`);
  },
};

// Message endpoints
export const messages = {
  async delete(id: string): Promise<void> {
    // DELETE is idempotent (deleting already deleted = same result), safe to retry
    await request<{ status: string }>(`/api/messages/${id}`, {
      method: 'DELETE',
      retry: true,
    });
  },
};

// Chat endpoints
export const chat = {
  async sendBatch(
    conversationId: string,
    message: string,
    files?: FileUpload[],
    forceTools?: string[],
    onUploadProgress?: (progress: number) => void,
    anonymousMode?: boolean
  ): Promise<ChatResponse> {
    // POST - no retry (not idempotent - could duplicate message)
    // Use longer timeout for chat (image generation, complex tool chains)
    const url = `/api/conversations/${conversationId}/chat/batch`;
    const body = {
      message,
      files,
      force_tools: forceTools?.length ? forceTools : undefined,
      anonymous_mode: anonymousMode ?? false,
    };

    // Use XHR with progress callback when files are attached
    if (files && files.length > 0 && onUploadProgress) {
      return requestWithProgress<ChatResponse>(url, body, {
        timeout: API_CHAT_TIMEOUT_MS,
        onUploadProgress,
      });
    }

    // Use standard fetch for requests without files
    return request<ChatResponse>(url, {
      method: 'POST',
      timeout: API_CHAT_TIMEOUT_MS,
      body: JSON.stringify(body),
    });
  },

  async *stream(
    conversationId: string,
    message: string,
    files?: FileUpload[],
    forceTools?: string[],
    abortController?: AbortController,
    anonymousMode?: boolean
  ): AsyncGenerator<StreamEvent> {
    log.debug('Starting stream', { conversationId, messageLength: message.length, fileCount: files?.length ?? 0 });
    const token = getToken();

    // Use provided controller or create new one for timeout
    const controller = abortController || new AbortController();
    // Only set timeout if using internal controller (not user-provided)
    const fetchTimeoutId = abortController
      ? null
      : setTimeout(() => controller.abort(), API_CHAT_TIMEOUT_MS);

    let response: Response;
    try {
      response = await fetch(
        `/api/conversations/${conversationId}/chat/stream`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({
            message,
            files,
            force_tools: forceTools?.length ? forceTools : undefined,
            anonymous_mode: anonymousMode ?? false,
          }),
          signal: controller.signal,
        }
      );
      if (fetchTimeoutId) clearTimeout(fetchTimeoutId);
    } catch (error) {
      if (fetchTimeoutId) clearTimeout(fetchTimeoutId);
      if (error instanceof Error && error.name === 'AbortError') {
        // If user provided controller, this is a user-initiated abort - re-throw as AbortError
        if (abortController) {
          throw error;
        }
        // Otherwise it's a timeout
        throw new ApiError(
          'Request timed out before streaming started.',
          0,
          { code: 'TIMEOUT', retryable: true, isTimeout: true }
        );
      }
      throw error;
    }

    if (!response.ok) {
      const data = (await response.json()) as ErrorResponse;
      const errorMsg = typeof data.error === 'string' ? data.error : data.error?.message || 'Stream request failed';
      throw new ApiError(errorMsg, response.status);
    }

    yield* readSseEvents(response, conversationId);
  },

  /**
   * Resume an interrupted chat stream from the server-side event journal.
   * Replays events with seq > afterSeq, continues live, ends with done.
   */
  async *resumeStream(
    conversationId: string,
    messageId: string,
    afterSeq: number,
    abortController?: AbortController
  ): AsyncGenerator<StreamEvent> {
    log.info('Resuming stream', { conversationId, messageId, afterSeq });
    const token = getToken();
    const controller = abortController || new AbortController();

    const response = await fetch(
      `/api/conversations/${conversationId}/chat/stream/${messageId}/resume?after_seq=${afterSeq}`,
      {
        method: 'GET',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: controller.signal,
      }
    );

    if (!response.ok) {
      throw new ApiError(`Resume failed (${response.status})`, response.status);
    }

    yield* readSseEvents(response, conversationId);
  },
};
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
      const response = await fetch(
        `/api/messages/${messageId}/files/${fileIndex}/thumbnail`,
        {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        }
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
    const response = await fetch(
      `/api/messages/${messageId}/files/${fileIndex}`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }
    );

    if (!response.ok) {
      throw new ApiError('Failed to fetch file', response.status);
    }

    return response.blob();
  },
};

// Version endpoint (no auth required)
export const version = {
  async get(): Promise<VersionResponse> {
    const response = await fetch('/api/version');
    return response.json() as Promise<VersionResponse>;
  },
};

// Cost tracking endpoints
export const costs = {
  async getConversationCost(conversationId: string): Promise<ConversationCostResponse> {
    return requestWithRetry<ConversationCostResponse>(`/api/conversations/${conversationId}/cost`);
  },

  async getMonthlyCost(year?: number, month?: number): Promise<MonthlyCostResponse> {
    const params = new URLSearchParams();
    if (year) params.set('year', year.toString());
    if (month) params.set('month', month.toString());
    const query = params.toString();
    return requestWithRetry<MonthlyCostResponse>(`/api/users/me/costs/monthly${query ? `?${query}` : ''}`);
  },

  async getCostHistory(limit?: number): Promise<CostHistoryResponse> {
    const params = new URLSearchParams();
    if (limit) params.set('limit', limit.toString());
    const query = params.toString();
    return requestWithRetry<CostHistoryResponse>(`/api/users/me/costs/history${query ? `?${query}` : ''}`);
  },

  async getMessageCost(messageId: string): Promise<MessageCostResponse> {
    return requestWithRetry<MessageCostResponse>(`/api/messages/${messageId}/cost`);
  },
};

// Memory endpoints
export const memories = {
  async list(): Promise<Memory[]> {
    const data = await requestWithRetry<MemoriesResponse>('/api/memories');
    return data.memories;
  },

  async delete(memoryId: string): Promise<void> {
    // DELETE is idempotent, safe to retry
    await request<{ status: string }>(`/api/memories/${memoryId}`, {
      method: 'DELETE',
      retry: true,
    });
  },
};

// Settings endpoints
export const settings = {
  async get(): Promise<UserSettings> {
    return requestWithRetry<UserSettings>('/api/users/me/settings');
  },

  async update(data: Partial<UserSettings>): Promise<void> {
    // PATCH is idempotent (same update = same result), safe to retry
    await request<{ status: string }>('/api/users/me/settings', {
      method: 'PATCH',
      body: JSON.stringify(data),
      retry: true,
    });
  },
};

// Todoist integration endpoints
export const todoist = {
  /**
   * Get the Todoist OAuth authorization URL.
   * Returns a URL to redirect the user to and a state token for CSRF protection.
   */
  async getAuthUrl(): Promise<TodoistAuthUrl> {
    return requestWithRetry<TodoistAuthUrl>('/auth/todoist/auth-url');
  },

  /**
   * Exchange Todoist OAuth code for access token and connect the account.
   * @param code - The authorization code from Todoist callback
   * @param state - The state token for CSRF validation (client should verify this)
   */
  async connect(code: string, state: string): Promise<TodoistConnectResponse> {
    return request<TodoistConnectResponse>('/auth/todoist/connect', {
      method: 'POST',
      body: JSON.stringify({ code, state }),
    });
  },

  /**
   * Disconnect the user's Todoist account.
   */
  async disconnect(): Promise<void> {
    await request<{ status: string }>('/auth/todoist/disconnect', {
      method: 'POST',
    });
  },

  /**
   * Get the current Todoist connection status.
   */
  async getStatus(): Promise<TodoistStatus> {
    return requestWithRetry<TodoistStatus>('/auth/todoist/status');
  },
};

// Google Calendar integration endpoints
export const calendar = {
  async getAuthUrl(): Promise<CalendarAuthUrl> {
    return requestWithRetry<CalendarAuthUrl>('/auth/calendar/auth-url');
  },

  async connect(code: string, state: string): Promise<CalendarConnectResponse> {
    return request<CalendarConnectResponse>('/auth/calendar/connect', {
      method: 'POST',
      body: JSON.stringify({ code, state }),
    });
  },

  async disconnect(): Promise<void> {
    await request<{ status: string }>('/auth/calendar/disconnect', {
      method: 'POST',
    });
  },

  async getStatus(): Promise<CalendarStatus> {
    return requestWithRetry<CalendarStatus>('/auth/calendar/status');
  },

  async listCalendars(): Promise<CalendarListResponse> {
    return requestWithRetry<CalendarListResponse>('/auth/calendar/calendars');
  },

  async getSelectedCalendars(): Promise<SelectedCalendarsResponse> {
    return requestWithRetry<SelectedCalendarsResponse>('/auth/calendar/selected-calendars');
  },

  async updateSelectedCalendars(calendarIds: string[]): Promise<SelectedCalendarsResponse> {
    return request<SelectedCalendarsResponse>('/auth/calendar/selected-calendars', {
      method: 'PUT',
      body: JSON.stringify({ calendar_ids: calendarIds }),
    });
  },
};

// Garmin Connect endpoints
export const garmin = {
  async connect(
    email: string,
    password: string,
  ): Promise<GarminConnectResponse> {
    return request<GarminConnectResponse>('/auth/garmin/connect', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  },

  async submitMfa(
    email: string,
    password: string,
    mfaCode: string,
  ): Promise<GarminConnectResponse> {
    return request<GarminConnectResponse>('/auth/garmin/mfa', {
      method: 'POST',
      body: JSON.stringify({ email, password, mfa_code: mfaCode }),
    });
  },

  async disconnect(): Promise<void> {
    await request<{ status: string }>('/auth/garmin/disconnect', {
      method: 'POST',
    });
  },

  async getStatus(): Promise<GarminStatus> {
    return requestWithRetry<GarminStatus>('/auth/garmin/status');
  },
};

// Search endpoints
export const search = {
  /**
   * Search across all conversations and messages.
   *
   * @param query - Search query string
   * @param limit - Maximum results to return (default: 20, max: 50)
   * @param offset - Number of results to skip for pagination
   * @returns Search results with conversation info and message snippets
   */
  async query(query: string, limit: number = 20, offset: number = 0): Promise<SearchResponse> {
    const params = new URLSearchParams({
      q: query,
      limit: String(limit),
      offset: String(offset),
    });
    return requestWithRetry<SearchResponse>(`/api/search?${params}`);
  },
};

// Planner endpoints
export const planner = {
  /**
   * Get the planner dashboard with events and tasks for the next 7 days.
   * Includes overdue tasks and integration connection status.
   * @param forceRefresh If true, bypasses cache and fetches fresh data
   */
  async getDashboard(forceRefresh: boolean = false): Promise<PlannerDashboard> {
    const url = forceRefresh ? '/api/planner?force_refresh=true' : '/api/planner';
    return requestWithRetry<PlannerDashboard>(url);
  },

  /**
   * Get or create the user's planner conversation.
   * If a reset is due (after 4am), messages will be cleared automatically.
   * @returns The planner conversation with messages and was_reset flag
   */
  async getConversation(): Promise<PlannerConversation> {
    return requestWithRetry<PlannerConversation>('/api/planner/conversation');
  },

  /**
   * Reset the planner conversation (clear all messages).
   * Physically deletes messages but preserves cost data for accuracy.
   */
  async reset(): Promise<PlannerResetResponse> {
    return request<PlannerResetResponse>('/api/planner/reset', {
      method: 'POST',
    });
  },

  /**
   * Get planner conversation state for real-time synchronization.
   * Returns conversation metadata (message count, last reset) to detect
   * external updates, resets, or deletion in other tabs/devices.
   */
  async sync(): Promise<PlannerSyncResponse> {
    return requestWithRetry<PlannerSyncResponse>('/api/planner/sync');
  },
};

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

// KV Store endpoints
export const kvStore = {
  async getNamespaces(): Promise<KVNamespacesResponse> {
    return requestWithRetry<KVNamespacesResponse>('/api/kv');
  },

  async getKeys(namespace: string): Promise<KVKeysResponse> {
    return requestWithRetry<KVKeysResponse>(`/api/kv/${encodeURIComponent(namespace)}`);
  },

  async getValue(namespace: string, key: string): Promise<KVValueResponse> {
    return requestWithRetry<KVValueResponse>(`/api/kv/${encodeURIComponent(namespace)}/${encodeURIComponent(key)}`);
  },

  async setValue(namespace: string, key: string, value: string): Promise<KVValueResponse> {
    return request<KVValueResponse>(`/api/kv/${encodeURIComponent(namespace)}/${encodeURIComponent(key)}`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    });
  },

  async deleteKey(namespace: string, key: string): Promise<void> {
    await request<{ status: string }>(`/api/kv/${encodeURIComponent(namespace)}/${encodeURIComponent(key)}`, {
      method: 'DELETE',
      retry: true,
    });
  },

  async clearNamespace(namespace: string): Promise<void> {
    await request<{ status: string }>(`/api/kv/${encodeURIComponent(namespace)}`, {
      method: 'DELETE',
    });
  },
};

// Sports endpoints
export const sports = {
  async getPrograms(): Promise<SportsProgram[]> {
    const data = await requestWithRetry<SportsProgramsResponse>('/api/sports/programs');
    return data.programs;
  },

  async createProgram(data: { name: string; emoji: string }): Promise<SportsProgram> {
    const response = await request<SportsProgramsResponse>('/api/sports/programs', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    return response.programs[0];
  },

  async deleteProgram(id: string): Promise<void> {
    await request<{ status: string }>(`/api/sports/programs/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    });
  },

  async getConversation(program: string): Promise<SportsConversation> {
    return requestWithRetry<SportsConversation>(`/api/sports/${encodeURIComponent(program)}/conversation`);
  },

  async reset(program: string): Promise<SportsResetResponse> {
    return request<SportsResetResponse>(`/api/sports/${encodeURIComponent(program)}/reset`, {
      method: 'POST',
    });
  },
};

// Language Learning endpoints
export const language = {
  async getPrograms(): Promise<LanguageProgram[]> {
    const data = await requestWithRetry<LanguageProgramsResponse>('/api/language/programs');
    return data.programs;
  },

  async createProgram(data: { name: string; emoji: string }): Promise<LanguageProgram> {
    const response = await request<LanguageProgramsResponse>('/api/language/programs', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    return response.programs[0];
  },

  async deleteProgram(id: string): Promise<void> {
    await request<{ status: string }>(`/api/language/programs/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    });
  },

  async getConversation(program: string): Promise<LanguageConversation> {
    return requestWithRetry<LanguageConversation>(`/api/language/${encodeURIComponent(program)}/conversation`);
  },

  async reset(program: string): Promise<LanguageResetResponse> {
    return request<LanguageResetResponse>(`/api/language/${encodeURIComponent(program)}/reset`, {
      method: 'POST',
    });
  },
};


// Web Push endpoints
export const push = {
  async getVapidPublicKey(): Promise<{ enabled: boolean; public_key: string | null }> {
    return requestWithRetry<{ enabled: boolean; public_key: string | null }>('/api/push/vapid-public-key');
  },

  async subscribe(subscription: { endpoint: string; keys: { p256dh: string; auth: string } }): Promise<{ success: boolean; subscription_id: string }> {
    return request<{ success: boolean; subscription_id: string }>('/api/push/subscriptions', {
      method: 'POST',
      body: JSON.stringify(subscription),
    });
  },

  async unsubscribe(endpoint: string): Promise<void> {
    await request<{ status: string }>('/api/push/subscriptions', {
      method: 'DELETE',
      body: JSON.stringify({ endpoint }),
    });
  },

  async sendTest(): Promise<{ status: string }> {
    return request<{ status: string }>('/api/push/test', { method: 'POST' });
  },
};
