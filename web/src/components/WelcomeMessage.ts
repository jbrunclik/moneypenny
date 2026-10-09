/**
 * Welcome message shown in an empty conversation. Shared by the initial
 * app shell (core/init.ts) and renderMessages' empty branch so the two
 * can't drift apart.
 */
import { useStore } from '../state/store';
import { escapeHtml } from '../utils/dom';

/** Personal greeting; nameless until the user is known (the pre-auth shell). */
function greeting(): string {
  const firstName = useStore.getState().user?.name.trim().split(/\s+/)[0];
  return firstName ? `What’s on your mind, ${escapeHtml(firstName)}?` : 'What’s on your mind?';
}

export function renderWelcomeMessageHtml(): string {
  return `
    <div class="welcome-message">
      <h2>${greeting()}</h2>
    </div>
  `;
}
