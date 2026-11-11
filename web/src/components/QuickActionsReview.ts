/**
 * The Quick actions sheet's Review: the coach's suggested changes to its quick
 * actions and standing instructions, each with the turns it rests on, accepted
 * or rejected one by one (docs/superpowers/specs/2026-11-11-program-self-tuning-design.md).
 * Presentation only: the calls come in as handlers (core/quick-actions.ts for
 * the sheet). Settings' instructions Review renders the same cards with its
 * own texts (docs/superpowers/specs/2026-11-11-instructions-self-tuning-design.md).
 */
import { SuggestionRefreshed } from '../api/setup-review';
import { QUICK_ACTION_REVIEW_PHASES } from '../config';
import { MS_PER_SECOND } from '../constants';
import type { QuickAction, SetupSuggestion } from '../types/api';
import { clearElement, createElement } from '../utils/dom';
import { CHECK_ICON, CLOSE_ICON, INFO_ICON, SPARKLES_ICON, WARNING_ICON, iconNodes, setIcon } from '../utils/icons';
import type { IconHtml } from '../utils/icons';

/** The Review's calls; `apply` resolves with what changed (the sheet: the program's quick actions). */
export interface SetupReviewHandlers<T = QuickAction[]> {
  load: () => Promise<SetupSuggestion[]>;
  apply: (suggestion: SetupSuggestion) => Promise<T>;
  reject: (suggestion: SetupSuggestion) => Promise<void>;
}

/** What a Review says: its empty line, its timed loading steps, its back button. */
export interface ReviewTexts {
  empty: string;
  phases: readonly { afterSeconds: number; text: string }[];
  back: string;
}

const QUICK_ACTION_TEXTS: ReviewTexts = {
  empty: 'Nothing to change - your quick actions and instructions match how you use them.',
  phases: QUICK_ACTION_REVIEW_PHASES,
  back: 'Back',
};
const FAILED_TEXT = 'The review failed.';

function errorText(error: unknown): string {
  return error instanceof Error && error.message ? error.message : 'Something went wrong.';
}

/** One changed field: its name, the old value struck through (if any), the new one. */
function fieldRow(change: SetupSuggestion['changes'][number]): HTMLElement {
  const values: HTMLElement[] = [];
  if (change.before) values.push(createElement('del', { class: 'qa-review-old' }, [change.before]));
  values.push(
    change.after
      ? createElement('ins', { class: 'qa-review-new' }, [change.after])
      : createElement('span', { class: 'qa-review-removed' }, ['Removed'])
  );
  return createElement('div', { class: 'qa-review-field' }, [
    createElement('div', { class: 'qa-review-field-name' }, [change.field]),
    ...values,
  ]);
}

