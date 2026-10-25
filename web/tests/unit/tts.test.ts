/**
 * Text-to-speech helpers: voice choice by language code and the text read
 * aloud (UI chrome inside the message is skipped).
 */
import { describe, it, expect, afterEach, vi } from 'vitest';

vi.mock('@/components/Toast', () => ({ toast: { error: vi.fn() } }));

import { findVoiceForLanguage, getTextContentForTTS } from '@/core/tts';

function voice(name: string, lang: string): SpeechSynthesisVoice {
  return { name, lang } as SpeechSynthesisVoice;
}

function stubVoices(voices: SpeechSynthesisVoice[]): void {
  vi.stubGlobal('speechSynthesis', { getVoices: () => voices });
}

describe('findVoiceForLanguage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns null while no voices are loaded', () => {
    stubVoices([]);
    expect(findVoiceForLanguage('en')).toBeNull();
  });

  it('matches a regional voice by its primary language', () => {
    stubVoices([voice('Daniel', 'en-GB'), voice('Zuzana', 'cs-CZ')]);
    expect(findVoiceForLanguage('cs')?.name).toBe('Zuzana');
  });

  it('matches case-insensitively and exactly', () => {
    stubVoices([voice('Generic', 'cs'), voice('Daniel', 'en-GB')]);
    expect(findVoiceForLanguage('CS')?.name).toBe('Generic');
    expect(findVoiceForLanguage('en-gb')?.name).toBe('Daniel');
  });

  it('does not match a language that merely shares a prefix', () => {
    // "c" must not pick Czech, "en" must not pick a hypothetical "eng" voice
    stubVoices([voice('Zuzana', 'cs-CZ'), voice('Odd', 'eng')]);
    expect(findVoiceForLanguage('c')).toBeNull();
    expect(findVoiceForLanguage('en')).toBeNull();
  });

  it('returns the first matching voice', () => {
    stubVoices([voice('First', 'de-DE'), voice('Second', 'de-AT')]);
    expect(findVoiceForLanguage('de')?.name).toBe('First');
  });
});

describe('getTextContentForTTS', () => {
  it('reads the message text without UI chrome and leaves the DOM untouched', () => {
    const content = document.createElement('div');
    content.innerHTML = [
      '<div class="thinking-indicator">Thinking...</div>',
      '<p>Hello there.</p>',
      '<div class="copyable-header"><span class="code-language">python</span></div>',
      '<pre><code>print(1)</code><button class="inline-copy-btn">Copy</button></pre>',
      '<div class="message-files">report.pdf</div>',
    ].join('');
    expect(getTextContentForTTS(content)).toBe('Hello there.print(1)');
    expect(content.querySelector('.thinking-indicator')).not.toBeNull();
  });

  it('returns an empty string for an empty element', () => {
    expect(getTextContentForTTS(document.createElement('div'))).toBe('');
  });
});
