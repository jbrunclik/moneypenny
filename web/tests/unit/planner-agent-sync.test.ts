/**
 * The planner and the viewed agent conversation are polled outside the
 * regular conversation sync. The planner poll reports a deletion, a reset
 * (last_reset changed) and new messages - only while the planner is shown,
 * and never for the first poll's baseline or this device's own turn. The
 * agent poll reports new messages in the viewed agent conversation and is
 * skipped while that conversation streams. A failed poll is swallowed.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const plannerApi = vi.hoisted(() => ({ sync: vi.fn() }));
const agentsApi = vi.hoisted(() => ({ syncConversation: vi.fn() }));

vi.mock('@/api/planner', () => ({ planner: plannerApi }));
vi.mock('@/api/agents', () => ({ agents: agentsApi }));

import { PlannerSync } from '@/sync/planner-sync';
import { AgentConversationSync } from '@/sync/agent-conversation-sync';
import { SyncState, type SyncManagerCallbacks } from '@/sync/sync-state';
import { useStore } from '@/state/store';
import type { Conversation } from '@/types/api';

function callbacks(): SyncManagerCallbacks & Record<string, ReturnType<typeof vi.fn>> {
  return {
    onConversationsUpdated: vi.fn(),
    onCurrentConversationDeleted: vi.fn(),
    onCurrentConversationExternalUpdate: vi.fn(),
    onPlannerDeleted: vi.fn(),
    onPlannerReset: vi.fn(),
    onPlannerExternalUpdate: vi.fn(),
    onAgentConversationExternalUpdate: vi.fn(),
  };
}

function plannerAnswer(messageCount: number, lastReset: string | null = null) {
  return { conversation: { message_count: messageCount, last_reset: lastReset } };
}

function conv(id: string): Conversation {
  return { id, title: id, model: 'm', created_at: '', updated_at: '' };
}

beforeEach(() => {
  vi.clearAllMocks();
  useStore.setState({ isPlannerView: true, currentConversation: null });
});

describe('PlannerSync', () => {
  let cb: ReturnType<typeof callbacks>;
  let sync: PlannerSync;

  beforeEach(() => {
    cb = callbacks();
    sync = new PlannerSync(cb);
  });

  async function poll(answer: unknown): Promise<void> {
    plannerApi.sync.mockResolvedValueOnce(answer);
    await sync.sync();
  }

  it('takes the first poll as the baseline', async () => {
    await poll(plannerAnswer(4, 't1'));
    expect(cb.onPlannerExternalUpdate).not.toHaveBeenCalled();
    expect(cb.onPlannerReset).not.toHaveBeenCalled();
  });

  it('reports new messages while the planner is shown', async () => {
    await poll(plannerAnswer(4));
    await poll(plannerAnswer(6));
    expect(cb.onPlannerExternalUpdate).toHaveBeenCalledWith(6);
  });

  it('does not report a same or lower count', async () => {
    await poll(plannerAnswer(4));
    await poll(plannerAnswer(4));
    await poll(plannerAnswer(2));
    expect(cb.onPlannerExternalUpdate).not.toHaveBeenCalled();
  });

  it('stays quiet when the planner is not shown, but moves the baseline', async () => {
    await poll(plannerAnswer(4));
    useStore.setState({ isPlannerView: false });
    await poll(plannerAnswer(6));
    expect(cb.onPlannerExternalUpdate).not.toHaveBeenCalled();

    useStore.setState({ isPlannerView: true });
    await poll(plannerAnswer(6));
    expect(cb.onPlannerExternalUpdate).not.toHaveBeenCalled();
  });

  it('reports a reset in another tab', async () => {
    await poll(plannerAnswer(4, 't1'));
    await poll(plannerAnswer(0, 't2'));
    expect(cb.onPlannerReset).toHaveBeenCalledTimes(1);
  });

  it('reports a deletion once, only after the planner existed', async () => {
    await poll({ conversation: null });
    expect(cb.onPlannerDeleted).not.toHaveBeenCalled();

    await poll(plannerAnswer(4));
    await poll({ conversation: null });
    await poll({ conversation: null });
    expect(cb.onPlannerDeleted).toHaveBeenCalledTimes(1);
  });

  it('a baseline set on load catches a change before the first poll', async () => {
    sync.setBaseline(4);
    await poll(plannerAnswer(5));
    expect(cb.onPlannerExternalUpdate).toHaveBeenCalledWith(5);
  });

  it('a baseline set on load ignores the reset this device made', async () => {
    await poll(plannerAnswer(4, 't1'));
    sync.setBaseline(0);
    await poll(plannerAnswer(0, 't2'));
    expect(cb.onPlannerReset).not.toHaveBeenCalled();
  });

  it("does not report this device's own turn", async () => {
    await poll(plannerAnswer(4));
    sync.noteOwnCount(6);
    await poll(plannerAnswer(6));
    expect(cb.onPlannerExternalUpdate).not.toHaveBeenCalled();
  });

  it('an own count before any baseline does not become one', async () => {
    sync.noteOwnCount(6);
    await poll(plannerAnswer(8));
    expect(cb.onPlannerExternalUpdate).not.toHaveBeenCalled();
  });

  it('clear() forgets the baseline', async () => {
    await poll(plannerAnswer(4));
    sync.clear();
    await poll(plannerAnswer(6));
    expect(cb.onPlannerExternalUpdate).not.toHaveBeenCalled();
  });

  it('swallows a failed poll', async () => {
    plannerApi.sync.mockRejectedValueOnce(new Error('offline'));
    await expect(sync.sync()).resolves.toBeUndefined();
  });
});

describe('AgentConversationSync', () => {
  let state: SyncState;
  let sync: AgentConversationSync;

  beforeEach(() => {
    state = new SyncState(callbacks(), { info: vi.fn(), warning: vi.fn() }, vi.fn());
    sync = new AgentConversationSync(state);
  });

  const onUpdate = () => state.callbacks.onAgentConversationExternalUpdate as ReturnType<typeof vi.fn>;

  async function poll(messageCount: number | null): Promise<void> {
    agentsApi.syncConversation.mockResolvedValueOnce({
      conversation: messageCount === null ? null : { message_count: messageCount },
    });
    await sync.sync();
  }

  it('does not poll without a viewed agent', async () => {
    await sync.sync();
    expect(agentsApi.syncConversation).not.toHaveBeenCalled();
  });

  it('reports new messages beyond the baseline set on viewing', async () => {
    sync.setViewedAgent('agent-1', 3);
    await poll(5);
    expect(agentsApi.syncConversation).toHaveBeenCalledWith('agent-1');
    expect(onUpdate()).toHaveBeenCalledWith(5);
  });

  it('takes the first poll as the baseline when viewing set none', async () => {
    sync.setViewedAgent('agent-1');
    await poll(5);
    expect(onUpdate()).not.toHaveBeenCalled();
    await poll(7);
    expect(onUpdate()).toHaveBeenCalledWith(7);
  });

  it('skips the poll while the viewed conversation streams', async () => {
    useStore.setState({ currentConversation: conv('c1') });
    state.streamingConversations.add('c1');
    sync.setViewedAgent('agent-1', 3);
    await sync.sync();
    expect(agentsApi.syncConversation).not.toHaveBeenCalled();
  });

  it("does not report this device's own turn", async () => {
    sync.setViewedAgent('agent-1', 3);
    sync.noteOwnCount(5);
    await poll(5);
    expect(onUpdate()).not.toHaveBeenCalled();
  });

  it('keeps the baseline when the conversation is not found', async () => {
    sync.setViewedAgent('agent-1', 3);
    await poll(null);
    await poll(4);
    expect(onUpdate()).toHaveBeenCalledWith(4);
  });

  it('stops polling after leaving the agent', async () => {
    sync.setViewedAgent('agent-1', 3);
    sync.setViewedAgent(null);
    await sync.sync();
    expect(agentsApi.syncConversation).not.toHaveBeenCalled();
  });

  it('swallows a failed poll', async () => {
    sync.setViewedAgent('agent-1', 3);
    agentsApi.syncConversation.mockRejectedValueOnce(new Error('offline'));
    await expect(sync.sync()).resolves.toBeUndefined();
  });
});