const EVIDENCE_LINE = /^(\d{4})-(\d{2})-(\d{2}):\s*(.*)$/s;
const QUOTE_MARKS = /^["'“”‘’]+|["'“”‘’]+$/g;

/** "2026-11-09: 'plan my week'" -> the day (readable, machine date kept) + the words as a quote */
const ITEM_LINE = /^(Memory|Instructions):\s*(.*)$/s;

/** "Memory: ..." / "Instructions: ..." -> what it quotes, labelled (clean-up evidence) */
function itemRow(kind: string, quoted: string): HTMLElement {
  return createElement('li', {}, [
    createElement('span', { class: 'qa-review-evidence-kind' }, [kind]),
    createElement('q', {}, [quoted.trim().replace(QUOTE_MARKS, '')]),
  ]);
}

function evidenceRow(line: string): HTMLElement {
  const item = ITEM_LINE.exec(line);
  if (item) return itemRow(item[1] ?? '', item[2] ?? '');
  const match = EVIDENCE_LINE.exec(line);
  if (!match) return createElement('li', {}, [createElement('q', {}, [line.replace(QUOTE_MARKS, '')])]);
  const [, y, m, d, said = ''] = match;
  const day = new Date(Number(y), Number(m) - 1, Number(d));
  const label = day.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  return createElement('li', {}, [
    createElement('time', { datetime: `${y}-${m}-${d}` }, [label]),
    createElement('q', {}, [said.trim().replace(QUOTE_MARKS, '')]),
  ]);
}

function itemElement(s: SetupSuggestion): HTMLElement {
  return createElement('li', { class: 'qa-review-item', 'data-state': 'open' }, [
    createElement('div', { class: 'qa-review-item-head' }, [
      createElement('div', { class: 'qa-review-summary' }, [s.summary]),
      createElement('div', { class: 'qa-review-item-status', 'aria-live': 'polite' }),
    ]),
    createElement('div', { class: 'qa-review-change' }, s.changes.map(fieldRow)),
    createElement('div', { class: 'qa-review-evidence' }, [
      createElement('div', { class: 'qa-review-evidence-title' }, ['Based on']),
      createElement('ul', {}, s.evidence.map(evidenceRow)),
    ]),
    createElement('div', { class: 'qa-review-actions' }, [
      createElement('button', { type: 'button', class: 'qa-review-reject' }, ['Reject']),
      createElement('button', { type: 'button', class: 'qa-review-accept' }, ['Accept']),
    ]),
  ]);
}

type StatusTone = 'applied' | 'rejected' | 'info' | 'error';

const TONE_ICONS: Record<StatusTone, IconHtml> = {
  applied: CHECK_ICON,
  rejected: CLOSE_ICON,
  info: INFO_ICON,
  error: WARNING_ICON,
};

/** The card's status: an outcome pill (applied/rejected) or a notice (info/error). */
function setStatus(item: HTMLElement, tone: StatusTone, text: string): void {
  const status = item.querySelector<HTMLElement>('.qa-review-item-status');
  if (!status) return;
  status.dataset.tone = tone;
  status.replaceChildren(
    createElement('span', { class: 'qa-review-status-icon', 'aria-hidden': 'true' }, [iconNodes(TONE_ICONS[tone])]),
    createElement('span', { class: 'qa-review-status-text' }, [text])
  );
}

const REFRESHED_TEXT = 'This changed since the review - here is the updated change.';

interface ItemContext<T> {
  handlers: SetupReviewHandlers<T>;
  onApplied: (result: T) => void;
}

const BUSY_LABELS = { applied: 'Applying…', rejected: 'Rejecting…' } as const;
const DONE_LABELS = { applied: 'Applied', rejected: 'Rejected' } as const;

async function answer<T>(
  item: HTMLElement,
  run: () => Promise<void>,
  state: 'applied' | 'rejected',
  ctx: ItemContext<T>
): Promise<void> {
  const buttons = item.querySelectorAll<HTMLButtonElement>('.qa-review-actions button');
  const pressed = item.querySelector<HTMLButtonElement>(state === 'applied' ? '.qa-review-accept' : '.qa-review-reject');
  const label = pressed?.textContent ?? '';
  buttons.forEach((b) => (b.disabled = true));
  if (pressed) pressed.textContent = BUSY_LABELS[state];
  try {
    await run();
    item.dataset.state = state;
    // Resolved: the outcome, and only what is still worth reading
    item.querySelector('.qa-review-actions')?.remove();
    item.querySelector('.qa-review-evidence')?.remove();
    if (state === 'rejected') item.querySelector('.qa-review-change')?.remove();
    setStatus(item, state, DONE_LABELS[state]);
  } catch (error) {
    if (error instanceof SuggestionRefreshed) {
      // A collision is not a dead end: the updated change, ready to accept again
      const fresh = liveItem(error.suggestion, ctx);
      setStatus(fresh, 'info', REFRESHED_TEXT);
      item.replaceWith(fresh);
      return;
    }
    buttons.forEach((b) => (b.disabled = false));
    if (pressed) pressed.textContent = label;
    setStatus(item, 'error', errorText(error));
  }
}

/** A suggestion's card with its Accept / Reject wired. */
function liveItem<T>(s: SetupSuggestion, ctx: ItemContext<T>): HTMLElement {
  const item = itemElement(s);
  item.querySelector('.qa-review-accept')?.addEventListener('click', () => {
    void answer(item, async () => ctx.onApplied(await ctx.handlers.apply(s)), 'applied', ctx);
  });
  item.querySelector('.qa-review-reject')?.addEventListener('click', () => {
    void answer(item, () => ctx.handlers.reject(s), 'rejected', ctx);
  });
  return item;
}

function renderSuggestions<T>(
  list: HTMLElement,
  suggestions: SetupSuggestion[],
  handlers: SetupReviewHandlers<T>,
  onApplied: (result: T) => void
): void {
  suggestions.forEach((s) => list.appendChild(liveItem(s, { handlers, onApplied })));
}

/**
 * Render the Review into `container` and start it. `onApplied` gets what
 * apply resolved with after each accepted change (the sheet: the program's
 * quick actions); `back` leaves the Review.
 */
export function renderSetupReview<T = QuickAction[]>(
  container: HTMLElement,
  handlers: SetupReviewHandlers<T>,
  onApplied: (result: T) => void,
  back: () => void,
  texts: ReviewTexts = QUICK_ACTION_TEXTS
): void {
  clearElement(container);
  const backButton = createElement('button', { type: 'button', class: 'qa-detail-back qa-review-back' }, [texts.back]);
  backButton.addEventListener('click', back);
  const status = createElement('p', { class: 'qa-review-status', 'aria-live': 'polite' });
  const list = createElement('ul', { class: 'qa-review-list' });
  container.append(
    createElement('div', { class: 'qa-review-header' }, [
      backButton,
      createElement('span', { class: 'qa-detail-section-title' }, ['Suggestions']),
    ]),
    status,
    list
  );

  const run = async (): Promise<void> => {
    clearElement(list);
    status.hidden = true;
    const stopLoading = showLoading(container, list, texts.phases);
    try {
      const suggestions = await handlers.load();
      stopLoading();
      status.hidden = suggestions.length > 0;
      status.textContent = suggestions.length ? '' : texts.empty;
      renderSuggestions(list, suggestions, handlers, onApplied);
    } catch (error) {
      stopLoading();
      status.hidden = false;
      status.textContent = FAILED_TEXT;
      const detail = `${errorText(error)} Nothing was changed.`;
      const retry = createElement('button', { type: 'button', class: 'qa-detail-back qa-review-retry' }, ['Try again']);
      retry.addEventListener('click', () => void run());
      list.appendChild(
        createElement('li', { class: 'qa-review-error' }, [
          createElement('p', { class: 'qa-review-error-detail' }, [detail]),
          retry,
        ])
      );
    }
  };
  void run();
}

/** The step the Review is on after `seconds` (the work's real order, timed). */
function phaseAt(phases: ReviewTexts['phases'], seconds: number): string {
  let text = phases[0]?.text ?? '';
  for (const phase of phases) {
    if (seconds >= phase.afterSeconds) text = phase.text;
  }
  return text;
}

/**
 * While the Review runs: the step it is on, the seconds so far and a moving
 * bar (no placeholder cards: they looked like a count of coming results).
 * Returns the function that removes them (and stops the clock).
 */
function showLoading(
  container: HTMLElement,
  list: HTMLElement,
  phases: ReviewTexts['phases']
): () => void {
  const phase = createElement('span', { class: 'qa-review-phase' }, [phaseAt(phases, 0)]);
  const elapsed = createElement('span', { class: 'qa-review-elapsed' }, ['0 s']);
  const icon = createElement('span', { class: 'qa-review-loading-icon', 'aria-hidden': 'true' });
  setIcon(icon, SPARKLES_ICON);
  const loading = createElement('div', { class: 'qa-review-loading', 'aria-live': 'polite' }, [
    createElement('div', { class: 'qa-review-loading-row' }, [icon, phase, elapsed]),
    createElement('div', {
      class: 'qa-review-progress',
      role: 'progressbar',
      'aria-label': 'Reviewing',
      'aria-busy': 'true',
    }),
  ]);
  list.before(loading);
  const started = Date.now();
  const timer = window.setInterval(() => {
    if (!container.isConnected) {
      window.clearInterval(timer);
      return;
    }
    const seconds = Math.floor((Date.now() - started) / MS_PER_SECOND);
    elapsed.textContent = `${seconds} s`;
    phase.textContent = phaseAt(phases, seconds);
  }, MS_PER_SECOND);
  return () => {
    window.clearInterval(timer);
    loading.remove();
  };
}
