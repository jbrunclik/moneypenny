/**
 * Forward links from a source to the reply an action produced: a claim to
 * its look-up's answer ("Looked up below ↓"), an offer to its report
 * ("Report below ↓"). Computed from the store's loaded messages: the action
 * message points back at its source, the reply is the next assistant message.
 */
import { useStore } from '../state/store';
import type { Message } from '../types/api';

function targets(message: Message, sourceId: string, claimIndex?: number): boolean {
  const action = message.action;
  if (!action) return false;
  if (claimIndex === undefined) return action.type === 'deep_research' && action.offer_message_id === sourceId;
  return action.type === 'verify_claim' && action.source_message_id === sourceId && action.claim_index === claimIndex;
}

/** Id of the reply to the latest action on this source (a claim when claimIndex is set). */
export function findActionReply(convId: string, sourceId: string, claimIndex?: number): string | null {
  const messages = useStore.getState().getMessages(convId);
  for (let i = messages.length - 1; i >= 0; i--) {
    if (!targets(messages[i], sourceId, claimIndex)) continue;
    const reply = messages.slice(i + 1).find((m) => m.role === 'assistant');
    if (reply) return reply.id;
  }
  return null;
}
