/**
 * Tests for the empty-conversation welcome message.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '@/state/store';
import { createWelcomeMessage } from '@/components/WelcomeMessage';
import type { User } from '@/types/api';

function heading(): string {
  return createWelcomeMessage().querySelector('h2')?.textContent ?? '';
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

  it('keeps the name as text', () => {
    useStore.setState({ user: { name: '<b>Eve</b> & co' } as User });
    const welcome = createWelcomeMessage();
    expect(welcome.className).toBe('welcome-message');
    expect(welcome.querySelector('b')).toBeNull();
    expect(welcome.querySelector('h2')?.textContent).toBe('What’s on your mind, <b>Eve</b>?');
  });
});
