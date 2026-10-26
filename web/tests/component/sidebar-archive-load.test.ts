/**
 * Loading the archived list (it also feeds the user-menu badge): overlapping
 * loads - startup, a change-log refetch, opening the view - answer out of
 * order under load, and only the newest one may set the list.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ listArchived: vi.fn() }));
vi.mock('@/api/conversations', () => ({ conversations: api, messages: {} }));

import { loadArchivedConversations } from '@/components/Sidebar';
import { useStore } from '@/state/store';
import type { Conversation } from '@/types/api';

function conv(id: string): Conversation {
  return { id, title: id, model: 'm', created_at: '', updated_at: '2026-01-01T00:00:00Z', archived: true };
}

const page = (total: number) => ({ next_cursor: null, has_more: false, total_count: total });

describe('loadArchivedConversations', () => {
  beforeEach(() => {
    useStore.setState(useStore.getInitialState(), true);
    api.listArchived.mockReset();
  });

  it('keeps the newest load when an older one answers last', async () => {
    let answerStartup!: (value: unknown) => void;
    api.listArchived
      .mockReturnValueOnce(new Promise((resolve) => (answerStartup = resolve)))
      .mockResolvedValueOnce({ conversations: [conv('a')], pagination: page(1) });

    const startup = loadArchivedConversations();
    await loadArchivedConversations();
    answerStartup({ conversations: [], pagination: page(0) });
    await startup;

    expect(useStore.getState().archivedConversations.map((c) => c.id)).toEqual(['a']);
    expect(useStore.getState().archivedPagination.totalCount).toBe(1);
  });
});
