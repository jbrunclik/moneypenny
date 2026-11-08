/**
 * A press on a sidebar row must not lose its click to a list re-render.
 *
 * A click fires only when the press and the release hit the same element. A
 * re-render between them (a stream finishing retitles its row) used to swap
 * every row, so the release landed on a new element and the tap did nothing
 * (CI run 42480482806, conversation-switch.spec.ts:291).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import { renderConversationsList } from '@/components/Sidebar';
import { LIST_PRESS_RENDER_HOLD_MAX_MS } from '@/config';
import type { Conversation } from '@/types/api';

vi.mock('@/api/costs', () => ({
  costs: { getMonthlyCost: vi.fn().mockResolvedValue({ formatted: '0 CZK' }) },
}));

function conv(id: string, title: string): Conversation {
  return { id, title, model: 'm', created_at: '', updated_at: new Date().toISOString() };
}
const row = (id: string) => document.querySelector<HTMLElement>(`[data-conv-id="${id}"]`)!;
const title = (id: string) => row(id).querySelector('.conversation-title')!.textContent;
const pointer = (type: string, target: EventTarget) =>
  target.dispatchEvent(new Event(type, { bubbles: true }));

function retitle(id: string, newTitle: string): void {
  useStore.setState({
    conversations: useStore.getState().conversations.map((c) => (c.id === id ? { ...c, title: newTitle } : c)),
  });
  renderConversationsList();
}

beforeEach(() => {
  vi.useFakeTimers();
  document.body.innerHTML = '<div id="conversations-list" class="conversations-list"></div>';
  useStore.setState({
    conversations: [conv('a', 'First'), conv('b', 'Second')],
    conversationsPagination: { nextCursor: null, hasMore: false, totalCount: 2, isLoadingMore: false },
    currentConversation: null,
    isLoading: false,
    isArchiveView: false,
    isTrashView: false,
  });
  renderConversationsList();
});

afterEach(() => {
  // Leave no press behind for the next test
  pointer('pointercancel', document);
  vi.runAllTimers();
  vi.useRealTimers();
});

describe('sidebar re-render during a press', () => {
  it('keeps the pressed row in place until the release', () => {
    const pressed = row('b').querySelector('.conversation-item')!;
    pointer('pointerdown', pressed);

    retitle('b', 'Retitled');

    expect(row('b').querySelector('.conversation-item')).toBe(pressed);
    expect(pressed.isConnected).toBe(true);
  });

  it('applies the held re-render right after the release', () => {
    pointer('pointerdown', row('b').querySelector('.conversation-item')!);
    retitle('b', 'Retitled');

    pointer('pointerup', row('b').querySelector('.conversation-item')!);
    expect(title('b')).toBe('Second');
    vi.runAllTimers();

    expect(title('b')).toBe('Retitled');
  });

  it('applies the held re-render when the press is cancelled', () => {
    pointer('pointerdown', row('b').querySelector('.conversation-item')!);
    retitle('b', 'Retitled');

    pointer('pointercancel', document);
    vi.runAllTimers();

    expect(title('b')).toBe('Retitled');
  });

  it('never holds a re-render longer than the cap', () => {
    pointer('pointerdown', row('b').querySelector('.conversation-item')!);
    retitle('b', 'Retitled');

    vi.advanceTimersByTime(LIST_PRESS_RENDER_HOLD_MAX_MS);

    expect(title('b')).toBe('Retitled');
  });

  it('renders at once without a press', () => {
    retitle('b', 'Retitled');

    expect(title('b')).toBe('Retitled');
  });
});
