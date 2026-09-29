/**
 * Note on assistant replies cut off by the tool-round cap.
 *
 * When a turn hits AGENT_MAX_TOOL_ROUNDS the model is told to stop gathering
 * and answer with what it has (Sep 2026: ~3% of turns), so the reply can be
 * partial. The server flags it `stopped_early`; this note says so and offers
 * Continue, which reuses the existing continue re-run. CSS shows the button
 * only on the latest assistant reply, where a re-run makes sense.
 */

const NOTE_CLASS = 'message-stopped-early';

/** Insert the note before the message actions (idempotent). */
export function appendStoppedEarlyNote(contentWrapper: HTMLElement, messageId: string): void {
  if (contentWrapper.querySelector(`.${NOTE_CLASS}`)) return;

  const note = document.createElement('div');
  note.className = NOTE_CLASS;
  const text = document.createElement('span');
  text.textContent = 'Stopped at the tool-step limit - this answer may be incomplete.';
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
