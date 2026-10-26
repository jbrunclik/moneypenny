/**
 * Conversation archive: archiving moves a conversation from the active list
 * to the archived one (with an Undo toast) and closes it when it is open;
 * unarchiving moves it back. Temporary and unknown conversations are left
 * alone, and a failed request leaves the lists as they were. The archive
 * view lazy-loads archived conversations on first open; leaving it restores
 * the URL of the open conversation (or home).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const api = vi.hoisted(() => ({
  archive: vi.fn<(id: string) => Promise<void>>(),
  unarchive: vi.fn<(id: string) => Promise<void>>(),
}));
const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
const sidebar = vi.hoisted(() => ({
  renderConversationsList: vi.fn(),
  loadArchivedConversations: vi.fn(),
  cleanupArchiveInfiniteScroll: vi.fn(),
}));
const view = vi.hoisted(() => ({ renderMessages: vi.fn(), updateChatTitle: vi.fn(), renderChatHeader: vi.fn() }));
const hash = vi.hoisted(() => ({
  clearConversationHash: vi.fn(),
  setTrashHash: vi.fn(),
  setConversationHash: vi.fn(),
  setArchiveHash: vi.fn(),
}));
const noteLocalChange = vi.hoisted(() => vi.fn());

vi.mock('@/api/conversations', () => ({ conversations: api, messages: {} }));
vi.mock('@/components/Toast', () => ({ toast: toastMock }));
vi.mock('@/components/Sidebar', () => sidebar);
vi.mock('@/components/messages', () => ({
  renderMessages: view.renderMessages,
  updateChatTitle: view.updateChatTitle,
}));
vi.mock('@/components/ChatHeader', () => ({ renderChatHeader: view.renderChatHeader }));
vi.mock('@/router/deeplink', () => hash);
vi.mock('@/sync/SyncManager', () => ({ getSyncManager: () => ({ noteLocalChange }) }));

import { archiveConversation, leaveArchiveView, navigateToArchive, unarchiveConversation } from '@/core/archive';
import { APP_NAME } from '@/config';
import { useStore } from '@/state/store';
import type { Conversation } from '@/types/api';

function conv(id: string, extra: Partial<Conversation> = {}): Conversation {
  return { id, title: id, model: 'm', created_at: '', updated_at: '2026-01-01T00:00:00Z', ...extra };
}

const emptyPagination = { nextCursor: null, hasMore: false, totalCount: 0, isLoadingMore: false };

const activeIds = () => useStore.getState().conversations.map((c) => c.id);
const archivedIds = () => useStore.getState().archivedConversations.map((c) => c.id);

/** The Undo action of the last success toast. */
function undoAction(): () => void {
  const options = toastMock.success.mock.calls.at(-1)?.[1] as { action?: { onClick: () => void } } | undefined;
  const onClick = options?.action?.onClick;
  if (!onClick) throw new Error('no Undo action on the toast');
  return onClick;
}

/** A promise with its resolve exposed, to act while a request is in flight. */
function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve: () => void = () => undefined;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.archive.mockResolvedValue(undefined);
  api.unarchive.mockResolvedValue(undefined);
  useStore.setState({
    conversations: [],
    archivedConversations: [],
    archivedPagination: { ...emptyPagination },
    currentConversation: null,
    isArchiveView: false,
    isTrashView: false,
  });
});

describe('archiveConversation', () => {
  it('moves the conversation to the archived list', async () => {
    useStore.setState({ conversations: [conv('a'), conv('b')] });

    await archiveConversation('a');

    expect(api.archive).toHaveBeenCalledWith('a');
    expect(activeIds()).toEqual(['b']);
    expect(archivedIds()).toEqual(['a']);
    expect(useStore.getState().archivedConversations[0]?.archived).toBe(true);
    expect(sidebar.renderConversationsList).toHaveBeenCalled();
  });

  it('tells the sync manager about the change so a poll does not undo it', async () => {
    useStore.setState({ conversations: [conv('a')] });
    await archiveConversation('a');
    expect(noteLocalChange).toHaveBeenCalledWith('a');
  });

  it('offers an Undo that restores the conversation', async () => {
    useStore.setState({ conversations: [conv('a')] });
    await archiveConversation('a');

    expect(toastMock.success).toHaveBeenCalledWith(
      'Conversation archived.',
      expect.objectContaining({ action: expect.objectContaining({ label: 'Undo' }) })
    );
    undoAction()();
    await vi.waitFor(() => expect(activeIds()).toEqual(['a']));

    expect(api.unarchive).toHaveBeenCalledWith('a');
    expect(archivedIds()).toEqual([]);
  });

  it('closes the conversation when it is the one open', async () => {
    useStore.setState({ conversations: [conv('a')], currentConversation: conv('a') });

    await archiveConversation('a');

    expect(useStore.getState().currentConversation).toBeNull();
    expect(view.renderMessages).toHaveBeenCalledWith([]);
    expect(view.updateChatTitle).toHaveBeenCalledWith(APP_NAME);
    expect(view.renderChatHeader).toHaveBeenCalledWith(null);
    expect(hash.clearConversationHash).toHaveBeenCalled();
  });

  it('keeps another open conversation on screen', async () => {
    useStore.setState({ conversations: [conv('a'), conv('b')], currentConversation: conv('b') });

    await archiveConversation('a');

    expect(useStore.getState().currentConversation?.id).toBe('b');
    expect(view.renderMessages).not.toHaveBeenCalled();
    expect(hash.clearConversationHash).not.toHaveBeenCalled();
  });

  // BUG: archiveConversation reads currentConversation from the state
  // snapshot taken before the archive request. Switching to another
  // conversation while the request is in flight therefore wipes the view of
  // the conversation now open (messages emptied, title reset, URL cleared)
  // and leaves no conversation selected.
  it.fails('keeps a conversation opened while the archive request was in flight', async () => {
    useStore.setState({ conversations: [conv('a'), conv('b')], currentConversation: conv('a') });
    const request = deferred();
    api.archive.mockReturnValue(request.promise);

    const archiving = archiveConversation('a');
    useStore.getState().setCurrentConversation(conv('b'));
    request.resolve();
    await archiving;

    expect(useStore.getState().currentConversation?.id).toBe('b');
    expect(view.renderMessages).not.toHaveBeenCalled();
  });

  it('does nothing for a temporary conversation', async () => {
    useStore.setState({ conversations: [conv('temp-1')] });

    await archiveConversation('temp-1');

    expect(api.archive).not.toHaveBeenCalled();
    expect(activeIds()).toEqual(['temp-1']);
  });

  it('does nothing for a conversation not in the list', async () => {
    await archiveConversation('missing');
    expect(api.archive).not.toHaveBeenCalled();
    expect(toastMock.success).not.toHaveBeenCalled();
  });

  it('keeps the conversation active and shows an error when the request fails', async () => {
    useStore.setState({ conversations: [conv('a')], currentConversation: conv('a') });
    api.archive.mockRejectedValue(new Error('500'));

    await archiveConversation('a');

    expect(activeIds()).toEqual(['a']);
    expect(archivedIds()).toEqual([]);
    expect(useStore.getState().currentConversation?.id).toBe('a');
    expect(toastMock.error).toHaveBeenCalledWith('Failed to archive conversation.');
    expect(toastMock.success).not.toHaveBeenCalled();
  });
});

