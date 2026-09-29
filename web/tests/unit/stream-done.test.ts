/**
 * Unit tests for the done-event -> store message mapping
 */
import { describe, it, expect, vi } from 'vitest';

vi.mock('@/core/conversation-actions', () => ({ updateConversationTitle: vi.fn() }));
vi.mock('@/core/toolbar', () => ({ updateConversationCost: vi.fn() }));
vi.mock('@/components/messages', () => ({}));

import { assistantMessageFromDone, hasVisibleContent } from '@/core/stream-done';

describe('assistantMessageFromDone', () => {
  it('maps the saved message fields', () => {
    const message = assistantMessageFromDone(
      {
        id: 'a1',
        created_at: '2026-09-29T12:00:00Z',
        content: 'Saved',
        sources: [{ title: 'T', url: 'https://example.com' }],
        generated_images: [{ prompt: 'p' }],
        files: [{ name: 'f.csv', type: 'text/csv' }],
        language: 'cs',
        stopped_early: true,
        title: 'ignored',
        user_message_id: 'ignored',
        approval_required: false,
      },
      'streamed'
    );
    expect(message).toEqual({
      id: 'a1',
      role: 'assistant',
      content: 'Saved',
      created_at: '2026-09-29T12:00:00Z',
      sources: [{ title: 'T', url: 'https://example.com' }],
      generated_images: [{ prompt: 'p' }],
      files: [{ name: 'f.csv', type: 'text/csv' }],
      language: 'cs',
      stopped_early: true,
    });
  });

  it('falls back to the streamed text when the event has no content', () => {
    expect(assistantMessageFromDone({ id: 'a1', created_at: 'x' }, 'streamed').content).toBe('streamed');
    expect(assistantMessageFromDone({ id: 'a1', created_at: 'x', content: '' }, 'streamed').content).toBe('streamed');
  });
});

describe('hasVisibleContent', () => {
  it('is false for metadata-only turns', () => {
    expect(hasVisibleContent({ id: 'a', created_at: 'x' })).toBe(false);
    expect(hasVisibleContent({ id: 'a', created_at: 'x', content: '  \n', files: [], sources: [] })).toBe(false);
  });

  it('is true for text, files, images or sources', () => {
    expect(hasVisibleContent({ id: 'a', created_at: 'x', content: 'hi' })).toBe(true);
    expect(hasVisibleContent({ id: 'a', created_at: 'x', files: [{ name: 'f', type: 't' }] })).toBe(true);
    expect(hasVisibleContent({ id: 'a', created_at: 'x', generated_images: [{ prompt: 'p' }] })).toBe(true);
    expect(hasVisibleContent({ id: 'a', created_at: 'x', sources: [{ title: 't', url: 'u' }] })).toBe(true);
  });
});
