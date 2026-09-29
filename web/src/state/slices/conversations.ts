import type { Conversation, ConversationsPagination } from '../../types/api';
import type { AppSlice } from '../store';
import {
  appendSortedByUpdatedAt,
  emptyConversationsPagination,
  insertSortedByUpdatedAt,
  localIsoNow,
  toConversationsPaginationState,
  type ConversationsPaginationState,
} from './conversationOrder';

export interface ConversationsData {
  conversations: Conversation[];
  currentConversation: Conversation | null;
  conversationsPagination: ConversationsPaginationState;

  // Per-conversation composer drafts (survive switching and reloads)
  conversationDrafts: Record<string, string>;
}

export interface ConversationsSlice extends ConversationsData {
  // Actions - Conversations
  setConversations: (conversations: Conversation[], pagination: ConversationsPagination) => void;
  appendConversations: (conversations: Conversation[], pagination: ConversationsPagination) => void;
  addConversation: (conversation: Conversation) => void;
  updateConversation: (id: string, updates: Partial<Conversation>) => void;
  bumpConversationActivity: (id: string, preview?: string) => void;
  removeConversation: (id: string) => void;
  setCurrentConversation: (conversation: Conversation | null) => void;
  setLoadingMoreConversations: (loading: boolean) => void;

  // Actions - Drafts
  setConversationDraft: (convId: string, text: string) => void;
  getConversationDraft: (convId: string) => string;
  migrateConversationDraft: (fromId: string, toId: string) => void;
}

/** Initial conversations state; also what logout resets to. */
export function initialConversationsData(): ConversationsData {
  return {
    conversations: [],
    currentConversation: null,
    conversationsPagination: emptyConversationsPagination(),
    conversationDrafts: {},
  };
}

/**
 * Idempotent add: an already-known conversation is merged in place (or
 * re-inserted when its timestamp moved); a new one is inserted sorted.
 */
function withAddedConversation(
  state: ConversationsData,
  conversation: Conversation
): Partial<ConversationsData> {
  const existingIndex = state.conversations.findIndex((c) => c.id === conversation.id);
  if (existingIndex !== -1) {
    // Merge with existing, preserving unreadCount if not provided in new data
    const existing = state.conversations[existingIndex];
    const merged = {
      ...existing,
      ...conversation,
      // Preserve unreadCount if the new conversation doesn't specify it
      unreadCount: conversation.unreadCount ?? existing.unreadCount,
    };
    // Re-insert at the correct sorted position when the timestamp
    // changed (e.g. a message bumped updated_at); otherwise keep the
    // current position to avoid shuffling equal-timestamp neighbors
    let newConvs: Conversation[];
    if (merged.updated_at !== existing.updated_at) {
      newConvs = state.conversations.filter((c) => c.id !== conversation.id);
      newConvs = insertSortedByUpdatedAt(newConvs, merged);
    } else {
      newConvs = [...state.conversations];
      newConvs[existingIndex] = merged;
    }
    return {
      conversations: newConvs,
      conversationsPagination: state.conversationsPagination, // Don't increment count
    };
  }

  // Insert conversation at correct sorted position (by updated_at DESC)
  // This ensures conversations discovered via sync appear in correct order
  // For temp conversations (newly created), always prepend to ensure they appear at top
  const isTempConversation = conversation.id.startsWith('temp-');
  const newConvs = isTempConversation
    ? [conversation, ...state.conversations]
    : insertSortedByUpdatedAt(state.conversations, conversation);

  return {
    conversations: newConvs,
    conversationsPagination: {
      ...state.conversationsPagination,
      totalCount: state.conversationsPagination.totalCount + 1,
    },
  };
}

function withUpdatedConversation(
  state: ConversationsData,
  id: string,
  updates: Partial<Conversation>
): Partial<ConversationsData> {
  const currentConversation =
    state.currentConversation?.id === id
      ? { ...state.currentConversation, ...updates }
      : state.currentConversation;

  const existing = state.conversations.find((c) => c.id === id);
  if (!existing) return { currentConversation };

  const merged = { ...existing, ...updates };
  // A bumped updated_at (message sent, sync poll) changes the
  // conversation's date group - re-insert at the correct sorted
  // position so the sidebar's group labels render in order
  const conversations =
    merged.updated_at !== existing.updated_at
      ? insertSortedByUpdatedAt(
          state.conversations.filter((c) => c.id !== id),
          merged
        )
      : state.conversations.map((c) => (c.id === id ? merged : c));

  return { conversations, currentConversation };
}

export const createConversationsSlice: AppSlice<ConversationsSlice> = (set, get) => ({
  ...initialConversationsData(),

  setConversations: (conversations, pagination) =>
    set({
      conversations,
      conversationsPagination: toConversationsPaginationState(pagination),
    }),
  appendConversations: (newConversations, pagination) =>
    set((state) => {
      // Deduplicate: filter out conversations already in the store
      const existingIds = new Set(state.conversations.map((c) => c.id));
      const filtered = newConversations.filter((c) => !existingIds.has(c.id));

      // Pages usually arrive older-than-tail, but a locally re-sorted head
      // (optimistic bumps) can break that assumption - merge-insert to
      // keep the sorted-by-updated_at-desc invariant
      return {
        conversations: filtered.reduce(appendSortedByUpdatedAt, state.conversations),
        conversationsPagination: toConversationsPaginationState(pagination),
      };
    }),
  addConversation: (conversation) => set((state) => withAddedConversation(state, conversation)),
  updateConversation: (id, updates) =>
    set((state) => withUpdatedConversation(state, id, updates)),
  // Optimistic sidebar bump on user activity (message send): moves the
  // conversation to the top with a fresh timestamp instead of waiting up
  // to a full sync-poll interval for the server's updated_at
  bumpConversationActivity: (id, preview) => {
    const updates: Partial<Conversation> = {
      updated_at: localIsoNow(),
    };
    if (preview) {
      updates.last_message_preview = preview;
    }
    get().updateConversation(id, updates);
  },
  removeConversation: (id) =>
    set((state) => ({
      conversations: state.conversations.filter((c) => c.id !== id),
      currentConversation:
        state.currentConversation?.id === id ? null : state.currentConversation,
      conversationsPagination: {
        ...state.conversationsPagination,
        totalCount: Math.max(0, state.conversationsPagination.totalCount - 1),
      },
    })),
  setCurrentConversation: (currentConversation) => set({ currentConversation }),
  setLoadingMoreConversations: (loading) =>
    set((state) => ({
      conversationsPagination: {
        ...state.conversationsPagination,
        isLoadingMore: loading,
      },
    })),

  // Draft actions (for error recovery)
  setConversationDraft: (convId, text) =>
    set((state) => {
      const drafts = { ...state.conversationDrafts };
      if (text) {
        drafts[convId] = text;
      } else {
        delete drafts[convId];
      }
      return { conversationDrafts: drafts };
    }),
  getConversationDraft: (convId) => get().conversationDrafts[convId] ?? '',
  migrateConversationDraft: (fromId, toId) =>
    set((state) => {
      const draft = state.conversationDrafts[fromId];
      if (draft === undefined) return state;
      const drafts = { ...state.conversationDrafts };
      delete drafts[fromId];
      drafts[toId] = draft;
      return { conversationDrafts: drafts };
    }),
});
