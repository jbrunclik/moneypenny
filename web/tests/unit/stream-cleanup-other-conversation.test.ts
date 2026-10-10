/**
 * A turn ending in one conversation must not tear down the streaming UI of
 * another conversation's turn (a background stream finishing while the user
 * watches a reply stream in the open one). The live context was one global
 * that every turn's cleanup nulled: the visible reply's thinking, tool and
 * autoscroll updates then stopped.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import {
  addStreamingMessage,
  cleanupStreamingContext,
  getStreamingContextConversationId,
} from '@/components/messages';

describe('cleanupStreamingContext(convId)', () => {
  beforeEach(() => {
    cleanupStreamingContext();
    document.body.innerHTML = '<div id="messages"></div>';
  });

  it("leaves another conversation's live context alone", () => {
    addStreamingMessage('visible', { anchor: false });
    cleanupStreamingContext('background');
    expect(getStreamingContextConversationId()).toBe('visible');
  });

  it("tears down its own conversation's context", () => {
    addStreamingMessage('visible', { anchor: false });
    cleanupStreamingContext('visible');
    expect(getStreamingContextConversationId()).toBeNull();
  });
});
