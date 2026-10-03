/**
 * Deep-research events of a live (or resumed) stream: the progress model
 * lives on the StreamingState, so it survives a conversation switch that
 * re-creates the streaming bubble; a one-second tick keeps the elapsed time
 * moving (and redraws the panel into a re-created bubble).
 */
import { MS_PER_SECOND } from '../constants';
import { getStreamingMessageElement } from '../components/messages';
import {
  applyResearchEvent,
  renderResearchProgress,
  tickResearchProgress,
} from '../components/messages/research-progress';
import { useStore } from '../state/store';
import type { StreamingState } from './stream-session';

function ids(state: StreamingState, convId: string): { convId: string; messageId: string } {
  return { convId, messageId: state.expectedAssistantMessageId ?? '' };
}

function startTicker(state: StreamingState, convId: string): void {
  const timer = setInterval(() => {
    const store = useStore.getState();
    if (!state.research || !store.getActiveRequest(convId)) {
      clearInterval(timer);
      return;
    }
    if (store.currentConversation?.id !== convId) return;
    const el = getStreamingMessageElement(convId);
    if (el) tickResearchProgress(el, state.research, ids(state, convId));
  }, MS_PER_SECOND);
}

export function handleResearchEvent(
  event: { type: string; [key: string]: unknown },
  state: StreamingState,
  convId: string,
  isCurrentConversation: boolean
): void {
  const fresh = event.type === 'research_plan' && !state.research;
  state.research = applyResearchEvent(state.research, event);
  if (!state.research) return;
  if (fresh) startTicker(state, convId);
  if (isCurrentConversation) renderResearchProgress(state.messageEl, state.research, ids(state, convId));
}
