/**
 * The Quick actions sheet's Review: the coach's suggested changes to its quick
 * actions and standing instructions, each with the turns it rests on, accepted
 * or rejected one by one (docs/superpowers/specs/2026-11-11-program-self-tuning-design.md).
 * Presentation only: the calls come in as handlers (core/quick-actions.ts for
 * the sheet). Settings' instructions Review renders the same cards with its
 * own texts (docs/superpowers/specs/2026-11-11-instructions-self-tuning-design.md).
 */
import { ApiError } from '../api/http';
import { SuggestionRefreshed } from '../api/setup-review';
import { changeRows, evidenceList } from './setup-change';
import { QUICK_ACTION_REVIEW_PHASES } from '../config';
import { MS_PER_SECOND } from '../constants';
import type { QuickAction, SetupSuggestion } from '../types/api';
import { clearElement, createElement } from '../utils/dom';
import { CHECK_ICON, CLOSE_ICON, INFO_ICON, SPARKLES_ICON, WARNING_ICON, iconNodes, setIcon } from '../utils/icons';
import { createEmptyState } from './EmptyState';
import type { IconHtml } from '../utils/icons';

/** The Review's calls; `apply` resolves with what changed (the sheet: the program's quick actions). */
export interface SetupReviewHandlers<T = QuickAction[]> {
  load: () => Promise<SetupSuggestion[]>;
  apply: (suggestion: SetupSuggestion) => Promise<T>;
  reject: (suggestion: SetupSuggestion) => Promise<void>;
}

/**
 * What a Review says: its empty line, its timed loading steps, and how it is
 * left - "back" to the list it came from (the sheet), or "close" when it opened
 * in place (Settings: a "Done" there read as "the review is done").
 */
export interface ReviewTexts {
  /** "Nothing to change": the hint under it (what matches how they're used) */
  empty: string;
  phases: readonly { afterSeconds: number; text: string }[];
  leave: 'back' | 'close';
}

const QUICK_ACTION_TEXTS: ReviewTexts = {
  empty: 'Your quick actions and instructions match how you use them.',
  phases: QUICK_ACTION_REVIEW_PHASES,
  leave: 'back',
};

function countText(n: number): string {
  return n === 1 ? '1 suggestion' : `${n} suggestions`;
}

/** Once every card is answered: what came of them (null while one is open). */
function doneText(list: HTMLElement): string | null {
  const items = [...list.querySelectorAll<HTMLElement>('.qa-review-item')];
  if (!items.length || items.some((i) => i.dataset.state === 'open')) return null;
  const count = (state: string): number => items.filter((i) => i.dataset.state === state).length;
  const [applied, rejected, failed] = [count('applied'), count('rejected'), count('failed')];
  const parts = [
    applied && `${applied} applied`,
    rejected && `${rejected} rejected`,
    failed && `${failed} no longer applied`,
  ].filter(Boolean);
  return `${parts.join(', ')}.`;
}

/** The app's empty state, compact and green: nothing to change, or all done. */
function resultState(title: string, hint: string, className: string): HTMLElement {
  return createElement('li', { class: `qa-review-result ${className}` }, [
    createEmptyState({ icon: CHECK_ICON, title, hint, variant: 'success', compact: true }),
  ]);
}

function leaveButton(leave: ReviewTexts['leave'], back: () => void): HTMLButtonElement {
  const button =
    leave === 'back'
      ? createElement('button', { type: 'button', class: 'qa-detail-back qa-review-back' }, ['Back'])
      : createElement('button', {
          type: 'button',
          class: 'qa-review-back qa-review-close',
          'aria-label': 'Close suggestions',
          title: 'Close',
        });
  if (leave === 'close') setIcon(button, CLOSE_ICON);
  button.addEventListener('click', back);
  return button;
}
const FAILED_TEXT = 'The review failed.';

function errorText(error: unknown): string {
  return error instanceof Error && error.message ? error.message : 'Something went wrong.';
}

