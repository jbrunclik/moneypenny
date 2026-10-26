/**
 * Chat header for regular conversations: a temp (unsaved) conversation gets
 * only its title; a saved one gets inline rename plus pin, archive and
 * delete buttons. The pin button names the action that fits the current
 * state (Pin / Unpin) and, after toggling, re-renders the header if the
 * conversation is still open so the icon follows.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { Conversation } from '@/types/api';

type HeaderOptions = { title: string; onRenameCommit?: (title: string) => void; actions?: HTMLElement[] };

const m = vi.hoisted(() => ({
  renderChatHeader: vi.fn<(options: HeaderOptions | null) => void>(),
  deleteConversation: vi.fn(() => Promise.resolve()),
  renameConversationTo: vi.fn(() => Promise.resolve()),
  togglePinConversation: vi.fn<(id: string) => Promise<void>>(() => Promise.resolve()),
  archiveConversation: vi.fn(() => Promise.resolve()),
}));

vi.mock('@/components/ChatHeader', () => ({ renderChatHeader: m.renderChatHeader }));
vi.mock('@/core/conversation-actions', () => ({
  deleteConversation: m.deleteConversation,
  renameConversationTo: m.renameConversationTo,
  togglePinConversation: m.togglePinConversation,
}));
vi.mock('@/core/archive', () => ({ archiveConversation: m.archiveConversation }));

import { useStore } from '@/state/store';
import { renderChatHeaderForConversation } from '@/core/conversation-header';

function conv(overrides: Partial<Conversation> = {}): Conversation {
  return { id: 'c1', title: 'Chat', model: 'm', created_at: '', updated_at: '', ...overrides };
}

const lastOptions = (): HeaderOptions => {
  const options = m.renderChatHeader.mock.lastCall?.[0];
  if (!options) throw new Error('header not rendered');
  return options;
};

const action = (label: string): HTMLElement => {
  const btn = lastOptions().actions?.find((b) => b.getAttribute('aria-label') === label);
  if (!btn) throw new Error(`no "${label}" action`);
  return btn;
};

describe('renderChatHeaderForConversation', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStore.setState(useStore.getInitialState(), true);
  });

  it('gives a temp conversation a plain title without rename or actions', () => {
    renderChatHeaderForConversation(conv({ id: 'temp-1', title: 'New chat' }));
    expect(m.renderChatHeader).toHaveBeenCalledWith({ title: 'New chat' });
  });

  it('gives a saved conversation pin, archive and delete actions', () => {
    renderChatHeaderForConversation(conv());
    expect(lastOptions().title).toBe('Chat');
    expect(lastOptions().actions?.map((b) => b.getAttribute('aria-label'))).toEqual([
      'Pin conversation',
      'Archive conversation',
      'Delete conversation',
    ]);
    expect(action('Delete conversation').classList.contains('chat-header-action-danger')).toBe(true);
    expect(action('Pin conversation').querySelector('svg')).not.toBeNull();
  });

  it('offers Unpin for a pinned conversation', () => {
    useStore.getState().addConversation(conv({ pinned: true }));
    renderChatHeaderForConversation(conv());
    expect(action('Unpin conversation').title).toBe('Unpin conversation');
  });

  it('renames through the inline rename commit', () => {
    renderChatHeaderForConversation(conv());
    lastOptions().onRenameCommit?.('Better title');
    expect(m.renameConversationTo).toHaveBeenCalledWith('c1', 'Better title');
  });

  it('archives and deletes the conversation from its buttons', () => {
    renderChatHeaderForConversation(conv());
    action('Archive conversation').click();
    action('Delete conversation').click();
    expect(m.archiveConversation).toHaveBeenCalledWith('c1');
    expect(m.deleteConversation).toHaveBeenCalledWith('c1');
  });

  it('re-renders with Unpin after pinning the open conversation', async () => {
    useStore.getState().addConversation(conv());
    useStore.getState().setCurrentConversation(conv());
    m.togglePinConversation.mockImplementation((id) => {
      useStore.getState().updateConversation(id, { pinned: true });
      return Promise.resolve();
    });
    renderChatHeaderForConversation(conv());

    action('Pin conversation').click();

    expect(m.togglePinConversation).toHaveBeenCalledWith('c1');
    await vi.waitFor(() => expect(m.renderChatHeader).toHaveBeenCalledTimes(2));
    expect(action('Unpin conversation')).toBeDefined();
  });

  it('leaves the header alone when another conversation is open by the time the pin lands', async () => {
    useStore.getState().addConversation(conv());
    useStore.getState().setCurrentConversation(conv());
    let finish!: () => void;
    m.togglePinConversation.mockReturnValue(new Promise<void>((resolve) => (finish = resolve)));
    renderChatHeaderForConversation(conv());

    action('Pin conversation').click();
    useStore.getState().setCurrentConversation(conv({ id: 'c2' }));
    finish();
    await Promise.resolve();
    await Promise.resolve();

    expect(m.renderChatHeader).toHaveBeenCalledTimes(1);
  });
});
