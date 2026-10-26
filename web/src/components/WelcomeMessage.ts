/**
 * Welcome message shown in an empty conversation. Shared by the initial
 * app shell (core/startup/app-shell.ts) and the views that empty the message
 * list (renderMessages, leaving a feature page) so they can't drift apart.
 */
import { useStore } from '../state/store';

/** Personal greeting (plain text); nameless until the user is known (the pre-auth shell). */
function greeting(): string {
  const firstName = useStore.getState().user?.name.trim().split(/\s+/)[0];
  return firstName ? `What’s on your mind, ${firstName}?` : 'What’s on your mind?';
}

/** The welcome element: the app shell's, and a message list being emptied. */
export function createWelcomeMessage(): HTMLDivElement {
  const welcome = document.createElement('div');
  welcome.className = 'welcome-message';
  const heading = document.createElement('h2');
  heading.textContent = greeting();
  welcome.appendChild(heading);
  return welcome;
}