function itemElement(s: SetupSuggestion): HTMLElement {
  return createElement('li', { class: 'qa-review-item', 'data-state': 'open' }, [
    createElement('div', { class: 'qa-review-item-head' }, [
      createElement('div', { class: 'qa-review-summary' }, [s.summary]),
      createElement('div', { class: 'qa-review-item-status', 'aria-live': 'polite' }),
    ]),
    changeRows(s.changes),
    evidenceList(s.evidence),
    createElement('div', { class: 'qa-review-actions' }, [
      createElement('button', { type: 'button', class: 'btn btn-secondary btn-sm qa-review-reject' }, ['Reject']),
      createElement('button', { type: 'button', class: 'btn btn-primary btn-sm qa-review-accept' }, ['Accept']),
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
  /** After each answer: the list may now be all done */
  onAnswered: () => void;
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
  const pressed = item.querySelector<HTMLButtonElement>(
    state === 'applied' ? '.qa-review-accept' : '.qa-review-reject'
  );
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
    ctx.onAnswered();
  } catch (error) {
    if (error instanceof SuggestionRefreshed) {
      // A collision is not a dead end: the updated change, ready to accept again
      const fresh = liveItem(error.suggestion, ctx);
      setStatus(fresh, 'info', REFRESHED_TEXT);
      item.replaceWith(fresh);
      return;
    }
    if (closeIfFinal(item, error)) {
      ctx.onAnswered();
      return;
    }
    buttons.forEach((b) => (b.disabled = false));
    if (pressed) pressed.textContent = label;
    setStatus(item, 'error', errorText(error));
  }
}

/**
 * A suggestion that can never apply (400: gone, ambiguous, already there)
 * closes like an answered card instead of offering Accept forever; true when
 * it did.
 */
function closeIfFinal(item: HTMLElement, error: unknown): boolean {
  if (!(error instanceof ApiError && error.status === 400)) return false;
  item.dataset.state = 'failed';
  item.querySelector('.qa-review-actions')?.remove();
  item.querySelector('.qa-review-evidence')?.remove();
  setStatus(item, 'error', errorText(error));
  return true;
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

function renderSuggestions<T>(list: HTMLElement, suggestions: SetupSuggestion[], ctx: ItemContext<T>): void {
  suggestions.forEach((s) => list.appendChild(liveItem(s, ctx)));
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
  const title = createElement('span', { class: 'qa-detail-section-title qa-review-title' }, ['Suggestions']);
  // Opened in place (Settings): the title reads like the section's own labels
  const heading =
    texts.leave === 'close'
      ? createElement('span', { class: 'qa-review-heading' }, [
          createElement('span', { class: 'qa-review-heading-icon', 'aria-hidden': 'true' }, [iconNodes(SPARKLES_ICON)]),
          title,
        ])
      : title;
  const leave = leaveButton(texts.leave, back);
  const list = createElement('ul', { class: 'qa-review-list' });
  // Back leads (it goes somewhere); a close sits at the end, out of the title's way
  const header = texts.leave === 'back' ? [leave, heading] : [heading, leave];
  container.append(createElement('div', { class: `qa-review-header qa-review-header--${texts.leave}` }, header), list);
  const ctx: ItemContext<T> = {
    handlers,
    onApplied,
    onAnswered: () => {
      const done = doneText(list);
      if (done !== null && !list.querySelector('.qa-review-done')) {
        list.prepend(resultState('All done', done, 'qa-review-done'));
      }
    },
  };

  const run = async (): Promise<void> => {
    clearElement(list);
    const stopLoading = showLoading(container, list, texts.phases);
    try {
      const suggestions = await handlers.load();
      stopLoading();
      title.textContent = suggestions.length ? countText(suggestions.length) : 'Suggestions';
      if (!suggestions.length) list.appendChild(resultState('Nothing to change', texts.empty, 'qa-review-empty'));
      renderSuggestions(list, suggestions, ctx);
    } catch (error) {
      stopLoading();
      list.appendChild(failedNotice(error, () => void run()));
    }
  };
  void run();
}

/** The Review failed: one notice - what, why, that nothing changed - and Try again. */
function failedNotice(error: unknown, retry: () => void): HTMLElement {
  const again = createElement('button', { type: 'button', class: 'btn btn-secondary btn-sm qa-review-retry' }, [
    'Try again',
  ]);
  again.addEventListener('click', retry);
  return createElement('li', { class: 'qa-review-error', role: 'alert' }, [
    createElement('span', { class: 'qa-review-error-icon', 'aria-hidden': 'true' }, [iconNodes(WARNING_ICON)]),
    createElement('div', { class: 'qa-review-error-body' }, [
      createElement('p', { class: 'qa-review-error-title' }, [FAILED_TEXT]),
      createElement('p', { class: 'qa-review-error-detail' }, [`${errorText(error)} Nothing was changed.`]),
      again,
    ]),
  ]);
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
function showLoading(container: HTMLElement, list: HTMLElement, phases: ReviewTexts['phases']): () => void {
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
