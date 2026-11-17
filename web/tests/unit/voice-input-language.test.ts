/**
 * Dictation starts in the conversation's language (Nov 17 2026): switching
 * took a hidden long press, so a Czech chat got English dictation until the
 * user found it. A hand pick still wins for its own conversation.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const state = { currentConversation: { id: 'conv-1' } as { id: string } | null };
vi.mock('@/state/store', () => ({ useStore: { getState: () => state } }));

import { languageForRecording } from '@/components/VoiceInput';

function messages(...languages: (string | null)[]): void {
  document.body.innerHTML = `<div id="messages">${languages
    .map((lang) => `<div class="message assistant"${lang ? ` data-language="${lang}"` : ''}></div>`)
    .join('')}</div>`;
}

describe('languageForRecording', () => {
  beforeEach(() => {
    localStorage.clear();
    state.currentConversation = { id: 'conv-1' };
  });

  it("uses the latest message's language", () => {
    messages('en', 'cs', null);
    expect(languageForRecording()).toBe('cs-CZ');
  });

  it('falls back to the saved language when dictation does not support it', () => {
    localStorage.setItem('voice-input-lang', 'en-US');
    messages('de');
    expect(languageForRecording()).toBe(localStorage.getItem('voice-input-lang'));
  });

  it('falls back to the saved language in a chat without a detected language', () => {
    localStorage.setItem('voice-input-lang', 'cs-CZ');
    messages(null);
    expect(languageForRecording()).toBe('cs-CZ');
  });
});
