/**
 * Scheduled items in the UI: the chat header chip and its sheet, the label on
 * a turn an item delivered, and the Command Center's "From chats" lane.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import { schedules } from '@/api/schedules';
import type { Conversation, ScheduledItem } from '@/types/api';
import {
  createSchedulesPopupShell,
  initScheduleIndicator,
  updateScheduleIndicator,
} from '@/components/ScheduleIndicator';
import { renderDeliveryLabel } from '@/components/messages/delivery-label';

vi.mock('@/api/schedules', () => ({
  schedules: {
    forConversation: vi.fn(),
    remove: vi.fn(async () => {}),
    pause: vi.fn(async () => ({})),
    resume: vi.fn(async () => ({})),
    run: vi.fn(async () => ({ status: 'report' })),
  },
}));

vi.mock('@/components/Toast', () => ({
  toast: { error: vi.fn(), info: vi.fn(), warning: vi.fn(), success: vi.fn() },
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
    standing: false,
    paused_reason: null,
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

  it('offers Run for a standing job and runs it', async () => {
    await show([item({ id: 'job-1', kind: 'recurring', standing: true })]);
    const sheet = openSheet();
    const run = sheet.querySelector<HTMLButtonElement>('.schedule-item-run');
    expect(run).not.toBeNull();
    run!.click();
    await vi.waitFor(() => expect(schedules.run).toHaveBeenCalledWith('job-1'));
  });

  it('shows Run as busy while the job runs', async () => {
    let finish: (value: { status: string }) => void = () => {};
    vi.mocked(schedules.run).mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));
    await show([item({ id: 'job-1', kind: 'recurring', standing: true })]);
    const run = openSheet().querySelector<HTMLButtonElement>('.schedule-item-run')!;
    run.click();
    await vi.waitFor(() => expect(run.disabled).toBe(true));
    expect(run.getAttribute('aria-label')).toBe('Running…');
    expect(run.classList.contains('is-running')).toBe(true);
    finish({ status: 'report' });
  });

  it('actions are labelled icon buttons, as in the job list', async () => {
    await show([item({ id: 'w1', kind: 'watcher' })]);
    const pause = openSheet().querySelector<HTMLButtonElement>('.schedule-item-pause')!;
    const cancel = openSheet().querySelector<HTMLButtonElement>('.schedule-item-cancel')!;
    expect(pause.querySelector('svg')).not.toBeNull();
    expect([pause.getAttribute('aria-label'), cancel.getAttribute('aria-label')]).toEqual(['Pause', 'Cancel']);
  });

  it('says when a hand-started run failed', async () => {
    const { toast } = await import('@/components/Toast');
    vi.mocked(schedules.run).mockResolvedValueOnce({ status: 'failed' });
    await show([item({ id: 'job-1', kind: 'recurring', standing: true })]);
    openSheet().querySelector<HTMLButtonElement>('.schedule-item-run')!.click();
    await vi.waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it('has no Run for a light item', async () => {
    await show([item({ kind: 'recurring' })]);
    expect(openSheet().querySelector('.schedule-item-run')).toBeNull();
  });

  it('says a job paused after failing', async () => {
    await show([item({ kind: 'recurring', standing: true, status: 'paused', paused_reason: 'failures' })]);
    const meta = openSheet().querySelector('.schedule-item-meta')!.textContent;
    expect(meta).toContain('paused after failing');
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
    expect(rows[1]?.querySelector('.schedule-item-pause')?.getAttribute('aria-label')).toBe('Pause');
  });

  it('a paused item offers resume', async () => {
    await show([item({ kind: 'watcher', status: 'paused' })]);
    const button = openSheet().querySelector<HTMLButtonElement>('.schedule-item-pause')!;
    expect(button.getAttribute('aria-label')).toBe('Resume');
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
