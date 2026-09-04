/**
 * Quick actions: one-tap saved prompts for program conversations.
 *
 * This module owns message composition, mounting the chip bar above the
 * composer while a program conversation is open, its mobile visibility
 * rules, sending, and the editor glue. Components in
 * components/QuickActions*.ts are presentation only.
 */
import type { QuickAction } from '../types/api';
import { useStore } from '../state/store';
import { renderQuickActionsBar, setQuickActionsBarDisabled } from '../components/QuickActionsBar';
import { isMobileViewport } from '../components/MessageInput';
import { showQuickActionForm } from '../components/QuickActionForm';
import { showQuickActionsEditor } from '../components/QuickActionsEditor';
import { toast } from '../components/Toast';
import { getElementById } from '../utils/dom';
import { createLogger } from '../utils/logger';
import { sendMessage } from './messaging';

const log = createLogger('quick-actions');

/**
 * Body, blank line, then one `Label: value` line per non-empty field (in
 * field order). Multi-line values indent continuation lines by two spaces.
 * All-empty fields -> body only.
 */
export function composeQuickActionMessage(
  action: QuickAction,
  values: Record<string, string>
): string {
  const body = action.body.trim();
  const lines: string[] = [];
  for (const field of action.fields) {
    const value = (values[field] ?? '').trim();
    if (!value) continue;
    lines.push(`${field}: ${value.split('\n').join('\n  ')}`);
  }
  return lines.length > 0 ? `${body}\n\n${lines.join('\n')}` : body;
}

export interface QuickActionsContext {
  namespace: 'sports' | 'language';
  programId: string;
  actions: QuickAction[];
  /** Persist the full list; resolves with the server's copy. */
  save: (actions: QuickAction[]) => Promise<QuickAction[]>;
}

let current: QuickActionsContext | null = null;
let unsubscribeStore: (() => void) | null = null;

export function shouldShowQuickActionsBar(input: {
  mobile: boolean;
  composerEmpty: boolean;
  streaming: boolean;
}): boolean {
  if (!input.mobile) return true;
  return input.composerEmpty && !input.streaming;
}

function isCurrentConversationStreaming(): boolean {
  const state = useStore.getState();
  const convId = state.currentConversation?.id;
  return convId !== undefined && state.activeRequests.has(convId);
}

/** Re-evaluate visibility + disabled state from composer/stream state. */
export function refreshQuickActionsBar(): void {
  const bar = getElementById<HTMLElement>('quick-actions-bar');
  if (!bar) return;
  if (!current) {
    bar.classList.add('hidden');
    return;
  }
  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  const streaming = isCurrentConversationStreaming();
  const visible = shouldShowQuickActionsBar({
    mobile: isMobileViewport(),
    composerEmpty: !textarea || textarea.value.trim() === '',
    streaming,
  });
  bar.classList.toggle('hidden', !visible);
  setQuickActionsBarDisabled(bar, streaming);
}

function renderCurrent(): void {
  const bar = getElementById<HTMLElement>('quick-actions-bar');
  if (!bar || !current) return;
  renderQuickActionsBar(
    bar,
    current.actions,
    (action, chip) => handleChipTap(action, chip),
    () => openQuickActionsEditor()
  );
  refreshQuickActionsBar();
}

function handleChipTap(action: QuickAction, chip: HTMLElement): void {
  if (isCurrentConversationStreaming()) {
    toast.info('Please wait for the current response to finish.');
    return;
  }
  if (action.fields.length === 0) {
    void sendQuickAction(action, {});
    return;
  }
  showQuickActionForm(action, chip, (values) => void sendQuickAction(action, values));
}

/** Compose the message, put it in the composer and send through the normal path. */
export async function sendQuickAction(
  action: QuickAction,
  values: Record<string, string>
): Promise<void> {
  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  if (!textarea) return;
  const text = composeQuickActionMessage(action, values);
  log.info('Sending quick action', { id: action.id, fields: Object.keys(values).length });
  textarea.value = text;
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  await sendMessage();
}

export function getQuickActionsContext(): QuickActionsContext | null {
  return current;
}

/** Open the per-program editor; saving persists via the context and re-renders the bar. */
export function openQuickActionsEditor(draft?: Partial<QuickAction>): void {
  const ctx = current;
  if (!ctx) return;
  showQuickActionsEditor({
    actions: ctx.actions,
    initialDraft: draft,
    // Autosave: the editor calls this after every change; the bar behind
    // the modal updates immediately so closing needs no extra step.
    onChange: async (actions) => {
      const saved = await ctx.save(actions);
      if (current && current.programId === ctx.programId) {
        current.actions = saved;
        renderCurrent();
      }
    },
  });
}

export function mountQuickActionsBar(ctx: QuickActionsContext): void {
  current = ctx;
  document.body.classList.add('has-quick-actions');
  renderCurrent();
}

export function unmountQuickActionsBar(): void {
  current = null;
  document.body.classList.remove('has-quick-actions');
  const bar = getElementById<HTMLElement>('quick-actions-bar');
  if (bar) bar.classList.add('hidden');
}

/** Wire composer + store listeners once at app init. */
export function initQuickActions(): void {
  const textarea = getElementById<HTMLTextAreaElement>('message-input');
  textarea?.addEventListener('input', refreshQuickActionsBar);
  window.addEventListener('resize', refreshQuickActionsBar);
  unsubscribeStore?.();
  unsubscribeStore = useStore.subscribe(
    (state) => state.activeRequests,
    () => refreshQuickActionsBar()
  );
  document.addEventListener('message:save-quick-action', (e) => {
    const { messageId } = (e as CustomEvent<{ messageId: string }>).detail;
    const convId = useStore.getState().currentConversation?.id;
    if (!convId || !current) return;
    const message = useStore
      .getState()
      .getMessages(convId)
      .find((m) => m.id === messageId);
    if (!message) return;
    openQuickActionsEditor({ body: message.content });
  });
}
