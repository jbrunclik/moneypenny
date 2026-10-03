/**
 * Conversations API: list/sync/CRUD, message pages, archive, trash, and single-message operations.
 */
import {
  PaginationDirection,
  type Conversation,
  type ConversationDetailResponse,
  type ConversationsResponse,
  type ConversationsPagination,
  type Message,
  type MessagesResponse,
  type MessagesPagination,
  type SyncResponse,
} from '../types/api';
import { request, requestWithRetry } from './http';

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
    // Map snake_case message_count to camelCase messageCount. Pinned
    // conversations arrive separately (excluded from the paginated portion)
    // and are merged in front so the store holds one list.
    const normalize = (conv: Conversation): Conversation => ({
      ...conv,
      messageCount: (conv as { message_count?: number }).message_count,
    });
    return {
      conversations: [
        ...(data.pinned_conversations ?? []).map(normalize),
        ...data.conversations.map(normalize),
      ],
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
    // Moves to the trash; idempotent server-side, safe to retry
    await request<{ status: string }>(`/api/conversations/${id}`, {
      method: 'DELETE',
      retry: true,
    });
  },

  /**
   * Persist anonymous mode for a conversation so it survives a page reload.
   */
  async pin(id: string): Promise<void> {
    await request<{ status: string }>(`/api/conversations/${id}/pin`, {
      method: 'POST',
      retry: true,
    });
  },

  async unpin(id: string): Promise<void> {
    await request<{ status: string }>(`/api/conversations/${id}/unpin`, {
      method: 'POST',
      retry: true,
    });
  },

  /**
   * Delete a conversation's tail from a message (inclusive = the message
   * itself too). Powers edit-and-resend.
   */
  async truncate(id: string, messageId: string, inclusive = true): Promise<void> {
    await request<{ deleted: number }>(`/api/conversations/${id}/truncate`, {
      method: 'POST',
      body: JSON.stringify({ message_id: messageId, inclusive }),
    });
  },

  async setAnonymousMode(id: string, anonymousMode: boolean): Promise<void> {
    // PATCH is idempotent (same update = same result), safe to retry
    await request<{ status: string }>(`/api/conversations/${id}/anonymous-mode`, {
      method: 'PATCH',
      body: JSON.stringify({ anonymous_mode: anonymousMode }),
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

  async restore(id: string): Promise<void> {
    // Idempotent server-side (restoring a live conversation is a no-op), safe to retry
    await request<{ status: string }>(`/api/conversations/${id}/restore`, {
      method: 'POST',
      retry: true,
    });
  },

  async deletePermanently(id: string): Promise<void> {
    // Not retried: a retry after a lost response would 404
    await request<{ status: string }>(`/api/conversations/${id}/permanent`, {
      method: 'DELETE',
    });
  },

  async emptyTrash(): Promise<number> {
    const data = await request<{ deleted: number }>('/api/conversations/trash', {
      method: 'DELETE',
    });
    return data.deleted;
  },

  /** Ask the running turn (named by its assistant message id) to stop server-side. */
  async stop(id: string, messageId: string): Promise<void> {
    await request<{ status: string }>(`/api/conversations/${id}/chat/stop`, {
      method: 'POST',
      body: JSON.stringify({ message_id: messageId }),
    });
  },

  /** Ask a running deep-research turn to write its report from what it has. */
  async finishNow(id: string, messageId: string): Promise<void> {
    await request<{ status: string }>(`/api/conversations/${id}/chat/finish-now`, {
      method: 'POST',
      body: JSON.stringify({ message_id: messageId }),
    });
  },

  /** Steer a turn that is currently generating (picked up between tool rounds). */
  async interject(id: string, message: string): Promise<void> {
    await request<{ status: string }>(`/api/conversations/${id}/chat/interject`, {
      method: 'POST',
      body: JSON.stringify({ message }),
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

  async listTrash(
    limit?: number,
    cursor?: string | null
  ): Promise<{ conversations: Conversation[]; pagination: ConversationsPagination }> {
    const params = new URLSearchParams();
    if (limit) params.set('limit', limit.toString());
    if (cursor) params.set('cursor', cursor);
    const query = params.toString();
    const data = await requestWithRetry<ConversationsResponse>(
      `/api/conversations/trash${query ? `?${query}` : ''}`
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

  /** Decline a deep-research offer (starting one goes through the chat stream). */
  async declineResearchOffer(id: string): Promise<void> {
    await request<{ status: string }>(`/api/messages/${id}/research-offer`, {
      method: 'PATCH',
      body: JSON.stringify({ status: 'declined' }),
    });
  },
};
