/**
 * Deep research on the client: starting a card's run, and re-offering it when
 * the run's turn would be re-run (Regenerate, Continue, Retry).
 *
 * Start sends a user message "Start deep research" carrying the card and the
 * edited plan; the server runs the pipeline as that turn (always over the
 * stream endpoint). The card's state is updated in the store right away so a
 * re-render shows the started line. Not now is the card's shared decline
 * (proposal-card.ts).
 */
import { proposals as proposalsApi } from '../api/proposals';
import { ApiError } from '../api/http';
import { removeRenderedMessagesFrom } from '../components/messages';
import { showAnsweredProposals } from '../components/messages/proposal-card';
import type { ResearchStartTarget } from '../components/messages/research-offer';
import { toast } from '../components/Toast';
import { useStore } from '../state/store';
import type { Proposal, ReopenReason } from '../types/api';
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

/**
 * The run a re-run would answer: the conversation's last user message, when
 * it is a deep-research Start, and its card (on the offer's reply).
 */
function runToReopen(convId: string): { startId: string; proposalId: string } | null {
  const messages = useStore.getState().getMessages(convId);
  const start = [...messages].reverse().find((m) => m.role === 'user');
  const action = start?.action;
  if (!start || action?.type !== 'deep_research') return null;
  const offer = messages.find((m) => m.id === action.offer_message_id);
  const card = offer?.proposals?.find((p) => p.kind === 'deep_research');
  return card ? { startId: start.id, proposalId: card.id } : null;
}

/**
 * Re-offer the card instead of re-running a deep-research run's turn (a
 * deploy killed it, or Regenerate / Continue / Retry on it): a re-run would
 * be an ordinary turn on "Start deep research". The run's messages go and
 * the card is open again with the started plan, no countdown. True when this
 * was such a run (the caller must not re-run it), false otherwise.
 */
export async function reopenResearchRun(convId: string, reason: ReopenReason): Promise<boolean> {
  const run = runToReopen(convId);
  if (!run) return false;
  log.info('Re-offering deep research', { conversationId: convId, proposalId: run.proposalId, reason });
  try {
    const card = await proposalsApi.reopen(run.proposalId, run.startId, reason);
    useStore.getState().truncateMessagesFrom(convId, run.startId);
    removeRenderedMessagesFrom(run.startId);
    showAnsweredProposals([card]);
  } catch (error) {
    log.warn('Re-offering deep research failed', { conversationId: convId, error: String(error) });
    toast.error(error instanceof ApiError ? error.message : 'Could not re-open the research offer.');
  }
  return true;
}
