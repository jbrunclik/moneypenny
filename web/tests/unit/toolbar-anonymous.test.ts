/**
 * The composer's anonymous toggle in a project chat: an anonymous chat is
 * never in a project (no project memory), so the toggle explains that
 * instead of turning on.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('@/sync/SyncManager', () => ({ getSyncManager: () => null }));
vi.mock('@/api/conversations', () => ({ conversations: { setAnonymousMode: vi.fn(() => Promise.resolve()) } }));
vi.mock('@/api/costs', () => ({ costs: {} }));
vi.mock('@/components/Toast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));
vi.mock('@/components/Sidebar', () => ({ updateMonthlyCost: vi.fn() }));
vi.mock('@/components/SpendBanner', () => ({ refreshSpendWarning: vi.fn() }));
vi.mock('@/components/CompactionIndicator', () => ({ updateCompactionIndicator: vi.fn() }));
vi.mock('@/components/FactsIndicator', () => ({ updateFactsIndicator: vi.fn() }));
vi.mock('@/components/ScheduleIndicator', () => ({ updateScheduleIndicator: vi.fn() }));

import { useStore } from '@/state/store';
import { toast } from '@/components/Toast';
import { conversations } from '@/api/conversations';
import { initToolbarButtons } from '@/core/toolbar';

function chat(id: string, projectId: string | null) {
  return { id, title: 'Wallbox', model: 'm', created_at: '', updated_at: '', project_id: projectId };
}

let button: HTMLButtonElement;

beforeEach(() => {
  vi.clearAllMocks();
  document.body.innerHTML = '<button id="anonymous-btn"></button>';
  button = document.getElementById('anonymous-btn') as HTMLButtonElement;
});

describe('the anonymous toggle', () => {
  it('stays off in a project chat and says why', () => {
    const conv = chat('c1', 'p1');
    useStore.setState({ conversations: [conv], currentConversation: conv });
    initToolbarButtons();

    button.click();

    expect(useStore.getState().getAnonymousMode('c1')).toBe(false);
    expect(button.classList.contains('active')).toBe(false);
    expect(conversations.setAnonymousMode).not.toHaveBeenCalled();
    expect(toast.info).toHaveBeenCalledWith(expect.stringContaining("can't be in a project"));
  });

  it('turns on in an ordinary chat', () => {
    const conv = chat('c2', null);
    useStore.setState({ conversations: [conv], currentConversation: conv });
    initToolbarButtons();

    button.click();

    expect(useStore.getState().getAnonymousMode('c2')).toBe(true);
    expect(conversations.setAnonymousMode).toHaveBeenCalledWith('c2', true);
  });
});
