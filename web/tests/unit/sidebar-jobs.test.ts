/**
 * The sidebar's clock: a chat with reminders, watchers or recurring checks
 * shows it (the count from two on), as the chat header's chip does.
 */
import { describe, expect, it } from 'vitest';
import { useStore } from '@/state/store';
import { renderConversationsList } from '@/components/Sidebar';
import type { Conversation } from '@/types/api';

function conv(id: string, scheduled: number | null): Conversation {
  return { id, title: id, model: 'm', created_at: '', updated_at: '', scheduled_count: scheduled } as Conversation;
}

describe('sidebar job clock', () => {
  it('marks chats with jobs, with the count from two on', () => {
    document.body.innerHTML = '<div id="conversations-list"></div>';
    useStore.setState({ conversations: [conv('one', 1), conv('two', 2), conv('none', null)] });

    renderConversationsList();

    const clock = (id: string) => document.querySelector(`[data-conv-id="${id}"] .conversation-jobs`);
    expect(clock('one')?.textContent?.trim()).toBe('');
    expect(clock('one')?.getAttribute('title')).toBe('1 scheduled job');
    expect(clock('two')?.textContent?.trim()).toBe('2');
    expect(clock('none')).toBeNull();
  });
});
