import type { Message, MessagesPagination } from '../../types/api';
import type { AppSlice } from '../store';

/**
 * Pagination state for messages in a conversation
 */
export interface MessagesPaginationState {
  olderCursor: string | null;
  newerCursor: string | null;
  hasOlder: boolean;
  hasNewer: boolean;
  totalCount: number;
  isLoadingOlder: boolean;
  isLoadingNewer: boolean;
}

export interface MessagesData {
  // Messages (per conversation)
  messages: Map<string, Message[]>;
  messagesPagination: Map<string, MessagesPaginationState>;
}

export interface MessagesSlice extends MessagesData {
  setMessages: (convId: string, messages: Message[], pagination: MessagesPagination) => void;
  prependMessages: (convId: string, messages: Message[], pagination: MessagesPagination) => void;
  appendMessages: (convId: string, messages: Message[], pagination: MessagesPagination) => void;
  appendMessage: (convId: string, message: Message) => void;
  updateMessage: (convId: string, messageId: string, updates: Partial<Message>) => void;
  removeMessage: (convId: string, messageId: string) => void;
  truncateMessagesFrom: (convId: string, messageId: string) => void;
  clearMessages: (convId: string) => void;
  setLoadingOlderMessages: (convId: string, loading: boolean) => void;
  setLoadingNewerMessages: (convId: string, loading: boolean) => void;
  getMessages: (convId: string) => Message[];
  getMessagesPagination: (convId: string) => MessagesPaginationState | undefined;
}

/** Initial messages state; also what logout resets to. */
export function initialMessagesData(): MessagesData {
  return {
    messages: new Map(),
    messagesPagination: new Map(),
  };
}

function toMessagesPaginationState(pagination: MessagesPagination): MessagesPaginationState {
  return {
    olderCursor: pagination.older_cursor,
    newerCursor: pagination.newer_cursor,
    hasOlder: pagination.has_older,
    hasNewer: pagination.has_newer,
    totalCount: pagination.total_count,
    isLoadingOlder: false,
    isLoadingNewer: false,
  };
}

/** Replace a conversation's message list and its pagination in one update. */
function withMessagesPage(
  state: MessagesData,
  convId: string,
  messages: Message[],
  pagination: MessagesPagination
): MessagesData {
  const newMessages = new Map(state.messages);
  newMessages.set(convId, messages);
  const newPagination = new Map(state.messagesPagination);
  newPagination.set(convId, toMessagesPaginationState(pagination));
  return { messages: newMessages, messagesPagination: newPagination };
}

/**
 * Store an updated message list and shift the pagination total by `delta`
 * (clamped at 0) when the conversation has pagination state.
 */
function withMessagesAndCount(
  state: MessagesData,
  convId: string,
  messages: Message[],
  delta: number
): Partial<MessagesData> {
  const newMessages = new Map(state.messages);
  newMessages.set(convId, messages);
  const pag = state.messagesPagination.get(convId);
  if (!pag) return { messages: newMessages };
  const newPagination = new Map(state.messagesPagination);
  newPagination.set(convId, { ...pag, totalCount: Math.max(0, pag.totalCount + delta) });
  return { messages: newMessages, messagesPagination: newPagination };
}

function withAppendedMessage(
  state: MessagesData,
  convId: string,
  message: Message
): Partial<MessagesData> {
  const existing = state.messages.get(convId) || [];
  // Idempotent by id: a reply can complete via more than one path
  // (live done event, journal resume, poll recovery) - the later
  // append replaces the earlier one in place instead of duplicating
  const index = existing.findIndex((m) => m.id === message.id);
  if (index !== -1) {
    const replaced = [...existing];
    replaced[index] = message;
    const newMessages = new Map(state.messages);
    newMessages.set(convId, replaced);
    return { messages: newMessages };
  }
  // Update total count in pagination
  return withMessagesAndCount(state, convId, [...existing, message], 1);
}

function withPaginationFlag(
  state: MessagesData,
  convId: string,
  flag: Partial<Pick<MessagesPaginationState, 'isLoadingOlder' | 'isLoadingNewer'>>
): Partial<MessagesData> {
  const pag = state.messagesPagination.get(convId);
  if (!pag) return state;
  const newPagination = new Map(state.messagesPagination);
  newPagination.set(convId, { ...pag, ...flag });
  return { messagesPagination: newPagination };
}

export const createMessagesSlice: AppSlice<MessagesSlice> = (set, get) => ({
  ...initialMessagesData(),

  setMessages: (convId, messages, pagination) =>
    set((state) => withMessagesPage(state, convId, messages, pagination)),
  prependMessages: (convId, newMsgs, pagination) =>
    set((state) => {
      const existing = state.messages.get(convId) || [];
      return withMessagesPage(state, convId, [...newMsgs, ...existing], pagination);
    }),
  appendMessages: (convId, newMsgs, pagination) =>
    set((state) => {
      const existing = state.messages.get(convId) || [];
      return withMessagesPage(state, convId, [...existing, ...newMsgs], pagination);
    }),
  appendMessage: (convId, message) =>
    set((state) => withAppendedMessage(state, convId, message)),
  updateMessage: (convId, messageId, updates) =>
    set((state) => {
      const existing = state.messages.get(convId);
      if (!existing?.some((m) => m.id === messageId)) return state;
      const newMessages = new Map(state.messages);
      newMessages.set(
        convId,
        existing.map((m) => (m.id === messageId ? { ...m, ...updates } : m))
      );
      return { messages: newMessages };
    }),
  truncateMessagesFrom: (convId, messageId) =>
    set((state) => {
      const existing = state.messages.get(convId);
      const index = existing?.findIndex((m) => m.id === messageId) ?? -1;
      if (!existing || index === -1) return state;
      const removed = existing.length - index;
      return withMessagesAndCount(state, convId, existing.slice(0, index), -removed);
    }),
  removeMessage: (convId, messageId) =>
    set((state) => {
      const existing = state.messages.get(convId);
      if (!existing?.some((m) => m.id === messageId)) return state;
      const remaining = existing.filter((m) => m.id !== messageId);
      return withMessagesAndCount(state, convId, remaining, -1);
    }),
  clearMessages: (convId) =>
    set((state) => {
      const newMessages = new Map(state.messages);
      newMessages.delete(convId);
      const newPagination = new Map(state.messagesPagination);
      newPagination.delete(convId);
      return { messages: newMessages, messagesPagination: newPagination };
    }),
  setLoadingOlderMessages: (convId, loading) =>
    set((state) => withPaginationFlag(state, convId, { isLoadingOlder: loading })),
  setLoadingNewerMessages: (convId, loading) =>
    set((state) => withPaginationFlag(state, convId, { isLoadingNewer: loading })),
  getMessages: (convId) => get().messages.get(convId) || [],
  getMessagesPagination: (convId) => get().messagesPagination.get(convId),
});
