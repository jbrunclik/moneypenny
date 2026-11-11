/**
 * The Quick actions sheet's Review: the coach's suggested changes to its quick
 * actions and standing instructions, each with the turns it rests on, accepted
 * or rejected one by one (docs/superpowers/specs/2026-11-11-program-self-tuning-design.md).
 * Presentation only: the calls come in as handlers from core/quick-actions.ts.
 */
import { QUICK_ACTION_REVIEW_PHASES } from '../config';
import { MS_PER_SECOND } from '../constants';
import type { QuickAction, SetupSuggestion } from '../types/api';
import { clearElement, createElement } from '../utils/dom';
import { SPARKLES_ICON, setIcon } from '../utils/icons';

export interface SetupReviewHandlers {
  load: () => Promise<SetupSuggestion[]>;
  /** Resolves with the program's quick actions after the change */
  apply: (suggestion: SetupSuggestion) => Promise<QuickAction[]>;
  reject: (suggestion: SetupSuggestion) => Promise<void>;
}

const EMPTY_TEXT = 'Nothing to change - your quick actions and instructions match how you use them.';
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

function itemElement(s: SetupSuggestion): HTMLElement {
  return createElement('li', { class: 'qa-review-item', 'data-state': 'open' }, [
    createElement('div', { class: 'qa-review-summary' }, [s.summary]),
    createElement('div', { class: 'qa-review-change' }, s.changes.map(fieldRow)),
    createElement(
      'ul',
      { class: 'qa-review-evidence', 'aria-label': 'Based on' },
      s.evidence.map((line) => createElement('li', {}, [line]))
    ),
    createElement('div', { class: 'qa-review-actions' }, [
      createElement('button', { type: 'button', class: 'qa-review-reject' }, ['Reject']),
      createElement('button', { type: 'button', class: 'qa-review-accept' }, ['Accept']),
    ]),
    createElement('div', { class: 'qa-review-item-status', 'aria-live': 'polite' }),
  ]);
}

/**
 * Thrown by `apply` when what the suggestion touches changed since the review
 * (a collision): it carries the same change against the setup as it is now.
 */
export class SuggestionRefreshed extends Error {
  constructor(readonly suggestion: SetupSuggestion) {
    super('This changed since the review.');
    this.name = 'SuggestionRefreshed';
  }
}

const REFRESHED_TEXT = 'This changed since the review - here is the updated change.';

interface ItemContext {
  handlers: SetupReviewHandlers;
  onApplied: (actions: QuickAction[]) => void;
}

async function answer(
  item: HTMLElement,
  run: () => Promise<void>,
  state: 'applied' | 'rejected',
  ctx: ItemContext
): Promise<void> {
  const status = item.querySelector<HTMLElement>('.qa-review-item-status');
  const buttons = item.querySelectorAll<HTMLButtonElement>('.qa-review-actions button');
  buttons.forEach((b) => (b.disabled = true));
  try {
    await run();
    item.dataset.state = state;
    item.querySelector('.qa-review-actions')?.remove();
    if (status) status.textContent = state === 'applied' ? 'Applied' : 'Rejected';
  } catch (error) {
    if (error instanceof SuggestionRefreshed) {
      // A collision is not a dead end: the updated change, ready to accept again
      const fresh = liveItem(error.suggestion, ctx);
      const freshStatus = fresh.querySelector<HTMLElement>('.qa-review-item-status');
      if (freshStatus) freshStatus.textContent = REFRESHED_TEXT;
      item.replaceWith(fresh);
      return;
    }
    buttons.forEach((b) => (b.disabled = false));
    if (status) status.textContent = errorText(error);
  }
}

/** A suggestion's card with its Accept / Reject wired. */
function liveItem(s: SetupSuggestion, ctx: ItemContext): HTMLElement {
  const item = itemElement(s);
  item.querySelector('.qa-review-accept')?.addEventListener('click', () => {
    void answer(item, async () => ctx.onApplied(await ctx.handlers.apply(s)), 'applied', ctx);
  });
  item.querySelector('.qa-review-reject')?.addEventListener('click', () => {
    void answer(item, () => ctx.handlers.reject(s), 'rejected', ctx);
  });
  return item;
}

function renderSuggestions(
  list: HTMLElement,
  suggestions: SetupSuggestion[],
  handlers: SetupReviewHandlers,
  onApplied: (actions: QuickAction[]) => void
): void {
  suggestions.forEach((s) => list.appendChild(liveItem(s, { handlers, onApplied })));
}

/**
 * Render the Review into `container` and start it. `onApplied` gets the
 * program's quick actions after each accepted change; `back` returns to the list.
 */
export function renderSetupReview(
  container: HTMLElement,
  handlers: SetupReviewHandlers,
  onApplied: (actions: QuickAction[]) => void,
  back: () => void
): void {
  clearElement(container);
  const backButton = createElement('button', { type: 'button', class: 'qa-detail-back qa-review-back' }, ['Back']);
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
    const stopLoading = showLoading(container, list);
    try {
      const suggestions = await handlers.load();
      stopLoading();
      status.hidden = suggestions.length > 0;
      status.textContent = suggestions.length ? '' : EMPTY_TEXT;
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
function phaseAt(seconds: number): string {
  let text = QUICK_ACTION_REVIEW_PHASES[0]?.text ?? '';
  for (const phase of QUICK_ACTION_REVIEW_PHASES) {
    if (seconds >= phase.afterSeconds) text = phase.text;
  }
  return text;
}

/**
 * While the Review runs: the step it is on, the seconds so far and a moving
 * bar (no placeholder cards: they looked like a count of coming results).
 * Returns the function that removes them (and stops the clock).
 */
function showLoading(container: HTMLElement, list: HTMLElement): () => void {
  const phase = createElement('span', { class: 'qa-review-phase' }, [phaseAt(0)]);
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
    phase.textContent = phaseAt(seconds);
  }, MS_PER_SECOND);
  return () => {
    window.clearInterval(timer);
    loading.remove();
  };
}
