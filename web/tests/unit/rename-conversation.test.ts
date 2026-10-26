/**
 * renameConversationTo: validation, temp conversations renamed locally,
 * archived ones updated in the archive list, failures reported.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import type { Conversation } from '@/types/api';

const api = vi.hoisted(() => ({ update: vi.fn() }));
const toastMock = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
const syncMock = vi.hoisted(() => ({ noteLocalChange: vi.fn() }));
const uiMock = vi.hoisted(() => ({ renderConversationsList: vi.fn(), updateChatTitle: vi.fn() }));

vi.mock('@/api/conversations', () => ({ conversations: api, messages: {} }));
vi.mock('@/components/Toast', () => ({ toast: toastMock }));
vi.mock('@/components/Modal', () => ({ showConfirm: vi.fn(), showPrompt: vi.fn() }));
vi.mock('@/sync/SyncManager', () => ({ getSyncManager: () => syncMock }));
vi.mock('@/components/Sidebar', () => ({
  renderConversationsList: uiMock.renderConversationsList,
  loadArchivedConversations: vi.fn(),
  cleanupArchiveInfiniteScroll: vi.fn(),
}));
vi.mock('@/components/SidebarSelection', () => ({ renderSelectionChrome: vi.fn() }));
vi.mock('@/components/messages', () => ({ renderMessages: vi.fn(), updateChatTitle: uiMock.updateChatTitle }));
vi.mock('@/components/ChatHeader', () => ({ renderChatHeader: vi.fn() }));
vi.mock('@/core/toolbar', () => ({ updateConversationCost: vi.fn() }));
vi.mock('@/router/deeplink', () => ({
  clearConversationHash: vi.fn(),
  setTrashHash: vi.fn(),
  setConversationHash: vi.fn(),
  setArchiveHash: vi.fn(),
}));

import { renameConversationTo } from '@/core/conversation-actions';

function conv(id: string, extra: Partial<Conversation> = {}): Conversation {
  return { id, title: id, model: 'm', created_at: '', updated_at: '2026-01-01T00:00:00Z', ...extra };
}
const s = () => useStore.getState();
const titleOf = (list: Conversation[], id: string) => list.find((c) => c.id === id)?.title;

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({
    conversations: [conv('a', { title: 'Old' }), conv('temp-1', { title: 'Draft' })],
    archivedConversations: [conv('z', { title: 'Archived' })],
    currentConversation: null,
  });
  api.update.mockResolvedValue({});
});

describe('renameConversationTo', () => {
  it('renames through the API, refreshes the sidebar and the open chat title', async () => {
    useStore.setState({ currentConversation: conv('a', { title: 'Old' }) });

    await renameConversationTo('a', '  New  ');

    expect(api.update).toHaveBeenCalledWith('a', { title: 'New' });
    expect(syncMock.noteLocalChange).toHaveBeenCalledTimes(2);
    expect(titleOf(s().conversations, 'a')).toBe('New');
    expect(uiMock.updateChatTitle).toHaveBeenCalledWith('New');
    expect(uiMock.renderConversationsList).toHaveBeenCalled();
    expect(toastMock.success).toHaveBeenCalledWith('Conversation renamed.');
  });

  it('leaves the chat title alone when another conversation is open', async () => {
    await renameConversationTo('a', 'New');

    expect(uiMock.updateChatTitle).not.toHaveBeenCalled();
    expect(toastMock.success).toHaveBeenCalled();
  });

  it('leaves the chat title alone when the user opens another conversation during the request', async () => {
    useStore.setState({ currentConversation: conv('a', { title: 'Old' }) });
    api.update.mockImplementation(async () => {
      useStore.setState({ currentConversation: conv('b', { title: 'Other' }) });
      return {};
    });

    await renameConversationTo('a', 'New');

    expect(uiMock.updateChatTitle).not.toHaveBeenCalled();
  });

  it('updates the chat title when the user opens the renamed conversation during the request', async () => {
    api.update.mockImplementation(async () => {
      useStore.setState({ currentConversation: conv('a', { title: 'Old' }) });
      return {};
    });

    await renameConversationTo('a', 'New');

    expect(uiMock.updateChatTitle).toHaveBeenCalledWith('New');
  });

  it('updates an archived conversation in the archive list', async () => {
    await renameConversationTo('z', 'Renamed');

    expect(titleOf(s().archivedConversations, 'z')).toBe('Renamed');
  });

  it('renames a temp conversation locally without calling the API', async () => {
    await renameConversationTo('temp-1', 'Named');

    expect(api.update).not.toHaveBeenCalled();
    expect(titleOf(s().conversations, 'temp-1')).toBe('Named');
    expect(toastMock.success).toHaveBeenCalledWith('Conversation renamed.');
  });

  it('ignores unknown ids, empty and unchanged titles', async () => {
    await renameConversationTo('missing', 'X');
    await renameConversationTo('a', '   ');
    await renameConversationTo('a', 'Old');

    expect(api.update).not.toHaveBeenCalled();
    expect(toastMock.success).not.toHaveBeenCalled();
  });

  it('rejects a title over 200 characters', async () => {
    await renameConversationTo('a', 'x'.repeat(201));

    expect(api.update).not.toHaveBeenCalled();
    expect(toastMock.error).toHaveBeenCalledWith('Conversation name is too long (max 200 characters).');
  });

  it('reports a failed API rename and keeps the old title', async () => {
    api.update.mockRejectedValue(new Error('down'));

    await renameConversationTo('a', 'New');

    expect(titleOf(s().conversations, 'a')).toBe('Old');
    expect(toastMock.error).toHaveBeenCalledWith('Failed to rename conversation. Please try again.');
  });
});