describe('unarchiveConversation', () => {
  it('moves the conversation back to the active list', async () => {
    useStore.setState({ archivedConversations: [conv('a', { archived: true })] });

    await unarchiveConversation('a');

    expect(api.unarchive).toHaveBeenCalledWith('a');
    expect(archivedIds()).toEqual([]);
    expect(activeIds()).toEqual(['a']);
    expect(useStore.getState().conversations[0]?.archived).toBe(false);
    expect(sidebar.renderConversationsList).toHaveBeenCalled();
    expect(toastMock.success).toHaveBeenCalledWith('Conversation restored.');
  });

  it('tells the sync manager about the change so a poll does not undo it', async () => {
    useStore.setState({ archivedConversations: [conv('a', { archived: true })] });
    await unarchiveConversation('a');
    expect(noteLocalChange).toHaveBeenCalledWith('a');
  });

  it('does nothing for a conversation that is not archived', async () => {
    useStore.setState({ conversations: [conv('a')] });

    await unarchiveConversation('a');

    expect(api.unarchive).not.toHaveBeenCalled();
    expect(activeIds()).toEqual(['a']);
  });

  it('keeps the conversation archived and shows an error when the request fails', async () => {
    useStore.setState({ archivedConversations: [conv('a', { archived: true })] });
    api.unarchive.mockRejectedValue(new Error('500'));

    await unarchiveConversation('a');

    expect(archivedIds()).toEqual(['a']);
    expect(activeIds()).toEqual([]);
    expect(toastMock.error).toHaveBeenCalledWith('Failed to unarchive conversation.');
  });
});

describe('navigateToArchive', () => {
  it('switches to the archive view (out of the trash) and sets its URL', () => {
    useStore.setState({ isTrashView: true });

    navigateToArchive();

    expect(useStore.getState().isArchiveView).toBe(true);
    expect(useStore.getState().isTrashView).toBe(false);
    expect(hash.setArchiveHash).toHaveBeenCalled();
  });

  it('loads archived conversations on first open', () => {
    navigateToArchive();
    expect(sidebar.loadArchivedConversations).toHaveBeenCalled();
  });

  it('renders the already loaded archive without loading it again', () => {
    useStore.setState({ archivedConversations: [conv('a', { archived: true })] });

    navigateToArchive();

    expect(sidebar.loadArchivedConversations).not.toHaveBeenCalled();
    expect(sidebar.renderConversationsList).toHaveBeenCalled();
  });
});

describe('leaveArchiveView', () => {
  it('leaves the archive view and stops its infinite scroll', () => {
    useStore.setState({ isArchiveView: true });

    leaveArchiveView();

    expect(useStore.getState().isArchiveView).toBe(false);
    expect(sidebar.cleanupArchiveInfiniteScroll).toHaveBeenCalled();
    expect(sidebar.renderConversationsList).toHaveBeenCalled();
  });

  it('restores the URL of the open conversation', () => {
    useStore.setState({ isArchiveView: true, currentConversation: conv('a') });

    leaveArchiveView();

    expect(hash.setConversationHash).toHaveBeenCalledWith('a', { replace: true });
    expect(hash.clearConversationHash).not.toHaveBeenCalled();
  });

  it('goes back home when a not yet saved conversation is open', () => {
    useStore.setState({ isArchiveView: true, currentConversation: conv('temp-1') });

    leaveArchiveView();

    expect(hash.setConversationHash).not.toHaveBeenCalled();
    expect(hash.clearConversationHash).toHaveBeenCalled();
  });

  it('goes back home when no conversation is open', () => {
    useStore.setState({ isArchiveView: true });

    leaveArchiveView();

    expect(hash.clearConversationHash).toHaveBeenCalled();
  });
});
