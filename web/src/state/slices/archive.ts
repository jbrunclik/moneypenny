import type { Conversation, ConversationsPagination } from '../../types/api';
import type { AppSlice } from '../store';
import {
  appendSortedByUpdatedAt,
  emptyConversationsPagination,
  insertSortedByUpdatedAt,
  toConversationsPaginationState,
  type ConversationsPaginationState,
} from './conversationOrder';

export interface ArchiveData {
  archivedConversations: Conversation[];
  archivedPagination: ConversationsPaginationState;
  isArchiveView: boolean;
}

export interface ArchiveSlice extends ArchiveData {
  setArchivedConversations: (conversations: Conversation[], pagination: ConversationsPagination) => void;
  appendArchivedConversations: (conversations: Conversation[], pagination: ConversationsPagination) => void;
  removeArchivedConversation: (id: string) => void;
  addArchivedConversation: (conversation: Conversation) => void;
  updateArchivedConversation: (id: string, updates: Partial<Conversation>) => void;
  setIsArchiveView: (active: boolean) => void;
  setLoadingMoreArchived: (loading: boolean) => void;
}

/** Initial archive state; also what logout resets to. */
export function initialArchiveData(): ArchiveData {
  return {
    archivedConversations: [],
    archivedPagination: emptyConversationsPagination(),
    isArchiveView: false,
  };
}

export const createArchiveSlice: AppSlice<ArchiveSlice> = (set) => ({
  ...initialArchiveData(),

  setArchivedConversations: (conversations, pagination) =>
    set({
      archivedConversations: conversations,
      archivedPagination: toConversationsPaginationState(pagination),
    }),
  appendArchivedConversations: (newConversations, pagination) =>
    set((state) => {
      const existingIds = new Set(state.archivedConversations.map((c) => c.id));
      const filtered = newConversations.filter((c) => !existingIds.has(c.id));
      return {
        archivedConversations: filtered.reduce(appendSortedByUpdatedAt, state.archivedConversations),
        archivedPagination: toConversationsPaginationState(pagination),
      };
    }),
  removeArchivedConversation: (id) =>
    set((state) => ({
      archivedConversations: state.archivedConversations.filter((c) => c.id !== id),
      archivedPagination: {
        ...state.archivedPagination,
        totalCount: Math.max(0, state.archivedPagination.totalCount - 1),
      },
    })),
  addArchivedConversation: (conversation) =>
    set((state) => ({
      archivedConversations: insertSortedByUpdatedAt(state.archivedConversations, conversation),
      archivedPagination: {
        ...state.archivedPagination,
        totalCount: state.archivedPagination.totalCount + 1,
      },
    })),
  updateArchivedConversation: (id, updates) =>
    set((state) => ({
      archivedConversations: state.archivedConversations.map((c) =>
        c.id === id ? { ...c, ...updates } : c
      ),
    })),
  setIsArchiveView: (isArchiveView) => set({ isArchiveView }),
  setLoadingMoreArchived: (loading) =>
    set((state) => ({
      archivedPagination: {
        ...state.archivedPagination,
        isLoadingMore: loading,
      },
    })),
});
