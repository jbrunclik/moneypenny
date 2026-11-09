/**
 * Note on assistant replies cut off by a turn budget.
 *
 * When a turn runs out of its cost, time or round budget, or loops, the model
 * answers once with tools off, so the reply can be partial. The server flags
 * it `stopped_early` (from `stopped_by`); this note says so and offers
 * Continue, which reuses the existing continue re-run. CSS shows the button
 * only on the latest assistant reply, where a re-run makes sense.
 * The same note marks replies the user stopped (server stop_reason "user").
 */

const NOTE_CLASS = 'message-stopped-early';

const NOTE_TEXT: Record<'budget' | 'user', string> = {
  budget: 'Stopped before finishing - this answer may be incomplete.',
  user: 'Stopped.',
};

/** Insert the note before the message actions (idempotent). */
export function appendStoppedEarlyNote(
  contentWrapper: HTMLElement,
  messageId: string,
  reason: 'budget' | 'user' = 'budget'
): void {
  if (contentWrapper.querySelector(`.${NOTE_CLASS}`)) return;

  const note = document.createElement('div');
  note.className = NOTE_CLASS;
  const text = document.createElement('span');
  text.textContent = NOTE_TEXT[reason];
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'message-stopped-early-continue';
  button.textContent = 'Continue';
  button.addEventListener('click', () => {
    document.dispatchEvent(new CustomEvent('message:continue', { detail: { messageId } }));
  });
  note.append(text, button);

  const actions = contentWrapper.querySelector('.message-actions');
  if (actions) {
    contentWrapper.insertBefore(note, actions);
  } else {
    contentWrapper.appendChild(note);
  }
}
