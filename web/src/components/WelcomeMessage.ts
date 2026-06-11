/**
 * Welcome message shown in an empty conversation, with suggested-prompt
 * chips that send a starter message showcasing the app's capabilities.
 */

import { escapeHtml } from '../utils/dom';

const SUGGESTED_PROMPTS = [
  'Plan my day',
  "What's in the news today?",
  'Quiz me on vocabulary',
  'Help me draft an email',
] as const;

/**
 * Render the welcome message HTML (used by the initial app shell and by
 * renderMessages when a conversation has no messages). Chip clicks are
 * handled via event delegation on #messages (see core/events.ts).
 */
export function renderWelcomeMessageHtml(): string {
  const chips = SUGGESTED_PROMPTS.map(
    (prompt) =>
      `<button class="suggestion-chip" data-prompt="${escapeHtml(prompt)}">${escapeHtml(prompt)}</button>`
  ).join('');
  return `
    <div class="welcome-message">
      <h2>Welcome to AI Chatbot</h2>
      <p>Start a conversation with Gemini AI</p>
      <div class="welcome-suggestions">${chips}</div>
    </div>
  `;
}
