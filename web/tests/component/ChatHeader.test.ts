/**
 * Component tests for ChatHeader
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { createChatHeader, renderChatHeader, updateChatHeaderTitle } from '@/components/ChatHeader';

describe('ChatHeader', () => {
  beforeEach(() => {
    document.body.innerHTML = '<header id="chat-header" class="chat-header hidden"></header>';
  });

  it('renders title, cost chip and actions', () => {
    const action = document.createElement('button');
    action.className = 'test-action';
    renderChatHeader({ title: 'My chat', actions: [action] });
    const header = document.getElementById('chat-header')!;
    expect(header.classList.contains('hidden')).toBe(false);
    expect(header.querySelector('.chat-header-title')!.textContent).toBe('My chat');
    expect(header.querySelector('.test-action')).not.toBeNull();
    expect(header.querySelector('#conversation-cost')).not.toBeNull();
  });

  it('hides when rendered with null', () => {
    renderChatHeader({ title: 'x' });
    renderChatHeader(null);
    expect(document.getElementById('chat-header')!.classList.contains('hidden')).toBe(true);
  });

  it('commits inline rename on Enter', () => {
    const onRenameCommit = vi.fn();
    renderChatHeader({ title: 'Old', onRenameCommit });
    const title = document.querySelector<HTMLElement>('.chat-header-title')!;
    title.click();
    const input = document.querySelector<HTMLInputElement>('.chat-header-title-input')!;
    input.value = 'New title';
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    expect(onRenameCommit).toHaveBeenCalledWith('New title');
    expect(document.querySelector('.chat-header-title')!.textContent).toBe('New title');
  });

  it('cancels inline rename on Escape', () => {
    const onRenameCommit = vi.fn();
    renderChatHeader({ title: 'Old', onRenameCommit });
    const title = document.querySelector<HTMLElement>('.chat-header-title')!;
    title.click();
    const input = document.querySelector<HTMLInputElement>('.chat-header-title-input')!;
    input.value = 'Discarded';
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(onRenameCommit).not.toHaveBeenCalled();
    expect(document.querySelector('.chat-header-title')!.textContent).toBe('Old');
  });

  it('renders back button and emoji for program variant', () => {
    const onBack = vi.fn();
    renderChatHeader({
      title: 'Pushups',
      emoji: '🤼',
      onBack,
      extraClass: 'sports-program-header',
    });
    const header = document.getElementById('chat-header')!;
    expect(header.classList.contains('sports-program-header')).toBe(true);
    expect(header.querySelector('.chat-header-emoji')!.textContent).toBe('🤼');
    header.querySelector<HTMLElement>('.chat-header-back')!.click();
    expect(onBack).toHaveBeenCalled();
  });

  it('clears variant class when re-rendered without it', () => {
    renderChatHeader({ title: 'Pushups', extraClass: 'sports-program-header' });
    renderChatHeader({ title: 'Plain chat' });
    const header = document.getElementById('chat-header')!;
    expect(header.classList.contains('sports-program-header')).toBe(false);
  });

  it('updates title in place', () => {
    renderChatHeader({ title: 'One' });
    updateChatHeaderTitle('Two');
    expect(document.querySelector('.chat-header-title')!.textContent).toBe('Two');
  });

  it('createChatHeader returns a detached element without touching the mount', () => {
    const el = createChatHeader({ title: 'Detached' });
    expect(el.querySelector('.chat-header-title')!.textContent).toBe('Detached');
    expect(document.getElementById('chat-header')!.children.length).toBe(0);
  });
});
