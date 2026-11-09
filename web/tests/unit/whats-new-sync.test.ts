/**
 * What's new on the client: a chat that joins the list through sync keeps
 * its marker, and the chat hides Regenerate/Continue (read-only).
 */
import { describe, expect, it } from 'vitest';
import { listEntryFromSummary } from '@/sync/summary-merge';
import type { ConversationSummary } from '@/types/api';

describe("What's new from sync", () => {
  it('keeps the marker on a chat that joins the list', () => {
    const summary = {
      id: 'w',
      title: 'Novinky',
      model: 'm',
      created_at: '2026-11-09T06:00:00Z',
      updated_at: '2026-11-09T06:00:00Z',
      message_count: 1,
      read_count: 0,
      last_message_preview: null,
      last_message_id: null,
      archived: false,
      trashed: false,
      pinned: false,
      anonymous_mode: false,
      is_whats_new: true,
    } satisfies ConversationSummary;

    expect(listEntryFromSummary(summary, 1).is_whats_new).toBe(true);
  });
});
