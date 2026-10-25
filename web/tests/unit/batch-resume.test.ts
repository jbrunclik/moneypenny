/**
 * Batch turns that outlive their page: the page remembers which user message
 * a batch turn answers, and after a reload waits (spinner up) for the reply
 * the server is still producing.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

const { waitForReplyTo, showLoadingIndicator, hideLoadingIndicator, settleTurnFor, incrementLocalMessageCount } =
  vi.hoisted(() => ({
    waitForReplyTo: vi.fn<(convId: string, messageId: string) => Promise<boolean>>(),
    showLoadingIndicator: vi.fn(),
    hideLoadingIndicator: vi.fn(),
    settleTurnFor: vi.fn(),
    incrementLocalMessageCount: vi.fn(),
  }));
vi.mock('@/core/reply-wait', () => ({ waitForReplyTo }));
vi.mock('@/components/messages', () => ({ showLoadingIndicator, hideLoadingIndicator }));
vi.mock('@/components/messages/turn-anchor', () => ({ settleTurnFor }));
vi.mock('@/sync/SyncManager', () => ({ getSyncManager: () => ({ incrementLocalMessageCount }) }));

import {
  INFLIGHT_BATCH_MAX_AGE_MS,
  clearAllInflightBatches,
  clearInflightBatch,
  hasInflightBatch,
  persistInflightBatch,
  resumeInflightBatchIfAny,
} from '@/core/batch-resume';
import { useStore } from '@/state/store';
import type { Conversation, Message } from '@/types/api';

const NOW = new Date('2026-10-26T10:00:00Z').getTime();

function msg(id: string, role: Message['role']): Message {
  return { id, role, content: id, created_at: '2026-10-26T10:00:00Z' };
}

function openConversation(id: string): void {
  const conv: Conversation = { id, title: id, model: 'm', created_at: '', updated_at: '' };
  useStore.getState().setCurrentConversation(conv);
}

describe('batch resume', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
    useStore.setState(useStore.getInitialState(), true);
    clearAllInflightBatches();
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.useRealTimers();
    clearAllInflightBatches();
  });

  describe('bookkeeping', () => {
    it('remembers an in-flight batch per conversation', () => {
      persistInflightBatch('c1', 'm1');
      expect(hasInflightBatch('c1')).toBe(true);
      expect(hasInflightBatch('c2')).toBe(false);
    });

    it('clearing with a different message id leaves a newer send alone', () => {
      persistInflightBatch('c1', 'm2');
      clearInflightBatch('c1', 'm1');
      expect(hasInflightBatch('c1')).toBe(true);
      clearInflightBatch('c1', 'm2');
      expect(hasInflightBatch('c1')).toBe(false);
    });

    it('clearing without a message id drops the entry', () => {
      persistInflightBatch('c1', 'm1');
      clearInflightBatch('c1');
      expect(hasInflightBatch('c1')).toBe(false);
    });

    it('entries older than the max age are ignored', () => {
      persistInflightBatch('c1', 'm1');
      vi.setSystemTime(NOW + INFLIGHT_BATCH_MAX_AGE_MS + 1);
      expect(hasInflightBatch('c1')).toBe(false);
    });

    it('clearAllInflightBatches drops every conversation', () => {
      persistInflightBatch('c1', 'm1');
      persistInflightBatch('c2', 'm2');
      clearAllInflightBatches();
      expect(hasInflightBatch('c1')).toBe(false);
      expect(hasInflightBatch('c2')).toBe(false);
    });

    it('survives corrupt storage', () => {
      localStorage.setItem('inflight-batch-turns', '{broken');
      expect(hasInflightBatch('c1')).toBe(false);
      persistInflightBatch('c1', 'm1');
      expect(hasInflightBatch('c1')).toBe(true);
    });
  });

  describe('resumeInflightBatchIfAny', () => {
    it('does nothing without an entry', async () => {
      await resumeInflightBatchIfAny('c1', [msg('m1', 'user')]);
      expect(waitForReplyTo).not.toHaveBeenCalled();
      expect(showLoadingIndicator).not.toHaveBeenCalled();
    });

    it('drops the entry when the reply is already there', async () => {
      persistInflightBatch('c1', 'm1');
      await resumeInflightBatchIfAny('c1', [msg('m1', 'user'), msg('r1', 'assistant')]);
      expect(waitForReplyTo).not.toHaveBeenCalled();
      expect(hasInflightBatch('c1')).toBe(false);
    });

    it('drops the entry when the message never reached the server', async () => {
      persistInflightBatch('c1', 'm1');
      await resumeInflightBatchIfAny('c1', [msg('other', 'user'), msg('r0', 'assistant')]);
      expect(waitForReplyTo).not.toHaveBeenCalled();
      expect(hasInflightBatch('c1')).toBe(false);
    });

    it('skips a conversation whose request is still live in this tab', async () => {
      persistInflightBatch('c1', 'm1');
      useStore.getState().setActiveRequest('c1', { conversationId: 'c1', type: 'batch' });
      await resumeInflightBatchIfAny('c1', [msg('m1', 'user')]);
      expect(waitForReplyTo).not.toHaveBeenCalled();
      expect(hasInflightBatch('c1')).toBe(true);
    });

    it('waits for the missing reply with the spinner up, then settles', async () => {
      openConversation('c1');
      persistInflightBatch('c1', 'm1');
      waitForReplyTo.mockResolvedValue(true);
      await resumeInflightBatchIfAny('c1', [msg('m1', 'user')]);
      expect(showLoadingIndicator).toHaveBeenCalled();
      expect(waitForReplyTo).toHaveBeenCalledWith('c1', 'm1');
      expect(incrementLocalMessageCount).toHaveBeenCalledWith('c1', 1);
      expect(hideLoadingIndicator).toHaveBeenCalled();
      expect(settleTurnFor).toHaveBeenCalledWith('c1');
      expect(hasInflightBatch('c1')).toBe(false);
    });

    it('does not count a message when the reply never came', async () => {
      openConversation('c1');
      persistInflightBatch('c1', 'm1');
      waitForReplyTo.mockResolvedValue(false);
      await resumeInflightBatchIfAny('c1', [msg('m1', 'user')]);
      expect(incrementLocalMessageCount).not.toHaveBeenCalled();
      expect(hasInflightBatch('c1')).toBe(false);
    });

    it('leaves the spinner alone when the user moved to another conversation', async () => {
      openConversation('c2');
      persistInflightBatch('c1', 'm1');
      waitForReplyTo.mockResolvedValue(true);
      await resumeInflightBatchIfAny('c1', [msg('m1', 'user')]);
      expect(hideLoadingIndicator).not.toHaveBeenCalled();
      expect(settleTurnFor).not.toHaveBeenCalled();
    });

    it('a second resume while already waiting does not poll twice', async () => {
      openConversation('c1');
      persistInflightBatch('c1', 'm1');
      let finish: (replied: boolean) => void = () => {};
      waitForReplyTo.mockReturnValue(new Promise((resolve) => (finish = resolve)));
      const first = resumeInflightBatchIfAny('c1', [msg('m1', 'user')]);
      await resumeInflightBatchIfAny('c1', [msg('m1', 'user')]);
      expect(waitForReplyTo).toHaveBeenCalledTimes(1);
      finish(true);
      await first;
    });

    it('keeps a newer send recorded while the old reply was awaited', async () => {
      openConversation('c1');
      persistInflightBatch('c1', 'm1');
      waitForReplyTo.mockImplementation(async () => {
        persistInflightBatch('c1', 'm2');
        return true;
      });
      await resumeInflightBatchIfAny('c1', [msg('m1', 'user')]);
      expect(hasInflightBatch('c1')).toBe(true);
    });
  });
});
