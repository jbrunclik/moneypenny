/**
 * A user message is plain text: newlines become line breaks, URLs become
 * links (www. gets https://), and nothing in it is markup. A URL ends where
 * a quote or angle bracket starts - "https://x.com" and <https://x.com>
 * link to https://x.com, not to a URL with the quote or bracket in it.
 */
import { describe, it, expect, vi } from 'vitest';

vi.mock('@/api/costs', () => ({ costs: { getMessageCost: vi.fn() } }));
vi.mock('@/utils/dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/dom')>();
  return { ...actual, scrollToBottom: vi.fn() };
});

import { addMessageToUI } from '@/components/messages';

function render(content: string): HTMLElement {
  const container = document.createElement('div');
  addMessageToUI({ id: 'u1', role: 'user', content, created_at: '2024-01-01T00:00:00Z' }, container);
  return container.querySelector<HTMLElement>('.message-content')!;
}

const links = (el: HTMLElement): [string | null, string | null][] =>
  [...el.querySelectorAll('a')].map((a) => [a.getAttribute('href'), a.textContent]);

describe('user message text', () => {
  it('links URLs and keeps the rest as text', () => {
    const el = render('see https://example.com/a?b=1&c=2 and www.x.org\n<b>not bold</b>');
    expect(links(el)).toEqual([
      ['https://example.com/a?b=1&c=2', 'https://example.com/a?b=1&c=2'],
      ['https://www.x.org', 'www.x.org'],
    ]);
    expect(el.querySelector('a')?.getAttribute('target')).toBe('_blank');
    expect(el.querySelector('a')?.getAttribute('rel')).toBe('noopener noreferrer');
    expect(el.querySelectorAll('br')).toHaveLength(1);
    expect(el.querySelector('b')).toBeNull();
    expect(el.textContent).toBe('see https://example.com/a?b=1&c=2 and www.x.org<b>not bold</b>');
  });

  it('ends a URL at a quote or angle bracket', () => {
    const el = render('"https://q.com" <https://lt.com> \'https://s.com\'');
    expect(links(el).slice(0, 2)).toEqual([
      ['https://q.com', 'https://q.com'],
      ['https://lt.com', 'https://lt.com'],
    ]);
    expect(el.textContent).toBe('"https://q.com" <https://lt.com> \'https://s.com\'');
  });
});
