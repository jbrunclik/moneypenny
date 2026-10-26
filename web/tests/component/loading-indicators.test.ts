import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/components/messages/turn-anchor', () => ({ anchorTurn: vi.fn() }));
vi.mock('@/utils/programmatic-scroll', () => ({ programmaticScrollToBottom: vi.fn() }));

import { anchorTurn } from '@/components/messages/turn-anchor';
import { programmaticScrollToBottom } from '@/utils/programmatic-scroll';
import {
  hideConversationLoader,
  hideLoadingIndicator,
  revealLoadingIndicator,
  showConversationLoader,
  showLoadingIndicator,
} from '@/components/messages/loading';

const container = () => document.getElementById('messages')!;
const loaders = () => document.querySelectorAll('.message-loading');

describe('message loading indicators', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="messages"></div>';
    vi.mocked(anchorTurn).mockClear();
    vi.mocked(programmaticScrollToBottom).mockClear();
  });

  it('anchors the waiting reply under the user message just sent', () => {
    container().innerHTML = '<div class="message user">Hi</div>';
    showLoadingIndicator();

    const loading = loaders()[0] as HTMLElement;
    expect(loading.querySelector('.loading-dots span')).not.toBeNull();
    expect(anchorTurn).toHaveBeenCalledWith(container(), container().firstElementChild, loading);
    expect(programmaticScrollToBottom).not.toHaveBeenCalled();
  });

  it('scrolls to the bottom when no user message precedes it', () => {
    container().innerHTML = '<div class="message assistant">Hello</div>';
    showLoadingIndicator();

    expect(anchorTurn).not.toHaveBeenCalled();
    expect(programmaticScrollToBottom).toHaveBeenCalledWith(container());
  });

  it('stays invisible while attachments upload, then reveals its dots', () => {
    showLoadingIndicator(true);
    expect(loaders()[0]!.classList.contains('awaiting-upload')).toBe(true);

    revealLoadingIndicator();
    expect(loaders()[0]!.classList.contains('awaiting-upload')).toBe(false);
  });

  it('keeps a single indicator and removes it on hide', () => {
    showLoadingIndicator();
    showLoadingIndicator();
    expect(loaders()).toHaveLength(1);

    hideLoadingIndicator();
    expect(loaders()).toHaveLength(0);
  });

  it('shows one conversation loader and hides it', () => {
    showConversationLoader();
    showConversationLoader();
    expect(container().querySelectorAll('.conversation-loader')).toHaveLength(1);
    expect(container().textContent).toContain('Loading conversation...');

    hideConversationLoader();
    expect(container().querySelector('.conversation-loader')).toBeNull();
  });

  it('does nothing without a message list', () => {
    document.body.innerHTML = '';
    showLoadingIndicator();
    showConversationLoader();
    expect(document.body.children).toHaveLength(0);
  });
});
