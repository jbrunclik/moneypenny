/**
 * Conversations API: list/sync/CRUD, message pages, archive, trash, and single-message operations.
 */
import {
  type ConversationFactsResponse,
  PaginationDirection,
  type BulkTrashRequest,
  type Conversation,
  type ConversationDetailResponse,
  type ConversationsResponse,
  type ConversationsPagination,
  type Message,
  type MessagesResponse,
  type MessagesPagination,
  type SyncResponse,
} from '../types/api';
import { ApiError, fetchWithConnectTimeout, getToken, request, requestWithRetry } from './http';
import { API_DEFAULT_TIMEOUT_MS } from '../config';

type ConversationListItem = ConversationsResponse['conversations'][number];

/**
 * The store Conversation for a listed summary: snake_case message_count
 * becomes messageCount, and the counts and flags the server sends as null
 * are left out. `withUnread`: the unread badge from the server-side read
 * state (read_count, shared across devices), so it shows from the first paint.
 */
export function toConversation(conv: ConversationListItem, withUnread = false): Conversation {
  const { message_count, read_count, archived, pinned, ...rest } = conv;
  return {
    ...rest,
    ...(archived !== null && { archived }),
    ...(pinned !== null && { pinned }),
    ...(message_count !== null && { messageCount: message_count }),
    ...(withUnread &&
      message_count !== null &&
      read_count !== null && { unreadCount: Math.max(0, message_count - read_count) }),
  };
}

// Conversation endpoints
/** The file name from a Content-Disposition header (its UTF-8 `filename*` first). */
export function exportFileName(header: string | null): string {
  const utf8 = header?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (utf8) {
    try {
      return decodeURIComponent(utf8);
    } catch {
      // A malformed escape: fall back to the plain name
    }
  }
  return header?.match(/filename="([^"]+)"/i)?.[1] ?? 'conversation.md';
}

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
    const normalize = (conv: ConversationListItem): Conversation => toConversation(conv, true);
    return {
      conversations: [
        ...data.pinned_conversations.map(normalize),
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
  /** The conversation's settled facts (read-only; the agent keeps them). */
  async getFacts(id: string): Promise<ConversationFactsResponse> {
    return requestWithRetry<ConversationFactsResponse>(`/api/conversations/${id}/facts`);
  },

  async getMessage(messageId: string): Promise<Message> {
    return requestWithRetry<Message>(`/api/messages/${messageId}`);
  },

  async create(model?: string, projectId?: string | null): Promise<Conversation> {
    // POST - no retry (not idempotent - creates new resource)
    return request<Conversation>('/api/conversations', {
      method: 'POST',
      body: JSON.stringify(projectId ? { model, project_id: projectId } : { model }),
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

  async bulkTrash(body: BulkTrashRequest): Promise<string[]> {
    // Idempotent server-side (already-trashed rows are skipped), safe to retry
    const data = await request<{ trashed_ids: string[] }>('/api/conversations/bulk-trash', {
      method: 'POST',
      body: JSON.stringify(body),
      retry: true,
    });
    return data.trashed_ids;
  },

  async bulkRestore(ids: string[]): Promise<string[]> {
    // Idempotent server-side (live rows are skipped), safe to retry
    const data = await request<{ restored_ids: string[] }>('/api/conversations/bulk-restore', {
      method: 'POST',
      body: JSON.stringify({ ids }),
      retry: true,
    });
    return data.restored_ids;
  },

  /** Ask the running turn (named by its assistant message id) to stop server-side. */
  /** The conversation as a Markdown file, with the name the server gives it. */
  async exportMarkdown(id: string): Promise<{ blob: Blob; fileName: string }> {
    const token = getToken();
    const response = await fetchWithConnectTimeout(
      `/api/conversations/${id}/export`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      API_DEFAULT_TIMEOUT_MS
    );
    if (!response.ok) throw new ApiError('Failed to export the conversation', response.status);
    return { blob: await response.blob(), fileName: exportFileName(response.headers.get('Content-Disposition')) };
  },

  /** Stop a turn named by its reply id, or - before the stream's first
   * event - by the id of the message it answers. */
  async stop(id: string, turn: { messageId: string } | { clientMessageId: string }): Promise<void> {
    const body =
      'messageId' in turn ? { message_id: turn.messageId } : { client_message_id: turn.clientMessageId };
    await request<{ status: string }>(`/api/conversations/${id}/chat/stop`, {
      method: 'POST',
      body: JSON.stringify(body),
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
  async interject(id: string, message: string, clientMessageId?: string): Promise<void> {
    await request<{ status: string }>(`/api/conversations/${id}/chat/interject`, {
      method: 'POST',
      body: JSON.stringify({ message, client_message_id: clientMessageId }),
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
      conversations: data.conversations.map((conv) => toConversation(conv)),
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
      conversations: data.conversations.map((conv) => toConversation(conv)),
      pagination: data.pagination,
    };
  },

  /** Full sync: every conversation with its state, plus the change-log cursor. */
  async sync(): Promise<SyncResponse> {
    return requestWithRetry<SyncResponse>('/api/conversations/sync?full=true');
  },

  /** Record that this device has shown the conversation up to messageCount. */
  async markRead(id: string, messageCount: number): Promise<void> {
    await request<{ status: string }>(`/api/conversations/${id}/read`, {
      method: 'POST',
      body: JSON.stringify({ message_count: messageCount }),
    });
  },

  /** Conversations changed after a change-log cursor, with their state. */
  async syncChanges(cursor: number): Promise<SyncResponse> {
    return requestWithRetry<SyncResponse>(`/api/conversations/sync?cursor=${cursor}`);
  },
};

// Message endpoints
export const messages = {
  /**
   * Edit a sent user message in place: everything after it goes, its text
   * changes and its attachments stay (the reply is regenerated after).
   */
  async edit(id: string, content: string): Promise<void> {
    await request<{ deleted: number }>(`/api/messages/${id}/edit`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    });
  },

  async delete(id: string): Promise<void> {
    // DELETE is idempotent (deleting already deleted = same result), safe to retry
    await request<{ status: string }>(`/api/messages/${id}`, {
      method: 'DELETE',
      retry: true,
    });
  },

};
