/**
 * How the UI reacts to what the sync manager reports (core/startup/sync.ts).
 * Every handler reads the live store when it fires.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { SyncManagerCallbacks } from '@/sync/sync-state';

const h = vi.hoisted(() => ({
  callbacks: null as SyncManagerCallbacks | null,
  start: vi.fn(async () => undefined),
  fullSync: vi.fn(async () => undefined),
  incrementalSync: vi.fn(async () => undefined),
}));

vi.mock('@/sync/SyncManager', () => ({
  initSyncManager: vi.fn((callbacks: SyncManagerCallbacks) => {
    h.callbacks = callbacks;
  }),
  getSyncManager: () => ({ start: h.start, fullSync: h.fullSync, incrementalSync: h.incrementalSync }),
}));
vi.mock('@/components/ChatHeader', () => ({ renderChatHeader: vi.fn() }));
vi.mock('@/components/Sidebar', () => ({
  renderConversationsList: vi.fn(),
  loadArchivedConversations: vi.fn(async () => undefined),
}));
vi.mock('@/components/messages', () => ({ renderMessages: vi.fn(), updateChatTitle: vi.fn() }));
vi.mock('@/components/Toast', () => ({ toast: { info: vi.fn() } }));
vi.mock('@/router/deeplink', () => ({ clearConversationHash: vi.fn(), pushEmptyHash: vi.fn() }));
vi.mock('@/core/planner', () => ({ navigateToPlanner: vi.fn(async () => undefined), leavePlannerView: vi.fn() }));
vi.mock('@/core/remote-merge', () => ({ mergeExternalChanges: vi.fn(async () => undefined) }));
vi.mock('@/core/stream-recovery', () => ({
  attemptRecovery: vi.fn(),
  cancelRecovery: vi.fn(),
  hasPendingRecovery: vi.fn(),
}));
vi.mock('@/core/toolbar', () => ({ updateConversationCost: vi.fn(async () => undefined) }));
vi.mock('@/core/trash', () => ({ loadTrashedConversations: vi.fn(async () => undefined) }));

import { startSync } from '@/core/startup/sync';
import { renderChatHeader } from '@/components/ChatHeader';
import { loadArchivedConversations, renderConversationsList } from '@/components/Sidebar';
import { renderMessages, updateChatTitle } from '@/components/messages';
import { toast } from '@/components/Toast';
import { clearConversationHash, pushEmptyHash } from '@/router/deeplink';
import { leavePlannerView, navigateToPlanner } from '@/core/planner';
import { mergeExternalChanges } from '@/core/remote-merge';
import { updateConversationCost } from '@/core/toolbar';
import { loadTrashedConversations } from '@/core/trash';
import { APP_NAME } from '@/config';
import { useStore } from '@/state/store';
import type { Conversation } from '@/types/api';

const CONV = { id: 'c1', title: 'One', model: 'm', created_at: '', updated_at: '' } as Conversation;

/** startSync passes every callback, the optional ones included */
function callbacks(): Required<SyncManagerCallbacks> {
  if (!h.callbacks) throw new Error('sync not started');
  return h.callbacks as Required<SyncManagerCallbacks>;
}

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({ currentConversation: CONV, isPlannerView: false });
  startSync();
});

describe('startSync', () => {
  it('starts the manager, and a failed start is logged, not thrown', async () => {
    expect(h.start).toHaveBeenCalled();
    h.start.mockRejectedValueOnce(new Error('offline'));
    expect(() => startSync()).not.toThrow();
    await Promise.resolve();
  });

  it('exposes full and incremental sync to the E2E tests', async () => {
    await window.__testFullSync();
    await window.__testIncrementalSync();
    expect(h.fullSync).toHaveBeenCalled();
    expect(h.incrementalSync).toHaveBeenCalled();
  });
});

describe('sync callbacks', () => {
  it('re-renders the list when conversations change', () => {
    callbacks().onConversationsUpdated();
    expect(renderConversationsList).toHaveBeenCalled();
  });

  it('closes the open conversation deleted on another device', () => {
    callbacks().onCurrentConversationDeleted();
    expect(useStore.getState().currentConversation).toBeNull();
    expect(renderMessages).toHaveBeenCalledWith([]);
    expect(updateChatTitle).toHaveBeenCalledWith(APP_NAME);
    expect(renderChatHeader).toHaveBeenCalledWith(null);
    expect(updateConversationCost).toHaveBeenCalledWith(null);
    expect(clearConversationHash).toHaveBeenCalled();
  });

  it('merges another device’s changes into the open conversation', () => {
    callbacks().onCurrentConversationExternalUpdate(3);
    expect(mergeExternalChanges).toHaveBeenCalledWith('c1');
    useStore.setState({ currentConversation: null });
    callbacks().onCurrentConversationExternalUpdate(3);
    expect(mergeExternalChanges).toHaveBeenCalledTimes(1);
  });

  it('shows a rename of the open conversation', () => {
    callbacks().onCurrentConversationRenamed('Renamed');
    expect(updateChatTitle).toHaveBeenCalledWith('Renamed');
  });

  it('reloads only the archive or trash rows that changed', () => {
    callbacks().onArchiveOrTrashChanged({ archive: true, trash: false });
    expect(loadArchivedConversations).toHaveBeenCalledTimes(1);
    expect(loadTrashedConversations).not.toHaveBeenCalled();
    callbacks().onArchiveOrTrashChanged({ archive: false, trash: true });
    expect(loadTrashedConversations).toHaveBeenCalledTimes(1);
    expect(loadArchivedConversations).toHaveBeenCalledTimes(1);
  });

  it('reacts to planner changes only while the planner is open', () => {
    callbacks().onPlannerDeleted();
    callbacks().onPlannerReset();
    callbacks().onPlannerExternalUpdate(3);
    expect(toast.info).not.toHaveBeenCalled();
    expect(mergeExternalChanges).not.toHaveBeenCalled();

    // Live state, not a snapshot from startup
    useStore.setState({ isPlannerView: true });
    callbacks().onPlannerDeleted();
    expect(leavePlannerView).toHaveBeenCalled();
    expect(pushEmptyHash).toHaveBeenCalled();
    callbacks().onPlannerReset();
    expect(navigateToPlanner).toHaveBeenCalled();
    callbacks().onPlannerExternalUpdate(3);
    expect(mergeExternalChanges).toHaveBeenCalledWith('c1');
    expect(toast.info).toHaveBeenCalledTimes(2);
  });

  it('merges an agent conversation’s new messages only when one is open', () => {
    callbacks().onAgentConversationExternalUpdate(3);
    expect(mergeExternalChanges).not.toHaveBeenCalled();
    useStore.setState({ currentConversation: { ...CONV, is_agent: true } });
    callbacks().onAgentConversationExternalUpdate(3);
    expect(mergeExternalChanges).toHaveBeenCalledWith('c1');
  });
});
