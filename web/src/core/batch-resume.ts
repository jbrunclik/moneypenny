/**
 * Batch turns that outlive their page.
 *
 * The batch endpoint saves the user message before the agent runs and keeps
 * running the turn after the client is gone. When the page dies mid-turn
 * (iPhone PWA suspended or reloaded), the reloaded conversation shows the
 * message with no reply - so wait for it, spinner up, instead of leaving the
 * user to send it again.
 */

import { useStore } from '../state/store';
import { createLogger } from '../utils/logger';
import { hideLoadingIndicator, showLoadingIndicator } from '../components/messages';
import { settleTurnFor } from '../components/messages/turn-anchor';
import type { Message } from '../types/api';
import { getSyncManager } from '../sync/SyncManager';
import { waitForReplyTo } from './reply-wait';

const log = createLogger('messaging');

// Map keyed by conversation id: batch turns can run in several conversations
// at once. A turn older than this is not worth waiting for after a reload.
const INFLIGHT_BATCH_KEY = 'inflight-batch-turns';
export const INFLIGHT_BATCH_MAX_AGE_MS = 30 * 60 * 1000;

interface InflightBatch {
  messageId: string;
  ts: number;
}

/** Conversations whose reply this page is already waiting for. */
const waiting = new Set<string>();

function readInflightBatches(): Record<string, InflightBatch> {
  try {
    const map = JSON.parse(localStorage.getItem(INFLIGHT_BATCH_KEY) || '{}') as Record<string, InflightBatch>;
    const now = Date.now();
    return Object.fromEntries(
      Object.entries(map).filter(([, e]) => e?.messageId && now - e.ts <= INFLIGHT_BATCH_MAX_AGE_MS)
    );
  } catch {
    return {};
  }
}

function writeInflightBatches(map: Record<string, InflightBatch>): void {
  try {
    if (Object.keys(map).length === 0) {
      localStorage.removeItem(INFLIGHT_BATCH_KEY);
    } else {
      localStorage.setItem(INFLIGHT_BATCH_KEY, JSON.stringify(map));
    }
  } catch {
    // Quota/privacy-mode failures only cost the reload-resume nicety
  }
}

/** Remember the user message a batch turn is answering (before the request). */
export function persistInflightBatch(convId: string, messageId: string): void {
  const map = readInflightBatches();
  map[convId] = { messageId, ts: Date.now() };
  writeInflightBatches(map);
}

/** Forget the conversation's entry (only if it is still `messageId`'s, when given). */
export function clearInflightBatch(convId: string, messageId?: string): void {
  const map = readInflightBatches();
  if (convId in map && (messageId === undefined || map[convId].messageId === messageId)) {
    delete map[convId];
    writeInflightBatches(map);
  }
}

/** Drop every entry (logout: another account must not wait on these turns). */
export function clearAllInflightBatches(): void {
  writeInflightBatches({});
}

/**
 * After the conversation renders: if this page died during a batch turn here
 * and the reply isn't in yet, show the spinner and poll until it lands.
 */
export async function resumeInflightBatchIfAny(convId: string, messages: Message[]): Promise<void> {
  // Still live in this tab (conversation switch, not a reload)
  if (useStore.getState().getActiveRequest(convId) || waiting.has(convId)) return;
  const entry = readInflightBatches()[convId];
  if (!entry) return;

  const sentAt = messages.findIndex((m) => m.id === entry.messageId);
  const replied = messages.slice(sentAt + 1).some((m) => m.role === 'assistant');
  if (sentAt < 0 || replied) {
    // Never landed (the outbox shows it as failed) or already answered
    clearInflightBatch(convId);
    return;
  }

  log.info('Waiting for a batch reply after reload', { conversationId: convId, messageId: entry.messageId });
  waiting.add(convId);
  showLoadingIndicator();
  try {
    if (await waitForReplyTo(convId, entry.messageId)) {
      // The reload counted the user message; only the reply is new
      getSyncManager()?.incrementLocalMessageCount(convId, 1);
    }
  } finally {
    waiting.delete(convId);
    // A message sent meanwhile has its own entry - leave that one alone
    clearInflightBatch(convId, entry.messageId);
    if (useStore.getState().currentConversation?.id === convId) {
      hideLoadingIndicator();
      settleTurnFor(convId);
    }
  }
}
