/**
 * Deep research on the client: starting and declining offers.
 *
 * Start sends a user message "Start deep research" carrying the edited plan;
 * the server runs the pipeline as that turn (always over the stream
 * endpoint). The offer's status is updated in the store right away so a
 * re-render shows the decided card.
 */
import { messages as messagesApi } from '../api/conversations';
import { toast } from '../components/Toast';
import { useStore } from '../state/store';
import type { MessageResearch, ResearchOfferStatus } from '../types/api';
import { createLogger } from '../utils/logger';
import { sendUiMessage } from './messaging';

const log = createLogger('deep-research');

export const START_MESSAGE = 'Start deep research';

/** The research data with its open offer (or a report's follow-up) set to status. */
export function withOfferStatus(research: MessageResearch, status: ResearchOfferStatus): MessageResearch {
  if (research.offer) return { ...research, offer: { ...research.offer, status } };
  if (research.run?.followup) {
    return { ...research, run: { ...research.run, followup: { ...research.run.followup, status } } };
  }
  return research;
}

function setOfferStatus(offerMessageId: string, status: ResearchOfferStatus): void {
  const store = useStore.getState();
  const convId = store.currentConversation?.id;
  if (!convId) return;
  const message = store.getMessages(convId).find((m) => m.id === offerMessageId);
  if (message?.research) {
    store.updateMessage(convId, offerMessageId, { research: withOfferStatus(message.research, status) });
  }
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
 * Start an offer with the edited plan; false when it could not be sent now.
 * `whenIdle` (autostart) waits for the reply carrying the offer to finish -
 * it is still the conversation's running request while its done is handled.
 */
export async function startDeepResearch(
  offerMessageId: string,
  subQuestions: string[],
  context: string,
  options: { whenIdle?: boolean; minutes?: number } = {}
): Promise<boolean> {
  log.info('Starting deep research', { offerMessageId, items: subQuestions.length });
  const plan = { offer_message_id: offerMessageId, sub_questions: subQuestions, context };
  setOfferStatus(offerMessageId, 'started');
  const convId = useStore.getState().currentConversation?.id;
  if (options.whenIdle && convId) await whenIdle(convId);
  const action = {
    type: 'deep_research' as const,
    offer_message_id: offerMessageId,
    items: subQuestions.length,
    minutes: options.minutes ?? 0,
  };
  const sent = await sendUiMessage(START_MESSAGE, { deepResearch: plan, action });
  if (!sent) setOfferStatus(offerMessageId, 'offered');
  return sent;
}

/** Decline an offer; false (with a toast) when the server refused. */
export async function declineDeepResearch(offerMessageId: string): Promise<boolean> {
  try {
    await messagesApi.declineResearchOffer(offerMessageId);
  } catch (error) {
    log.warn('Declining the research offer failed', { error, offerMessageId });
    toast.error('Could not decline the offer. Please try again.');
    return false;
  }
  setOfferStatus(offerMessageId, 'declined');
  return true;
}
