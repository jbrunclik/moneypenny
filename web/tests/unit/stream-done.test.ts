/**
 * Unit tests for the done-event -> store message mapping
 */
import { describe, it, expect, vi } from 'vitest';

vi.mock('@/core/conversation-actions', () => ({ updateConversationTitle: vi.fn() }));
vi.mock('@/core/toolbar', () => ({ updateConversationCost: vi.fn() }));
vi.mock('@/components/messages', () => ({}));

import { assistantMessageFromDone, doneContentToRender, hasVisibleContent } from '@/core/stream-done';

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

  it('carries stop_reason into the store message', () => {
    const msg = assistantMessageFromDone(
      { id: 'm1', created_at: '2026-09-30T10:00:00Z', content: 'Partial', stop_reason: 'user' },
      'Partial'
    );
    expect(msg.stop_reason).toBe('user');
  });
});

describe('assistantMessageFromDone grounding', () => {
  it('carries annotations and the grounding summary into the store message', () => {
    const annotations = [{ type: 'claim' as const, verdict: 'not_found' as const, quote: 'X' }];
    const message = assistantMessageFromDone(
      { id: 'a1', created_at: '2026-10-03T08:00:00', content: 'X', annotations, grounding: { checked: true, source_count: 2 } },
      'X'
    );

    expect(message.annotations).toEqual(annotations);
    expect(message.grounding).toEqual({ checked: true, source_count: 2 });
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

describe('doneContentToRender', () => {
  it('renders the saved text when it differs from what streamed', () => {
    // The grounding check marks unverified specifics after the last token
    // (src/agent/grounding_markers.py); the bubble must show the saved text
    expect(doneContentToRender('Kupte u VeloRama _(neověřeno)_.', 'Kupte u VeloRama.')).toBe(
      'Kupte u VeloRama _(neověřeno)_.'
    );
  });

  it('renders the saved text when no tokens arrived (lost-token recovery)', () => {
    expect(doneContentToRender('Hi there', '')).toBe('Hi there');
  });

  it('skips the re-render when the streamed text already matches', () => {
    expect(doneContentToRender('Hi there', 'Hi there')).toBeNull();
    expect(doneContentToRender('Hi there', 'Hi there\n')).toBeNull();
  });

  it('keeps the streamed text when the event has no content', () => {
    expect(doneContentToRender(undefined, 'Streamed')).toBeNull();
    expect(doneContentToRender('', 'Streamed')).toBeNull();
  });
});
