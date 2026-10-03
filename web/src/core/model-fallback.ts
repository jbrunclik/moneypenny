/**
 * Note shown when the conversation's model was down (503) and the other
 * model tier answered instead (src/agent/graph.py chat_node fallback).
 */
import { useStore } from '../state/store';
import { toast } from '../components/Toast';

function shortName(modelId: string | undefined): string {
  const model = useStore.getState().models.find((m) => m.id === modelId);
  return model?.short_name ?? modelId ?? 'The model';
}

export function notifyModelFallback(toModelId: string): void {
  const from = shortName(useStore.getState().currentConversation?.model);
  toast.info(`${from} is overloaded right now - ${shortName(toModelId)} answered instead.`);
}
