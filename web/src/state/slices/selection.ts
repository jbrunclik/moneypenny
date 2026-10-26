import type { BulkTrashRequest, Conversation } from '../../types/api';
import type { AppSlice, AppState } from '../store';
import { isTempConversation } from '../../utils/conversation-id';

export type SelectionMode = 'ids' | 'all';

/**
 * Sidebar selection for bulk delete. In 'ids' mode selectedIds are the
 * picked chats. In 'all' mode every unpinned chat counts as selected
 * (also pages not loaded yet) except excludedIds, and selectedIds holds
 * pinned chats picked by hand.
 */
export interface SelectionData {
  isSelecting: boolean;
  selectionMode: SelectionMode;
  selectedIds: Set<string>;
  excludedIds: Set<string>;
  selectAllCreatedBefore: string | null;
  isBulkDeleting: boolean;
}

export interface SelectionSlice extends SelectionData {
  startSelection: () => void;
  endSelection: () => void;
  toggleSelected: (conv: Pick<Conversation, 'id' | 'pinned'>) => void;
  selectAll: (createdBefore: string) => void;
  deselectAll: () => void;
  setBulkDeleting: (busy: boolean) => void;
}

/** Initial selection state; also what logout resets to. */
export function initialSelectionData(): SelectionData {
  return {
    isSelecting: false,
    selectionMode: 'ids',
    selectedIds: new Set(),
    excludedIds: new Set(),
    selectAllCreatedBefore: null,
    isBulkDeleting: false,
  };
}

function toggled(set: Set<string>, id: string): Set<string> {
  const next = new Set(set);
  if (!next.delete(id)) next.add(id);
  return next;
}

export const createSelectionSlice: AppSlice<SelectionSlice> = (set) => ({
  ...initialSelectionData(),

  startSelection: () => set({ ...initialSelectionData(), isSelecting: true }),
  endSelection: () => set(initialSelectionData()),
  toggleSelected: (conv) =>
    set((state) =>
      state.selectionMode === 'all' && !conv.pinned
        ? { excludedIds: toggled(state.excludedIds, conv.id) }
        : { selectedIds: toggled(state.selectedIds, conv.id) }
    ),
  selectAll: (createdBefore) =>
    set({
      selectionMode: 'all',
      selectedIds: new Set(),
      excludedIds: new Set(),
      selectAllCreatedBefore: createdBefore,
    }),
  deselectAll: () =>
    set({ selectionMode: 'ids', selectedIds: new Set(), excludedIds: new Set(), selectAllCreatedBefore: null }),
  setBulkDeleting: (isBulkDeleting) => set({ isBulkDeleting }),
});

export function isConversationSelected(
  state: AppState,
  conv: Pick<Conversation, 'id' | 'pinned'>
): boolean {
  if (state.selectionMode === 'all' && !conv.pinned) return !state.excludedIds.has(conv.id);
  return state.selectedIds.has(conv.id);
}

/** "N selected": in 'all' mode the server's list total (pinned included) minus pinned, exclusions. */
export function selectedCount(state: AppState): number {
  if (state.selectionMode === 'ids') return state.selectedIds.size;
  const pinned = state.conversations.filter((c) => c.pinned).length;
  const unpinnedTotal = Math.max(0, state.conversationsPagination.totalCount - pinned);
  return Math.max(0, unpinnedTotal - state.excludedIds.size) + state.selectedIds.size;
}

/** Selected chats among the loaded rows (for local removal and noteLocalChange). */
export function selectedLoadedIds(state: AppState): string[] {
  return state.conversations.filter((c) => isConversationSelected(state, c)).map((c) => c.id);
}

const isServerId = (id: string): boolean => !isTempConversation(id);

/** The bulk-trash body, or null when nothing on the server is selected. */
export function buildBulkTrashRequest(state: AppState): BulkTrashRequest | null {
  const serverIds = (ids: Set<string>) => [...ids].filter(isServerId);
  if (state.selectionMode === 'all' && state.selectAllCreatedBefore) {
    return {
      all: true,
      ids: serverIds(state.selectedIds),
      exclude_ids: serverIds(state.excludedIds),
      created_before: state.selectAllCreatedBefore,
    };
  }
  const ids = serverIds(state.selectedIds);
  return ids.length ? { ids } : null;
}
