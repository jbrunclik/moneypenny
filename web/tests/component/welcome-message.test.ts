/**
 * Tests for the empty-conversation welcome message.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '@/state/store';
import { createWelcomeMessage, renderWelcomeMessageHtml } from '@/components/WelcomeMessage';
import type { User } from '@/types/api';

function heading(): string {
  const el = document.createElement('div');
  el.innerHTML = renderWelcomeMessageHtml();
  return el.querySelector('.welcome-message h2')?.textContent ?? '';
}

describe('welcome message', () => {
  beforeEach(() => useStore.setState({ user: null }));

  it('greets the user by first name', () => {
    useStore.setState({ user: { name: 'Jiří Novák' } as User });
    expect(heading()).toBe('What’s on your mind, Jiří?');
  });

  it('falls back to a nameless greeting before the user is known', () => {
    expect(heading()).toBe('What’s on your mind?');
  });

  it('escapes the name', () => {
    useStore.setState({ user: { name: '<b>Eve</b>' } as User });
    const el = document.createElement('div');
    el.innerHTML = renderWelcomeMessageHtml();
    expect(el.querySelector('b')).toBeNull();
    expect(el.querySelector('h2')?.textContent).toBe('What’s on your mind, <b>Eve</b>?');
  });

  it('builds the same element as the shell markup, the name as text', () => {
    useStore.setState({ user: { name: '<b>Eve</b> & co' } as User });
    const fromHtml = document.createElement('div');
    fromHtml.innerHTML = renderWelcomeMessageHtml();
    const welcome = createWelcomeMessage();
    expect(welcome.outerHTML).toBe(fromHtml.querySelector('.welcome-message')?.outerHTML.replace(/>\s+</g, '><'));
    expect(welcome.querySelector('b')).toBeNull();
  });
});
