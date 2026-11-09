/**
 * Deep research on the client: starting a card's run.
 *
 * Start sends a user message "Start deep research" carrying the card and the
 * edited plan; the server runs the pipeline as that turn (always over the
 * stream endpoint). The card's state is updated in the store right away so a
 * re-render shows the started line. Not now is the card's shared decline
 * (proposal-card.ts).
 */
import type { ResearchStartTarget } from '../components/messages/research-offer';
import { useStore } from '../state/store';
import type { Proposal } from '../types/api';
import { createLogger } from '../utils/logger';
import { sendUiMessage } from './messaging';

const log = createLogger('deep-research');

const START_MESSAGE = 'Start deep research';

/** Set a card's state in the store's copy of its reply. */
function setCardState(target: ResearchStartTarget, state: Proposal['state']): void {
  const store = useStore.getState();
  const convId = store.currentConversation?.id;
  if (!convId) return;
  const message = store.getMessages(convId).find((m) => m.id === target.messageId);
  if (!message?.proposals) return;
  const proposals = message.proposals.map((p) => (p.id === target.proposalId ? { ...p, state } : p));
  store.updateMessage(convId, target.messageId, { proposals });
}

/** Resolves once the conversation has no reply running. */
function whenIdle(convId: string): Promise<void> {
  return new Promise((resolve) => {
    if (!useStore.getState().getActiveRequest(convId)) return resolve();
    const unsubscribe = useStore.subscribe((state) => {
      if (state.getActiveRequest(convId)) return;
      unsubscribe();
      resolve();
    });
  });
}

/**
 * Start a card's run with the edited plan; false when it could not be sent now.
 * `whenIdle` (autostart) waits for the reply carrying the card to finish -
 * it is still the conversation's running request while its done is handled.
 */
export async function startDeepResearch(
  target: ResearchStartTarget,
  subQuestions: string[],
  context: string,
  options: { whenIdle?: boolean; minutes?: number } = {}
): Promise<boolean> {
  log.info('Starting deep research', { proposalId: target.proposalId, items: subQuestions.length });
  const plan = { proposal_id: target.proposalId, sub_questions: subQuestions, context };
  setCardState(target, 'approved');
  const convId = useStore.getState().currentConversation?.id;
  if (options.whenIdle && convId) await whenIdle(convId);
  const action = {
    type: 'deep_research' as const,
    offer_message_id: target.messageId,
    items: subQuestions.length,
    minutes: options.minutes ?? 0,
  };
  const sent = await sendUiMessage(START_MESSAGE, { deepResearch: plan, action });
  if (!sent) setCardState(target, 'pending');
  return sent;
}
