import { compareTimestamps } from '../../utils/timestamps';
import type { Conversation, ConversationsPagination } from '../../types/api';

/**
 * Pagination state for a conversations list (active or archived)
 */
export interface ConversationsPaginationState {
  nextCursor: string | null;
  hasMore: boolean;
  totalCount: number;
  isLoadingMore: boolean;
}

export function emptyConversationsPagination(): ConversationsPaginationState {
  return {
    nextCursor: null,
    hasMore: false,
    totalCount: 0,
    isLoadingMore: false,
  };
}

export function toConversationsPaginationState(
  pagination: ConversationsPagination
): ConversationsPaginationState {
  return {
    nextCursor: pagination.next_cursor,
    hasMore: pagination.has_more,
    totalCount: pagination.total_count,
    isLoadingMore: false,
  };
}

/**
 * Insert a conversation into a list sorted by updated_at DESC.
 * Uses <= so that conversations with the same timestamp are prepended
 * (newer first). The sidebar renders the array in order and emits date-group
 * labels on group changes, so this invariant must hold after every mutation.
 */
export function insertSortedByUpdatedAt(
  conversations: Conversation[],
  conversation: Conversation
): Conversation[] {
  const result = [...conversations];
  const insertIndex = result.findIndex((c) => compareTimestamps(c.updated_at, conversation.updated_at) <= 0);
  if (insertIndex === -1) {
    result.push(conversation);
  } else {
    result.splice(insertIndex, 0, conversation);
  }
  return result;
}

/**
 * Like insertSortedByUpdatedAt but stable for pagination: an item with a
 * timestamp equal to existing entries goes AFTER them, preserving the
 * server's page order instead of reversing it.
 */
export function appendSortedByUpdatedAt(
  conversations: Conversation[],
  conversation: Conversation
): Conversation[] {
  const result = [...conversations];
  const insertIndex = result.findIndex((c) => compareTimestamps(c.updated_at, conversation.updated_at) < 0);
  if (insertIndex === -1) {
    result.push(conversation);
  } else {
    result.splice(insertIndex, 0, conversation);
  }
  return result;
}

/**
 * Current time in the backend's timestamp format: datetime.now().isoformat()
 * - LOCAL time, no timezone suffix (e.g. "2026-08-24T12:34:56.789").
 * Ordering compares instants (utils/timestamps), so a "...Z" string would
 * sort correctly too; this keeps optimistic bumps in the server's format.
 */
export function localIsoNow(): string {
  const d = new Date();
  const pad = (n: number, w = 2) => String(n).padStart(w, '0');
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`
  );
}
