/**
 * The Quick actions sheet's Review: the coach's suggested changes to its quick
 * actions and standing instructions, each with the turns it rests on, accepted
 * or rejected one by one (docs/superpowers/specs/2026-11-11-program-self-tuning-design.md).
 * Presentation only: the calls come in as handlers from core/quick-actions.ts.
 */
import type { QuickAction, SetupSuggestion } from '../types/api';
import { clearElement, createElement } from '../utils/dom';

export interface SetupReviewHandlers {
  load: () => Promise<SetupSuggestion[]>;
  /** Resolves with the program's quick actions after the change */
  apply: (suggestion: SetupSuggestion) => Promise<QuickAction[]>;
  reject: (suggestion: SetupSuggestion) => Promise<void>;
}

const LOADING_TEXT = 'Reviewing your quick actions and recent chats…';
const EMPTY_TEXT = 'Nothing to change - your quick actions and instructions match how you use them.';
const FAILED_TEXT = 'The review failed.';

function errorText(error: unknown): string {
  return error instanceof Error && error.message ? error.message : 'Something went wrong.';
}

function itemElement(s: SetupSuggestion): HTMLElement {
  return createElement('li', { class: 'qa-review-item', 'data-state': 'open' }, [
    createElement('div', { class: 'qa-review-summary' }, [s.summary]),
    createElement('div', { class: 'qa-review-change' }, [
      createElement('div', { class: 'qa-review-before' }, [
        createElement('span', { class: 'qa-review-tag' }, ['Before']),
        s.before,
      ]),
      createElement('div', { class: 'qa-review-after' }, [
        createElement('span', { class: 'qa-review-tag' }, ['After']),
        s.after,
      ]),
    ]),
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

async function answer(
  item: HTMLElement,
  run: () => Promise<void>,
  state: 'applied' | 'rejected'
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
    buttons.forEach((b) => (b.disabled = false));
    if (status) status.textContent = errorText(error);
  }
}

function renderSuggestions(
  list: HTMLElement,
  suggestions: SetupSuggestion[],
  handlers: SetupReviewHandlers,
  onApplied: (actions: QuickAction[]) => void
): void {
  suggestions.forEach((s) => {
    const item = itemElement(s);
    item.querySelector('.qa-review-accept')?.addEventListener('click', () => {
      void answer(item, async () => onApplied(await handlers.apply(s)), 'applied');
    });
    item.querySelector('.qa-review-reject')?.addEventListener('click', () => {
      void answer(item, () => handlers.reject(s), 'rejected');
    });
    list.appendChild(item);
  });
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
    status.textContent = LOADING_TEXT;
    try {
      const suggestions = await handlers.load();
      status.textContent = suggestions.length ? '' : EMPTY_TEXT;
      status.hidden = suggestions.length > 0;
      renderSuggestions(list, suggestions, handlers, onApplied);
    } catch {
      status.hidden = false;
      status.textContent = FAILED_TEXT;
      const retry = createElement('button', { type: 'button', class: 'qa-detail-back qa-review-retry' }, ['Try again']);
      retry.addEventListener('click', () => void run());
      list.appendChild(createElement('li', { class: 'qa-review-retry-row' }, [retry]));
    }
  };
  void run();
}
