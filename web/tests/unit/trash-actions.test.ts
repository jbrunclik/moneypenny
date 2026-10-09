/**
 * Tests for trash actions: delete -> trash with Undo, restore routing,
 * delete forever, empty trash.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import type { Conversation } from '@/types/api';
import { ApiError } from '@/api/http';

const api = vi.hoisted(() => ({
  delete: vi.fn(),
  restore: vi.fn(),
  deletePermanently: vi.fn(),
  emptyTrash: vi.fn(),
  listTrash: vi.fn(),
}));
const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
const confirmMock = vi.hoisted(() => vi.fn());

vi.mock('@/api/conversations', () => ({ conversations: api, messages: {} }));
vi.mock('@/components/Toast', () => ({ toast: toastMock }));
vi.mock('@/components/Modal', () => ({ showConfirm: confirmMock, showPrompt: vi.fn() }));
vi.mock('@/components/Sidebar', () => ({
  renderConversationsList: vi.fn(),
  loadArchivedConversations: vi.fn(),
  cleanupArchiveInfiniteScroll: vi.fn(),
}));
vi.mock('@/components/messages', () => ({ renderMessages: vi.fn(), updateChatTitle: vi.fn() }));
vi.mock('@/components/ChatHeader', () => ({ renderChatHeader: vi.fn() }));
vi.mock('@/core/toolbar', () => ({ updateConversationCost: vi.fn() }));
vi.mock('@/router/deeplink', () => ({
  clearConversationHash: vi.fn(),
  setTrashHash: vi.fn(),
  setConversationHash: vi.fn(),
  setArchiveHash: vi.fn(),
}));

import { deleteConversation } from '@/core/conversation-actions';
import { renderConversationsList } from '@/components/Sidebar';
import { restoreConversation, deleteConversationForever, emptyTrash } from '@/core/trash';

function conv(id: string, extra: Partial<Conversation> = {}): Conversation {
  return { id, title: id, model: 'm', created_at: '', updated_at: '2026-01-01T00:00:00Z', ...extra };
}

const emptyPagination = { nextCursor: null, hasMore: false, totalCount: 0, isLoadingMore: false };

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({
    conversations: [],
    archivedConversations: [],
    archivedPagination: { ...emptyPagination },
    trashedConversations: [],
    trashPagination: { ...emptyPagination },
    currentConversation: null,
  });
  confirmMock.mockResolvedValue(true);
  Object.values(api).forEach((fn) => fn.mockResolvedValue(undefined));
});

describe('deleteConversation (move to trash)', () => {
  it('asks with trash wording and moves the row into the trash', async () => {
    useStore.setState({ conversations: [conv('a')] });

    await deleteConversation('a');

    expect(confirmMock).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'Move to trash',
        message: 'Move this conversation to the trash? You can restore it for 14 days.',
        confirmLabel: 'Move to trash',
        // Reversible (restorable from the trash): a neutral button, not red
        danger: false,
      })
    );
    expect(api.delete).toHaveBeenCalledWith('a');
    expect(useStore.getState().conversations).toEqual([]);
    expect(useStore.getState().trashedConversations.map((c) => c.id)).toEqual(['a']);
    expect(toastMock.success).toHaveBeenCalledWith(
      'Moved to trash.',
      expect.objectContaining({ action: expect.objectContaining({ label: 'Undo' }) })
    );
  });

  it('the trash already holds the row when the list re-renders (menu badge)', async () => {
    useStore.setState({ conversations: [conv('a')] });
    const trashSizesAtRender: number[] = [];
    vi.mocked(renderConversationsList).mockImplementation(() => {
      trashSizesAtRender.push(useStore.getState().trashedConversations.length);
    });

    await deleteConversation('a');

    expect(trashSizesAtRender.length).toBeGreaterThan(0);
    expect(trashSizesAtRender.at(-1)).toBe(1);
    expect(trashSizesAtRender[0]).toBe(1);
  });

  it('estimates purge_at locally so the row always shows its days left', async () => {
    useStore.setState({ conversations: [conv('a')] });

    await deleteConversation('a');

    const row = useStore.getState().trashedConversations[0];
    const days = (new Date(row.purge_at!).getTime() - new Date(row.deleted_at!).getTime()) / 86_400_000;
    expect(days).toBe(14);
  });

  it('does nothing when cancelled', async () => {
    useStore.setState({ conversations: [conv('a')] });
    confirmMock.mockResolvedValue(false);

    await deleteConversation('a');

    expect(api.delete).not.toHaveBeenCalled();
    expect(useStore.getState().conversations).toHaveLength(1);
  });

  it('Undo puts an archived conversation back into the archive', async () => {
    useStore.setState({ archivedConversations: [conv('a', { archived: true })] });

    await deleteConversation('a');
    const undo = toastMock.success.mock.calls[0][1].action.onClick as () => Promise<void>;
    await undo();

    expect(api.restore).toHaveBeenCalledWith('a');
    expect(useStore.getState().archivedConversations.map((c) => c.id)).toEqual(['a']);
    expect(useStore.getState().conversations).toEqual([]);
    expect(useStore.getState().trashedConversations).toEqual([]);
  });
});

describe('Undo for a conversation outside the loaded lists', () => {
  it('uses the open conversation, so Undo restores it', async () => {
    // e.g. an older archived chat opened from search: not in either loaded list
    useStore.setState({ currentConversation: conv('a', { archived: true }) });

    await deleteConversation('a');
    const undo = toastMock.success.mock.calls[0][1].action.onClick as () => Promise<void>;
    await undo();

    expect(api.restore).toHaveBeenCalledWith('a');
    expect(useStore.getState().archivedConversations.map((c) => c.id)).toEqual(['a']);
  });
});

describe('restoreConversation', () => {
  it('returns a live conversation to the main list', async () => {
    useStore.setState({ trashedConversations: [conv('a', { archived: false, purge_at: 'x' })] });

    await restoreConversation('a');

    expect(useStore.getState().conversations.map((c) => c.id)).toEqual(['a']);
    expect(useStore.getState().conversations[0].purge_at).toBeNull();
    expect(useStore.getState().trashedConversations).toEqual([]);
  });

  it('returns an archived conversation to the archive', async () => {
    useStore.setState({ trashedConversations: [conv('a', { archived: true })] });

    await restoreConversation('a');

    expect(useStore.getState().archivedConversations.map((c) => c.id)).toEqual(['a']);
    expect(useStore.getState().conversations).toEqual([]);
  });

  it('still restores server-side when there is no local copy', async () => {
    await restoreConversation('ghost');

    expect(api.restore).toHaveBeenCalledWith('ghost');
    expect(toastMock.success).toHaveBeenCalledWith('Conversation restored.');
  });

  it('keeps the row and shows an error when the request fails', async () => {
    useStore.setState({ trashedConversations: [conv('a')] });
    api.restore.mockRejectedValue(new Error('network'));

    await restoreConversation('a');

    expect(useStore.getState().trashedConversations).toHaveLength(1);
    expect(toastMock.error).toHaveBeenCalled();
  });
});

describe('deleteConversationForever', () => {
  it('confirms, deletes and drops the row', async () => {
    useStore.setState({ trashedConversations: [conv('a')] });

    await deleteConversationForever('a');

    expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({ danger: true }));
    expect(api.deletePermanently).toHaveBeenCalledWith('a');
    expect(useStore.getState().trashedConversations).toEqual([]);
  });

  it('treats 404 as already gone', async () => {
    useStore.setState({ trashedConversations: [conv('a')] });
    api.deletePermanently.mockRejectedValue(new ApiError('Not found', 404));

    await deleteConversationForever('a');

    expect(useStore.getState().trashedConversations).toEqual([]);
    expect(toastMock.error).not.toHaveBeenCalled();
  });

  it('keeps the row on other errors', async () => {
    useStore.setState({ trashedConversations: [conv('a')] });
    api.deletePermanently.mockRejectedValue(new ApiError('Boom', 500));

    await deleteConversationForever('a');

    expect(useStore.getState().trashedConversations).toHaveLength(1);
    expect(toastMock.error).toHaveBeenCalled();
  });
});

describe('emptyTrash', () => {
  it('confirms then clears the trash', async () => {
    useStore.setState({
      trashedConversations: [conv('a'), conv('b')],
      trashPagination: { ...emptyPagination, totalCount: 2 },
    });
    api.emptyTrash.mockResolvedValue(2);

    await emptyTrash();

    expect(api.emptyTrash).toHaveBeenCalled();
    expect(useStore.getState().trashedConversations).toEqual([]);
    expect(useStore.getState().trashPagination.totalCount).toBe(0);
  });

  it('does nothing when cancelled', async () => {
    useStore.setState({ trashedConversations: [conv('a')] });
    confirmMock.mockResolvedValue(false);

    await emptyTrash();

    expect(api.emptyTrash).not.toHaveBeenCalled();
    expect(useStore.getState().trashedConversations).toHaveLength(1);
  });
});
