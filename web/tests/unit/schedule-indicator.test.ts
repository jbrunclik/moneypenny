/**
 * Scheduled items in the UI: the chat header chip and its sheet, the label on
 * a turn an item delivered, and the Command Center's "From chats" lane.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import { schedules } from '@/api/schedules';
import type { CommandCenterResponse, Conversation, ScheduledItem } from '@/types/api';
import {
  createSchedulesPopupShell,
  initScheduleIndicator,
  updateScheduleIndicator,
} from '@/components/ScheduleIndicator';
import { renderDeliveryLabel } from '@/components/messages/delivery-label';
import { renderCommandCenter } from '@/components/CommandCenter';

vi.mock('@/api/schedules', () => ({
  schedules: {
    forConversation: vi.fn(),
    remove: vi.fn(async () => {}),
    pause: vi.fn(async () => ({})),
    resume: vi.fn(async () => ({})),
  },
}));

const CONV_ID = 'conv-1';

function item(extra: Partial<ScheduledItem> = {}): ScheduledItem {
  return {
    id: 'i1',
    conversation_id: CONV_ID,
    conversation_title: "Dog's tail",
    kind: 'check_in',
    title: "How's the tail looking?",
    when: 'Fri 13 Nov 2026 18:00',
    ends: 'then done',
    status: 'active',
    next_run_at: '2026-11-13T17:00:00.000000+00:00',
    ...extra,
  };
}

async function show(items: ScheduledItem[]): Promise<HTMLElement> {
  vi.mocked(schedules.forConversation).mockResolvedValue({ conversation_id: CONV_ID, items });
  await updateScheduleIndicator(CONV_ID);
  return document.getElementById('conversation-schedules-mobile')!;
}

function openSheet(): HTMLElement {
  document.getElementById('conversation-schedules-mobile')!.click();
  return document.getElementById('schedules-popup')!;
}

describe('ScheduleIndicator', () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    document.body.innerHTML = `
      <header class="mobile-header">
        <button id="conversation-schedules-mobile" class="chat-header-schedules hidden"></button>
      </header>
    `;
    document.body.appendChild(createSchedulesPopupShell());
    useStore.setState({ currentConversation: { id: CONV_ID } as Conversation });
    initScheduleIndicator();
    await updateScheduleIndicator(null);
  });

  it('is hidden when the chat has no items', async () => {
    const chip = await show([]);
    expect(chip.classList.contains('hidden')).toBe(true);
  });

  it('shows the count', async () => {
    const chip = await show([item(), item({ id: 'i2', kind: 'watcher' })]);
    expect(chip.classList.contains('hidden')).toBe(false);
    expect(chip.textContent).toContain('2');
    expect(chip.getAttribute('aria-label')).toBe('2 scheduled in this chat');
  });

  it('lists each item with when and how it ends', async () => {
    await show([item()]);
    const sheet = openSheet();
    expect(sheet.classList.contains('hidden')).toBe(false);
    expect(sheet.textContent).toContain("How's the tail looking?");
    expect(sheet.textContent).toContain('Fri 13 Nov 2026 18:00');
    expect(sheet.textContent).toContain('then done');
  });

  it('offers pause only for watchers and recurring checks', async () => {
    await show([item(), item({ id: 'w1', kind: 'watcher', title: 'Job board' })]);
    const sheet = openSheet();
    const rows = sheet.querySelectorAll('.schedule-item');
    expect(rows[0]?.querySelector('.schedule-item-pause')).toBeNull();
    expect(rows[1]?.querySelector('.schedule-item-pause')?.textContent).toBe('Pause');
  });

  it('a paused item offers resume', async () => {
    await show([item({ kind: 'watcher', status: 'paused' })]);
    const button = openSheet().querySelector<HTMLButtonElement>('.schedule-item-pause')!;
    expect(button.textContent).toBe('Resume');
    button.click();
    await vi.waitFor(() => expect(schedules.resume).toHaveBeenCalledWith('i1'));
  });

  it('cancel removes the item and refreshes the chip', async () => {
    await show([item()]);
    vi.mocked(schedules.forConversation).mockResolvedValue({ conversation_id: CONV_ID, items: [] });

    openSheet().querySelector<HTMLButtonElement>('.schedule-item-cancel')!.click();

    await vi.waitFor(() => expect(schedules.remove).toHaveBeenCalledWith('i1'));
    await vi.waitFor(() =>
      expect(document.getElementById('conversation-schedules-mobile')!.classList.contains('hidden')).toBe(true)
    );
  });

  it("ignores a response for a chat the user already left", async () => {
    vi.mocked(schedules.forConversation).mockResolvedValue({ conversation_id: CONV_ID, items: [item()] });
    useStore.setState({ currentConversation: { id: 'other' } as Conversation });
    await updateScheduleIndicator(CONV_ID);
    expect(document.getElementById('conversation-schedules-mobile')!.classList.contains('hidden')).toBe(true);
  });
});

describe('renderDeliveryLabel', () => {
  it('shows the label', () => {
    const el = renderDeliveryLabel({ kind: 'check_in', label: 'Check-in · Fri 18:00' });
    expect(el.className).toContain('message-delivery');
    expect(el.querySelector('.message-delivery-text')?.textContent).toBe('Check-in · Fri 18:00');
  });
});

describe('Command Center "From chats" lane', () => {
  function payload(chatItems: ScheduledItem[]): CommandCenterResponse {
    return {
      agents: [],
      pending_approvals: [],
      recent_executions: [],
      total_unread: 0,
      agents_waiting: 0,
      agents_with_errors: 0,
      chat_items: chatItems,
    } as unknown as CommandCenterResponse;
  }

  function render(chatItems: ScheduledItem[]) {
    const refresh = vi.fn(async () => {});
    const noop = vi.fn(async () => {});
    const el = renderCommandCenter(payload(chatItems), refresh, noop, noop, noop, vi.fn(), vi.fn());
    return { el, refresh };
  }

  it('is hidden with no items', () => {
    expect(render([]).el.querySelector('.command-center-section--chat-items')).toBeNull();
  });

  it('sits above the agents with a link to each chat', () => {
    const { el } = render([item()]);
    const section = el.querySelector('.command-center-section--chat-items')!;
    expect(section.textContent).toContain('From chats');
    const sections = [...el.querySelectorAll('.command-center > div')];
    expect(sections.indexOf(section)).toBeLessThan(sections.indexOf(el.querySelector('.command-center-section--agents')!));
    const link = section.querySelector<HTMLAnchorElement>('.chat-item-chat')!;
    expect(link.getAttribute('href')).toBe(`#/conversations/${CONV_ID}`);
    expect(link.textContent).toBe("Dog's tail");
    expect(section.textContent).toContain('Fri 13 Nov 2026 18:00 · then done');
  });

  it('cancel removes the item and refreshes the dashboard', async () => {
    const { el, refresh } = render([item()]);
    el.querySelector<HTMLButtonElement>('.chat-item-cancel')!.click();
    await vi.waitFor(() => expect(schedules.remove).toHaveBeenCalledWith('i1'));
    await vi.waitFor(() => expect(refresh).toHaveBeenCalled());
  });
});
