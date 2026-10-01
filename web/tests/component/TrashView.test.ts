/**
 * Tests for the trash view rendering (sidebar full-view, like the archive).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import { renderTrashView, renderTrashEntry, daysLeftLabel } from '@/components/TrashView';
import type { Conversation } from '@/types/api';

vi.mock('@/api/conversations', () => ({
  conversations: { listTrash: vi.fn() },
}));

function trashed(id: string, title: string, purgeAt: string): Conversation {
  return { id, title, model: 'm', created_at: '', updated_at: '', purge_at: purgeAt };
}

function setTrash(convs: Conversation[]): void {
  useStore.setState({
    trashedConversations: convs,
    trashPagination: { nextCursor: null, hasMore: false, totalCount: convs.length, isLoadingMore: false },
  });
}

describe('daysLeftLabel', () => {
  const now = new Date('2026-10-01T12:00:00');

  it('rounds partial days up', () => {
    expect(daysLeftLabel('2026-10-03T08:00:00', now)).toBe('2 days left');
  });

  it('uses the singular for one day', () => {
    expect(daysLeftLabel('2026-10-02T06:00:00', now)).toBe('1 day left');
  });

  it('never goes negative', () => {
    expect(daysLeftLabel('2026-09-30T00:00:00', now)).toBe('Deleting soon');
  });

  it('is empty without a purge date', () => {
    expect(daysLeftLabel(null, now)).toBe('');
  });
});

describe('renderTrashView', () => {
  let container: HTMLDivElement;

  beforeEach(() => {
    container = document.createElement('div');
  });

  it('renders rows with restore and delete-forever actions and escaped titles', () => {
    setTrash([trashed('c1', 'Gone <b>', '2099-01-01T00:00:00')]);
    renderTrashView(container);

    expect(container.querySelector('.trash-view-header')).not.toBeNull();
    expect(container.querySelector('[data-restore-id="c1"]')).not.toBeNull();
    expect(container.querySelector('[data-delete-forever-id="c1"]')).not.toBeNull();
    expect(container.querySelector('[data-empty-trash]')).not.toBeNull();
    expect(container.innerHTML).toContain('Gone &lt;b&gt;');
    expect(container.querySelector('.trash-days-left')?.textContent).toMatch(/days left/);
  });

  it('rows do not open the conversation', () => {
    setTrash([trashed('c1', 'Gone', '2099-01-01T00:00:00')]);
    renderTrashView(container);
    expect(container.querySelector('.conversation-item[role="button"]')).toBeNull();
  });

  it('shows an empty state without the empty-trash action', () => {
    setTrash([]);
    renderTrashView(container);
    expect(container.textContent).toContain('Trash is empty');
    expect(container.textContent).toContain('14 days');
    expect(container.querySelector('[data-empty-trash]')).toBeNull();
  });
});

describe('renderTrashEntry', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <button class="user-menu-trash hidden"><span class="trash-count">0</span></button>`;
  });

  it('hides the menu entry when the trash is empty', () => {
    setTrash([]);
    renderTrashEntry();
    expect(document.querySelector('.user-menu-trash')?.classList.contains('hidden')).toBe(true);
  });

  it('shows the entry with the count', () => {
    setTrash([trashed('a', 'A', ''), trashed('b', 'B', '')]);
    renderTrashEntry();
    const entry = document.querySelector('.user-menu-trash');
    expect(entry?.classList.contains('hidden')).toBe(false);
    expect(entry?.querySelector('.trash-count')?.textContent).toBe('2');
  });
});
