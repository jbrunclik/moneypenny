/**
 * Bulk delete: one request, rows leave after the server confirms, one Undo.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import type { Conversation } from '@/types/api';

const api = vi.hoisted(() => ({
  bulkTrash: vi.fn(),
  bulkRestore: vi.fn(),
  listTrash: vi.fn(),
}));
const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
const syncMock = vi.hoisted(() => ({ noteLocalChange: vi.fn(), incrementalSync: vi.fn() }));

vi.mock('@/api/conversations', () => ({ conversations: api, messages: {} }));
vi.mock('@/components/Toast', () => ({ toast: toastMock }));
vi.mock('@/components/Modal', () => ({ showConfirm: vi.fn(), showPrompt: vi.fn() }));
vi.mock('@/sync/SyncManager', () => ({ getSyncManager: () => syncMock }));
vi.mock('@/components/Sidebar', () => ({
  renderConversationsList: vi.fn(),
  loadArchivedConversations: vi.fn(),
  cleanupArchiveInfiniteScroll: vi.fn(),
}));
vi.mock('@/components/SidebarSelection', () => ({ renderSelectionChrome: vi.fn() }));
vi.mock('@/components/messages', () => ({ renderMessages: vi.fn(), updateChatTitle: vi.fn() }));
vi.mock('@/components/ChatHeader', () => ({ renderChatHeader: vi.fn() }));
vi.mock('@/core/toolbar', () => ({ updateConversationCost: vi.fn() }));
vi.mock('@/router/deeplink', () => ({
  clearConversationHash: vi.fn(),
  setTrashHash: vi.fn(),
  setConversationHash: vi.fn(),
  setArchiveHash: vi.fn(),
}));

import { bulkDeleteConversations } from '@/core/conversation-actions';
import { restoreConversations } from '@/core/trash';
import { clearConversationHash } from '@/router/deeplink';

function conv(id: string, extra: Partial<Conversation> = {}): Conversation {
  return { id, title: id, model: 'm', created_at: '', updated_at: '2026-01-01T00:00:00Z', ...extra };
}
const emptyPagination = { nextCursor: null, hasMore: false, totalCount: 0, isLoadingMore: false };
const s = () => useStore.getState();

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({
    conversations: [conv('a'), conv('b'), conv('c')],
    conversationsPagination: { ...emptyPagination, totalCount: 3 },
    trashedConversations: [],
    trashPagination: { ...emptyPagination },
    currentConversation: null,
  });
  s().endSelection();
  api.listTrash.mockResolvedValue({
    conversations: [],
    pagination: { next_cursor: null, has_more: false, total_count: 0 },
  });
});

function pick(...ids: string[]): void {
  s().startSelection();
  ids.forEach((id) => s().toggleSelected(conv(id)));
}

describe('bulkDeleteConversations', () => {
  it('trashes the picked rows with one request, no confirm, and offers one Undo', async () => {
    api.bulkTrash.mockResolvedValue(['a', 'b']);
    pick('a', 'b');

    await bulkDeleteConversations();

    expect(api.bulkTrash).toHaveBeenCalledTimes(1);
    expect(api.bulkTrash).toHaveBeenCalledWith({ ids: ['a', 'b'] });
    expect(s().conversations.map((c) => c.id)).toEqual(['c']);
    expect(s().isSelecting).toBe(false);
    expect(syncMock.noteLocalChange).toHaveBeenCalledWith('a');
    expect(toastMock.success).toHaveBeenCalledWith(
      'Moved 2 chats to trash.',
      expect.objectContaining({ action: expect.objectContaining({ label: 'Undo' }) })
    );
  });

  it('keeps rows and selection on failure', async () => {
    api.bulkTrash.mockRejectedValue(new Error('boom'));
    pick('a');

    await bulkDeleteConversations();

    expect(s().conversations).toHaveLength(3);
    expect(s().isSelecting).toBe(true);
    expect(s().selectedIds.has('a')).toBe(true);
    expect(s().isBulkDeleting).toBe(false);
    expect(toastMock.error).toHaveBeenCalledWith('Failed to move chats to trash. Please try again.');
  });

  it('ignores a second call while one is running', async () => {
    let resolve: (ids: string[]) => void = () => {};
    api.bulkTrash.mockReturnValue(new Promise<string[]>((r) => (resolve = r)));
    pick('a');

    const first = bulkDeleteConversations();
    await bulkDeleteConversations();
    resolve(['a']);
    await first;

    expect(api.bulkTrash).toHaveBeenCalledTimes(1);
  });

  it('clears the open chat when it was trashed', async () => {
    api.bulkTrash.mockResolvedValue(['a']);
    useStore.setState({ currentConversation: conv('a') });
    pick('a');

    await bulkDeleteConversations();

    expect(s().currentConversation).toBeNull();
    expect(clearConversationHash).toHaveBeenCalled();
  });

  it('removes temp chats locally without a request', async () => {
    useStore.setState({ conversations: [conv('temp-1'), conv('a')] });
    pick('temp-1');

    await bulkDeleteConversations();

    expect(api.bulkTrash).not.toHaveBeenCalled();
    expect(s().conversations.map((c) => c.id)).toEqual(['a']);
    expect(s().isSelecting).toBe(false);
  });

  it('says "1 chat" for one', async () => {
    api.bulkTrash.mockResolvedValue(['a']);
    pick('a');

    await bulkDeleteConversations();

    expect(toastMock.success).toHaveBeenCalledWith('Moved 1 chat to trash.', expect.anything());
  });
});

describe('restoreConversations', () => {
  it('restores in one call and puts the rows back', async () => {
    useStore.setState({ conversations: [conv('c')] });
    api.bulkRestore.mockResolvedValue(['a', 'b']);

    await restoreConversations(['a', 'b'], [conv('a'), conv('b')]);

    expect(api.bulkRestore).toHaveBeenCalledWith(['a', 'b']);
    expect(s().conversations.map((c) => c.id).sort()).toEqual(['a', 'b', 'c']);
    expect(toastMock.success).toHaveBeenCalledWith('Restored 2 chats.');
  });

  it('chunks to the bulk cap', async () => {
    const ids = Array.from({ length: 501 }, (_, i) => `x${i}`);
    api.bulkRestore.mockImplementation(async (chunk: string[]) => chunk);

    await restoreConversations(ids, []);

    expect(api.bulkRestore).toHaveBeenCalledTimes(2);
    expect(api.bulkRestore.mock.calls[0][0]).toHaveLength(500);
    expect(api.bulkRestore.mock.calls[1][0]).toEqual(['x500']);
  });

  it('unknown ids trigger an incremental sync', async () => {
    api.bulkRestore.mockResolvedValue(['unloaded']);

    await restoreConversations(['unloaded'], []);

    expect(syncMock.incrementalSync).toHaveBeenCalled();
  });

  it('reports failure', async () => {
    api.bulkRestore.mockRejectedValue(new Error('boom'));

    await restoreConversations(['a'], [conv('a')]);

    expect(toastMock.error).toHaveBeenCalledWith('Failed to restore chats.');
  });
});
