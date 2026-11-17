/**
 * `#/new?text=` opens a new chat with the text in the composer (iOS has no
 * share target for a home-screen app; a Shortcut can open this link).
 */
import { describe, it, expect, vi } from 'vitest';

vi.mock('@/core/conversation', () => ({ createConversation: vi.fn() }));
vi.mock('@/components/MessageInput', () => ({ updateSendButtonState: vi.fn() }));

import { sharedText } from '@/core/share-link';
import { parseHash } from '@/router/deeplink';

describe('sharedText', () => {
  it('reads the text, URL-decoded', () => {
    expect(sharedText('#/new?text=Shrn%20tenhle%20%C4%8Dl%C3%A1nek')).toBe('Shrn tenhle článek');
    expect(sharedText('#/new?text=a+b')).toBe('a b');
  });

  it('opens an empty new chat for a bare #/new', () => {
    expect(sharedText('#/new')).toBe('');
  });

  it('is null for any other hash', () => {
    expect(sharedText('#/newsletter')).toBeNull();
    expect(sharedText('#/conversations/abc')).toBeNull();
    expect(sharedText('')).toBeNull();
  });
});

describe('parseHash', () => {
  it('knows the new-chat route, so the router leaves it alone', () => {
    expect(parseHash('#/new?text=x').type).toBe('new');
    expect(parseHash('#/new').type).toBe('new');
    expect(parseHash('#/newsletter').type).toBe('unknown');
  });
});
