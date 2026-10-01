import type { Conversation, ConversationsPagination } from '../../types/api';
import type { AppSlice } from '../store';
import {
  appendSortedByUpdatedAt,
  emptyConversationsPagination,
  insertSortedByUpdatedAt,
  toConversationsPaginationState,
  type ConversationsPaginationState,
} from './conversationOrder';

export interface TrashData {
  trashedConversations: Conversation[];
  trashPagination: ConversationsPaginationState;
  isTrashView: boolean;
}

export interface TrashSlice extends TrashData {
  setTrashedConversations: (conversations: Conversation[], pagination: ConversationsPagination) => void;
  appendTrashedConversations: (conversations: Conversation[], pagination: ConversationsPagination) => void;
  removeTrashedConversation: (id: string) => void;
  addTrashedConversation: (conversation: Conversation) => void;
  clearTrash: () => void;
  setIsTrashView: (active: boolean) => void;
  setLoadingMoreTrash: (loading: boolean) => void;
}

/** Initial trash state; also what logout resets to. */
export function initialTrashData(): TrashData {
  return {
    trashedConversations: [],
    trashPagination: emptyConversationsPagination(),
    isTrashView: false,
  };
}

export const createTrashSlice: AppSlice<TrashSlice> = (set) => ({
  ...initialTrashData(),

  setTrashedConversations: (conversations, pagination) =>
    set({
      trashedConversations: conversations,
      trashPagination: toConversationsPaginationState(pagination),
    }),
  appendTrashedConversations: (newConversations, pagination) =>
    set((state) => {
      const existingIds = new Set(state.trashedConversations.map((c) => c.id));
      const filtered = newConversations.filter((c) => !existingIds.has(c.id));
      return {
        trashedConversations: filtered.reduce(appendSortedByUpdatedAt, state.trashedConversations),
        trashPagination: toConversationsPaginationState(pagination),
      };
    }),
  removeTrashedConversation: (id) =>
    set((state) => ({
      trashedConversations: state.trashedConversations.filter((c) => c.id !== id),
      trashPagination: {
        ...state.trashPagination,
        totalCount: Math.max(0, state.trashPagination.totalCount - 1),
      },
    })),
  addTrashedConversation: (conversation) =>
    set((state) => ({
      trashedConversations: insertSortedByUpdatedAt(state.trashedConversations, conversation),
      trashPagination: {
        ...state.trashPagination,
        totalCount: state.trashPagination.totalCount + 1,
      },
    })),
  clearTrash: () => set({ trashedConversations: [], trashPagination: emptyConversationsPagination() }),
  setIsTrashView: (isTrashView) => set({ isTrashView }),
  setLoadingMoreTrash: (loading) =>
    set((state) => ({
      trashPagination: {
        ...state.trashPagination,
        isLoadingMore: loading,
      },
    })),
});
