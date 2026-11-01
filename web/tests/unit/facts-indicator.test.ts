/**
 * Unit tests for the conversation facts chip and its read-only popup.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import { conversations } from '@/api/conversations';
import type { Conversation, ConversationFactsResponse } from '@/types/api';
import { createFactsPopupShell, initFactsIndicator, updateFactsIndicator } from '@/components/FactsIndicator';

vi.mock('@/api/conversations', () => ({
  conversations: { getFacts: vi.fn() },
}));

const CONV_ID = 'conv-1';

function response(overrides: Partial<ConversationFactsResponse> = {}): ConversationFactsResponse {
  return {
    conversation_id: CONV_ID,
    enabled: true,
    max_count: 30,
    facts: [
      { key: 'walls', text: 'All partitions are reinforced concrete', updated_at: '2026-11-01T10:00:00.000000+00:00' },
      { key: 'blinds', text: 'Blackout blinds already installed', updated_at: '2026-11-01T10:01:00.000000+00:00' },
    ],
    ...overrides,
  };
}

async function show(r: ConversationFactsResponse): Promise<HTMLElement> {
  vi.mocked(conversations.getFacts).mockResolvedValue(r);
  await updateFactsIndicator(CONV_ID);
  return document.getElementById('conversation-facts-mobile')!;
}

describe('FactsIndicator', () => {
  beforeEach(async () => {
    document.body.innerHTML = `
      <header class="mobile-header">
        <button id="conversation-facts-mobile" class="chat-header-facts hidden"></button>
      </header>
    `;
    document.body.appendChild(createFactsPopupShell());
    useStore.setState({ currentConversation: { id: CONV_ID } as Conversation });
    await updateFactsIndicator(null);
  });

  it('shows the count', async () => {
    const chip = await show(response());
    expect(chip.classList.contains('hidden')).toBe(false);
    expect(chip.textContent).toContain('2');
    expect(chip.getAttribute('aria-label')).toBe('2 facts settled in this conversation');
  });

  it('is hidden with no facts', async () => {
    const chip = await show(response({ facts: [] }));
    expect(chip.classList.contains('hidden')).toBe(true);
  });

  it('is hidden when the feature is off', async () => {
    const chip = await show(response({ enabled: false, facts: [] }));
    expect(chip.classList.contains('hidden')).toBe(true);
  });

  it('ignores a response for a conversation no longer open', async () => {
    vi.mocked(conversations.getFacts).mockImplementation(async () => {
      useStore.setState({ currentConversation: { id: 'conv-2' } as Conversation });
      return response();
    });
    await updateFactsIndicator(CONV_ID);
    expect(document.getElementById('conversation-facts-mobile')!.classList.contains('hidden')).toBe(true);
  });

  it('opens a read-only popup listing the facts', async () => {
    initFactsIndicator();
    const chip = await show(response());
    chip.click();

    const popup = document.getElementById('facts-popup')!;
    expect(popup.textContent).toContain('walls');
    expect(popup.textContent).toContain('Blackout blinds already installed');
    expect(popup.textContent).toContain('To change a fact, tell Moneypenny in the chat.');
    expect(popup.querySelector('input, textarea, [contenteditable]')).toBeNull();
  });
});
