/**
 * Welcome message shown in an empty conversation. Shared by the initial
 * app shell (core/init.ts) and renderMessages' empty branch so the two
 * can't drift apart.
 */

export function renderWelcomeMessageHtml(): string {
  return `
    <div class="welcome-message">
      <h2>What can I help with?</h2>
    </div>
  `;
}
