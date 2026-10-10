/**
 * Edit-and-resend truncates the conversation server-side, then resent the
 * text by writing it into the composer and pressing send: the user's own
 * draft there was overwritten and any files attached to it went with the
 * edit. Editing a message with attachments silently deleted them (only the
 * text is resent).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useStore } from '@/state/store';

vi.mock('@/api/conversations', () => ({
  conversations: { truncate: vi.fn(() => Promise.resolve()) },
  messages: { delete: vi.fn() },
}));
vi.mock('@/components/Toast', () => ({
  toast: { info: vi.fn(), error: vi.fn(), warning: vi.fn(), success: vi.fn() },
}));
vi.mock('@/components/messages', () => ({
  hideLoadingIndicator: vi.fn(),
  removeRenderedMessagesFrom: vi.fn(),
}));
const edit = { save: (_text: string): void => {} };
vi.mock('@/components/messages/edit', () => ({
  beginInlineEdit: vi.fn((_el: HTMLElement, _text: string, opts: { onSave: (t: string) => void }) => {
    edit.save = opts.onSave;
  }),
}));
vi.mock('@/core/messaging', () => ({
  dispatchSend: vi.fn(),
  sendMessage: vi.fn(),
  sendUiMessage: vi.fn(() => Promise.resolve(true)),
}));
vi.mock('@/core/stream-send', () => ({ sendStreamingMessage: vi.fn() }));
vi.mock('@/core/batch-send', () => ({ sendBatchMessage: vi.fn() }));

import { initOutboxHandlers } from '@/core/rerun';
import { sendMessage, sendUiMessage } from '@/core/messaging';
import { conversations } from '@/api/conversations';
import { toast } from '@/components/Toast';
import { beginInlineEdit } from '@/components/messages/edit';

const PAGE = { older_cursor: null, newer_cursor: null, has_older: false, has_newer: false, total_count: 2 };
initOutboxHandlers();

function editMessage(id: string): void {
  document.dispatchEvent(new CustomEvent('message:edit', { detail: { messageId: id } }));
}

describe('edit and resend', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.innerHTML = `<textarea id="message-input">my unsent draft</textarea>
      <div class="message user" data-message-id="u1"></div>
      <div class="message user" data-message-id="u2"></div>`;
    useStore.setState({ currentConversation: { id: 'c1', title: 'T', model: 'm', created_at: '', updated_at: '' } as never });
    useStore.getState().removeActiveRequest('c1');
    useStore.getState().setMessages('c1', [
      { id: 'u1', role: 'user', content: 'Original', created_at: '2026-10-10T20:00:00' },
      {
        id: 'u2', role: 'user', content: 'With a photo', created_at: '2026-10-10T20:01:00',
        files: [{ name: 'a.jpg', type: 'image/jpeg' }],
      },
    ] as never, PAGE);
  });

  it("resends the edit without touching the composer's draft", async () => {
    editMessage('u1');
    edit.save('Edited');
    await vi.waitFor(() => expect(sendUiMessage).toHaveBeenCalledWith('Edited'));
    expect(sendMessage).not.toHaveBeenCalled();
    expect((document.getElementById('message-input') as HTMLTextAreaElement).value).toBe('my unsent draft');
  });

  it('does not edit a message with attachments (they would be lost)', () => {
    editMessage('u2');
    expect(beginInlineEdit).not.toHaveBeenCalled();
    expect(conversations.truncate).not.toHaveBeenCalled();
    expect(toast.info).toHaveBeenCalled();
  });
});
