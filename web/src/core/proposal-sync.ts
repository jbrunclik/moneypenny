/**
 * A typed "yes" answers the cards of an earlier reply on the server, before
 * the turn runs (docs/features/proposals.md) - the cards already on screen
 * do not know. After a turn in a conversation that showed an open card, the
 * external-changes merge re-renders the cards that changed.
 */
import { useStore } from '../state/store';

/** Whether the conversation shows a card still awaiting an answer. */
export function hasOpenProposals(convId: string): boolean {
  return useStore
    .getState()
    .getMessages(convId)
    .some((m) => m.proposals?.some((p) => p.state === 'pending'));
}
