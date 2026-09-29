/**
 * Unit tests for the conversation compaction indicator (header chip, in-list
 * divider, dimming, and the scroll-position contract of late insertion).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import { costs } from '@/api/costs';
import type { Conversation, ConversationCompactionResponse } from '@/types/api';
import {
  applyCompactionMarkers,
  updateCompactionIndicator,
} from '@/components/CompactionIndicator';

vi.mock('@/api/costs', () => ({
  costs: { getConversationCompaction: vi.fn() },
}));

const CONV_ID = 'conv-1';

function status(overrides: Partial<ConversationCompactionResponse> = {}): ConversationCompactionResponse {
  return {
    conversation_id: CONV_ID,
    active: true,
    summarized_count: 2,
    total_count: 4,
    generation: 1,
    generation_estimated: false,
    boundary_message_id: 'm2',
    summary: 'Earlier: **hotels**',
    ...overrides,
  };
}

function setUpDom(): HTMLElement {
  document.body.innerHTML = `
    <header class="mobile-header">
      <button id="conversation-compaction-mobile" class="chat-header-compaction hidden"></button>
    </header>
    <div id="messages">
      <div class="message user" data-message-id="m1"></div>
      <div class="message assistant" data-message-id="m2"></div>
      <div class="message user" data-message-id="m3"></div>
      <div class="message assistant" data-message-id="m4"></div>
    </div>
  `;
  return document.getElementById('messages')!;
}

async function showStatus(s: ConversationCompactionResponse): Promise<void> {
  vi.mocked(costs.getConversationCompaction).mockResolvedValue(s);
  await updateCompactionIndicator(CONV_ID);
}

describe('CompactionIndicator', () => {
  let container: HTMLElement;

  beforeEach(async () => {
    container = setUpDom();
    useStore.setState({ currentConversation: { id: CONV_ID } as Conversation });
    // Reset module state between tests
    await updateCompactionIndicator(null);
  });

  it('dims summarized messages and places the divider after the boundary', async () => {
    await showStatus(status());

    const ids = [...container.querySelectorAll<HTMLElement>('.message--compacted')].map(
      (el) => el.dataset.messageId
    );
    expect(ids).toEqual(['m1', 'm2']);
    const divider = container.querySelector('.compaction-divider');
    expect(divider?.previousElementSibling?.getAttribute('data-message-id')).toBe('m2');
    expect(divider?.textContent).toContain('2 messages above summarized');
    expect(divider?.textContent).toContain('×1');
  });

  it('shows the chip with counts and depth', async () => {
    await showStatus(status({ summarized_count: 48, total_count: 72, generation: 4 }));

    const chip = document.getElementById('conversation-compaction-mobile')!;
    expect(chip.classList.contains('hidden')).toBe(false);
    expect(chip.textContent).toContain('48/72');
    expect(chip.textContent).toContain('×4');
    expect(chip.classList.contains('compaction--deep')).toBe(true);
  });

  it('marks an estimated generation with a tilde', async () => {
    await showStatus(status({ generation: 2, generation_estimated: true }));
    expect(document.getElementById('conversation-compaction-mobile')!.textContent).toContain('×~2');
  });

  it('clears everything when compaction is inactive', async () => {
    await showStatus(status());
    await showStatus(status({ active: false, boundary_message_id: null }));

    expect(container.querySelector('.compaction-divider')).toBeNull();
    expect(container.querySelector('.message--compacted')).toBeNull();
    expect(document.getElementById('conversation-compaction-mobile')!.classList.contains('hidden')).toBe(
      true
    );
  });

  it('is idempotent across repeated application', async () => {
    await showStatus(status());
    applyCompactionMarkers(container);
    applyCompactionMarkers(container);
    expect(container.querySelectorAll('.compaction-divider')).toHaveLength(1);
  });

  it('shows no divider when the boundary message is not loaded yet', async () => {
    await showStatus(status({ boundary_message_id: 'not-loaded' }));
    expect(container.querySelector('.compaction-divider')).toBeNull();
    expect(container.querySelector('.message--compacted')).toBeNull();
    // Chip still tells the user
    expect(document.getElementById('conversation-compaction-mobile')!.classList.contains('hidden')).toBe(
      false
    );
  });

  it('ignores a response for a conversation that is no longer open', async () => {
    let resolve!: (s: ConversationCompactionResponse) => void;
    vi.mocked(costs.getConversationCompaction).mockReturnValue(
      new Promise((r) => {
        resolve = r;
      })
    );
    const pending = updateCompactionIndicator(CONV_ID);
    useStore.setState({ currentConversation: { id: 'other' } as Conversation });
    resolve(status());
    await pending;

    expect(container.querySelector('.compaction-divider')).toBeNull();
  });

  it('drops a cached status once another conversation is open', async () => {
    await showStatus(status());
    useStore.setState({ currentConversation: { id: 'other' } as Conversation });
    applyCompactionMarkers(container);
    expect(container.querySelector('.compaction-divider')).toBeNull();
  });

  it('hides the indicator when the request fails', async () => {
    await showStatus(status());
    vi.mocked(costs.getConversationCompaction).mockRejectedValue(new Error('boom'));
    await updateCompactionIndicator(CONV_ID);
    expect(container.querySelector('.compaction-divider')).toBeNull();
  });

  it('keeps the user pinned to the bottom when a late insertion shifts content', async () => {
    // jsdom has no layout: emulate a scrolled-to-bottom container
    let scrollHeight = 1000;
    Object.defineProperty(container, 'scrollHeight', { get: () => scrollHeight, configurable: true });
    Object.defineProperty(container, 'clientHeight', { value: 400, configurable: true });
    container.scrollTop = 600;
    vi.mocked(costs.getConversationCompaction).mockImplementation(async () => {
      scrollHeight = 1030; // the divider adds height
      return status();
    });

    await updateCompactionIndicator(CONV_ID);

    expect(container.scrollTop).toBe(1030);
  });

  it('keeps the first visible message in place when the user is scrolled up', async () => {
    // jsdom has no layout: m3 is the first visible message, and inserting the
    // divider above it pushes it 30px down
    Object.defineProperty(container, 'scrollHeight', { value: 3000, configurable: true });
    Object.defineProperty(container, 'clientHeight', { value: 400, configurable: true });
    container.scrollTop = 500;
    container.getBoundingClientRect = () => ({ top: 0 }) as DOMRect;
    const m3Top = (): number => (container.querySelector('.compaction-divider') ? 40 : 10);
    for (const el of container.querySelectorAll<HTMLElement>('.message')) {
      const above = el.dataset.messageId === 'm1' || el.dataset.messageId === 'm2';
      el.getBoundingClientRect = () =>
        (above ? { top: -100, bottom: -50 } : { top: m3Top(), bottom: m3Top() + 50 }) as DOMRect;
    }

    await showStatus(status());

    expect(container.scrollTop).toBe(530);
  });

  it('opens a popup with stats and the rendered summary', async () => {
    const { initCompactionIndicator, getCompactionPopupHtml } = await import(
      '@/components/CompactionIndicator'
    );
    document.body.insertAdjacentHTML('beforeend', getCompactionPopupHtml());
    initCompactionIndicator();
    await showStatus(status({ generation: 3 }));

    container.querySelector<HTMLElement>('.compaction-divider')!.click();

    const popup = document.getElementById('compaction-popup')!;
    expect(popup.classList.contains('hidden')).toBe(false);
    expect(popup.textContent).toContain('2 of 4 messages');
    expect(popup.textContent).toContain('last 2 messages');
    expect(popup.querySelector('.compaction-summary strong')?.textContent).toBe('hotels');
  });
});
