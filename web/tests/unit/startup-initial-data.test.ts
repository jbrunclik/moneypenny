/**
 * Loading the signed-in user's data (core/startup/initial-data.ts): the
 * store, the first render, the initial route and only then sync.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => {
  const state = {
    calls: [] as string[],
    listError: null as Error | null,
    todoistDown: false,
    /** startSync's callback for "the first full sync is done" */
    onSyncStarted: undefined as (() => void) | undefined,
    /** A mock that records its name in `calls` */
    rec: (name: string) => vi.fn(() => void state.calls.push(name)),
  };
  return state;
});

vi.mock('@/api/conversations', () => ({
  conversations: {
    list: vi.fn(async () => {
      if (h.listError) throw h.listError;
      return {
        conversations: [{ id: 'c1', title: 'One', model: 'm', created_at: '', updated_at: '' }],
        pagination: { next_cursor: null, has_more: false, total_count: 1 },
      };
    }),
  },
}));
vi.mock('@/api/app', () => ({
  models: { list: vi.fn(async () => ({ models: [{ id: 'm', name: 'M' }], default: 'm' })) },
  config: { getUploadConfig: vi.fn(async () => ({ max_file_size: 1 })) },
}));
vi.mock('@/api/integrations', () => ({
  todoist: {
    getStatus: vi.fn(async () => {
      if (h.todoistDown) throw new Error('down');
      return { connected: true };
    }),
  },
  calendar: { getStatus: vi.fn(async () => ({ connected: false })) },
}));
vi.mock('@/components/MessageInput', () => ({ updateSendButtonState: h.rec('updateSendButtonState') }));
vi.mock('@/components/ModelSelector', () => ({ renderModelDropdown: h.rec('renderModelDropdown') }));
vi.mock('@/components/Sidebar', () => ({
  renderConversationsList: h.rec('renderConversationsList'),
  renderUserInfo: h.rec('renderUserInfo'),
  loadArchivedConversations: vi.fn(async () => {
    h.calls.push('loadArchivedConversations');
    throw new Error('archive is optional');
  }),
  initSidebarTimeRefresh: h.rec('initSidebarTimeRefresh'),
}));
vi.mock('@/components/SpendBanner', () => ({ refreshSpendWarning: vi.fn(async () => undefined) }));
vi.mock('@/components/Toast', () => ({ toast: { error: vi.fn() } }));
vi.mock('@/core/push', () => ({ resyncPushSubscription: vi.fn(async () => undefined) }));
vi.mock('@/core/trash', () => ({ loadTrashedConversations: h.rec('loadTrashedConversations') }));
vi.mock('@/core/startup/initial-route', () => ({
  openInitialRoute: vi.fn(async () => {
    h.calls.push(`openInitialRoute loading=${String(useStore.getState().isLoading)}`);
  }),
}));
vi.mock('@/core/startup/sync', () => ({
  startSync: vi.fn((onStarted?: () => void) => {
    h.calls.push('startSync');
    h.onSyncStarted = onStarted;
  }),
}));

import { loadInitialData } from '@/core/startup/initial-data';
import { openInitialRoute } from '@/core/startup/initial-route';
import { toast } from '@/components/Toast';
import type { InitialRoute } from '@/router/deeplink';
import { useStore } from '@/state/store';
import type { Conversation, User } from '@/types/api';

const USER = { id: 'u1', email: 'a@example.com', name: 'A' } as User;

beforeEach(() => {
  h.calls = [];
  h.listError = null;
  h.todoistDown = false;
  h.onSyncStarted = undefined;
  vi.clearAllMocks();
  useStore.setState({ user: USER, currentConversation: null, conversations: [], isLoading: false });
});

describe('loadInitialData', () => {
  it('stores the data and the integration status', async () => {
    await loadInitialData(null);
    const state = useStore.getState();
    expect(state.conversations.map((c) => c.id)).toEqual(['c1']);
    expect(state.models.map((m) => m.id)).toEqual(['m']);
    expect(state.user).toMatchObject({ todoist_connected: true, calendar_connected: false });
    expect(state.isLoading).toBe(false);
  });

  it('opens the initial route while loading, and starts sync only after it', async () => {
    const route = { type: 'conversation', conversationId: 'c1' } as unknown as InitialRoute;
    await loadInitialData(route);
    expect(openInitialRoute).toHaveBeenCalledWith(route);
    const opened = h.calls.indexOf('openInitialRoute loading=true');
    expect(opened).toBeGreaterThan(-1);
    expect(h.calls.indexOf('startSync')).toBeGreaterThan(opened);
  });

  it('keeps a new chat started while the list was loading', async () => {
    const draft = { id: 'temp-1', title: 'New Conversation', model: 'm', created_at: '', updated_at: '' } as Conversation;
    useStore.setState({ currentConversation: draft });
    await loadInitialData(null);
    expect(useStore.getState().conversations.map((c) => c.id)).toContain('temp-1');
  });

  it('treats an integration whose status fails as disconnected', async () => {
    h.todoistDown = true;
    await loadInitialData(null);
    expect(useStore.getState().user).toMatchObject({ todoist_connected: false });
    expect(toast.error).not.toHaveBeenCalled();
  });

  it('loads the trash count, except when the trash view itself is the route', async () => {
    await loadInitialData(null);
    h.onSyncStarted?.();
    expect(h.calls).toContain('loadTrashedConversations');
    h.calls = [];
    await loadInitialData({ isTrash: true } as unknown as InitialRoute);
    h.onSyncStarted?.();
    expect(h.calls).not.toContain('loadTrashedConversations');
  });

  it('loads the archive and trash lists only once the first sync has its cursor', async () => {
    // A chat trashed elsewhere between an earlier list load and the sync's
    // cursor was in neither, so the badge stayed stale (Oct 2026)
    await loadInitialData(null);
    expect(h.calls).not.toContain('loadTrashedConversations');
    expect(h.calls).not.toContain('loadArchivedConversations');
    h.onSyncStarted?.();
    expect(h.calls).toContain('loadTrashedConversations');
    expect(h.calls).toContain('loadArchivedConversations');
  });

  it('offers a refresh on failure, and still ends loading and re-renders', async () => {
    h.listError = new Error('offline');
    await loadInitialData(null);
    expect(toast.error).toHaveBeenCalledWith(
      'Failed to load data. Please refresh the page.',
      expect.objectContaining({ action: expect.objectContaining({ label: 'Refresh' }) })
    );
    expect(h.calls).not.toContain('startSync');
    expect(useStore.getState().isLoading).toBe(false);
    // Text typed during boot gets its send button back; skeletons go
    expect(h.calls).toEqual(['updateSendButtonState', 'renderConversationsList']);
  });
});
