/**
 * Selection mode in the sidebar: entering, ticking rows, select all, chrome text.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import { renderConversationsList } from '@/components/Sidebar';
import {
  enterSelectionMode,
  exitSelectionMode,
  handleSelectionListClick,
  initSidebarSelection,
  renderSelectionChrome,
} from '@/components/SidebarSelection';
import type { Conversation } from '@/types/api';

vi.mock('@/api/costs', () => ({
  costs: { getMonthlyCost: vi.fn().mockResolvedValue({ formatted: '0 CZK' }) },
}));
const bulkDelete = vi.fn(() => Promise.resolve());
const leaveViews = { trash: vi.fn(), archive: vi.fn() };

function conv(id: string, extra: Partial<Conversation> = {}): Conversation {
  return { id, title: id, model: 'm', created_at: '', updated_at: new Date().toISOString(), ...extra };
}
const s = () => useStore.getState();
const row = (id: string) => document.querySelector<HTMLElement>(`[data-conv-id="${id}"]`)!;
const click = (el: Element) => {
  const e = new MouseEvent('click', { bubbles: true });
  Object.defineProperty(e, 'target', { value: el });
  return handleSelectionListClick(e);
};

beforeEach(() => {
  // The sidebar parts of the app shell (core/startup/app-shell.ts)
  document.body.innerHTML = `
    <aside id="sidebar" class="sidebar">
      <div class="sidebar-header"></div>
      <div id="selection-bar" class="selection-bar hidden">
        <button id="selection-cancel" type="button">Cancel</button>
        <span class="selection-count">0 selected</span>
        <button id="selection-all" type="button">Select all</button>
      </div>
      <div id="search-container"></div>
      <div id="conversations-list" class="conversations-list"></div>
      <div class="sidebar-footer"><div id="user-info"></div></div>
      <div id="selection-footer" class="selection-footer hidden">
        <button id="selection-trash" type="button" disabled>Move 0 to trash</button>
      </div>
    </aside>`;
  useStore.setState({
    conversations: [conv('p', { pinned: true }), conv('a'), conv('b')],
    conversationsPagination: { nextCursor: null, hasMore: false, totalCount: 3, isLoadingMore: false },
    currentConversation: null,
    isLoading: false,
    isArchiveView: false,
    isTrashView: false,
  });
  vi.clearAllMocks();
  initSidebarSelection({ bulkDelete, leaveTrashView: leaveViews.trash, leaveArchiveView: leaveViews.archive });
  exitSelectionMode();
});

describe('sidebar selection mode', () => {
  it('enter shows the bar, checkboxes and a disabled trash button', () => {
    enterSelectionMode();

    expect(document.getElementById('sidebar')!.classList.contains('selecting')).toBe(true);
    expect(document.getElementById('selection-bar')!.classList.contains('hidden')).toBe(false);
    expect(row('a').querySelector('.conversation-select')).not.toBeNull();
    expect(document.querySelector('.selection-count')!.textContent).toBe('0 selected');
    expect(document.querySelector<HTMLButtonElement>('#selection-trash')!.disabled).toBe(true);
  });

  it('clicking a row ticks it instead of opening it', () => {
    enterSelectionMode();

    expect(click(row('a').querySelector('.conversation-item')!)).toBe(true);

    expect(s().selectedIds.has('a')).toBe(true);
    expect(row('a').classList.contains('selected')).toBe(true);
    expect(row('a').querySelector('.conversation-select')!.getAttribute('aria-checked')).toBe('true');
    expect(document.querySelector('#selection-trash')!.textContent).toContain('Move 1 to trash');
    expect(s().currentConversation).toBeNull();
  });

  it('select all ticks unpinned rows and toggles to Deselect all', () => {
    enterSelectionMode();
    click(document.getElementById('selection-all')!);

    expect(row('a').classList.contains('selected')).toBe(true);
    expect(row('p').classList.contains('selected')).toBe(false);
    expect(document.querySelector('.selection-count')!.textContent).toBe('2 selected');
    expect(document.getElementById('selection-all')!.textContent).toBe('Deselect all');
  });

  it('the trash button runs bulk delete; cancel leaves selection mode', () => {
    enterSelectionMode();
    click(row('a').querySelector('.conversation-item')!);
    click(document.getElementById('selection-trash')!);
    expect(bulkDelete).toHaveBeenCalledTimes(1);

    click(document.getElementById('selection-cancel')!);
    expect(s().isSelecting).toBe(false);
    expect(row('a').querySelector('.conversation-select')).toBeNull();
  });

  it('shows Moving… while the request runs', () => {
    enterSelectionMode();
    useStore.setState({ isBulkDeleting: true });
    renderSelectionChrome();

    const btn = document.querySelector<HTMLButtonElement>('#selection-trash')!;
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain('Moving…');
  });

  it('entering from the trash or archive view leaves it properly (hash, scroll listener)', () => {
    useStore.setState({ isTrashView: true });
    enterSelectionMode();
    expect(leaveViews.trash).toHaveBeenCalledTimes(1);
    exitSelectionMode();

    useStore.setState({ isArchiveView: true });
    enterSelectionMode();
    expect(leaveViews.archive).toHaveBeenCalledTimes(1);
  });

  it('outside selection mode, rows render no checkbox', () => {
    renderConversationsList();
    expect(row('a').querySelector('.conversation-select')).toBeNull();
  });
});
