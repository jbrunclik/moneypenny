/**
 * Welcome message shown in an empty conversation. Shared by the initial
 * app shell (core/init.ts) and renderMessages' empty branch so the two
 * can't drift apart.
 */

export function renderWelcomeMessageHtml(): string {
  return `
    <div class="welcome-message">
      <h2>Welcome to AI Chatbot</h2>
      <p>Start a conversation with Gemini AI</p>
    </div>
  `;
}
