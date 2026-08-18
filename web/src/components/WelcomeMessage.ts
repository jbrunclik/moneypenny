/**
 * Welcome message shown in an empty conversation. Shared by the initial
 * app shell (core/init.ts) and renderMessages' empty branch so the two
 * can't drift apart.
 *
 * Suggested-prompt chips fill the composer on click (delegated handler
 * in core/events.ts).
 */

import { escapeHtml } from '../utils/dom';

const SUGGESTED_PROMPTS: string[] = [
  'Summarize this link: ',
  'Plan my week',
  'What should I train today?',
  'Quiz me in Italian',
];

export function renderWelcomeMessageHtml(): string {
  const chips = SUGGESTED_PROMPTS.map(
    (p) =>
      `<button class="welcome-prompt-chip" data-prompt="${escapeHtml(p)}">${escapeHtml(p.trim())}</button>`,
  ).join('');
  return `
    <div class="welcome-message">
      <h2>What can I help with?</h2>
      <div class="welcome-prompts">${chips}</div>
    </div>
  `;
}
