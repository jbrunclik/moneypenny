/**
 * Text-to-speech helpers: voice choice by language code and the text read
 * aloud (UI chrome inside the message is skipped).
 */
import { describe, it, expect, afterEach, vi } from 'vitest';

vi.mock('@/components/Toast', () => ({ toast: { error: vi.fn() } }));

import { findVoiceForLanguage, getSpeechChunks } from '@/core/tts';

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

function content(html: string): HTMLDivElement {
  const el = document.createElement('div');
  el.innerHTML = html;
  return el;
}

describe('getSpeechChunks', () => {
  it('reads prose only - no UI chrome, code, tables or citations - and leaves the DOM untouched', () => {
    const el = content(
      [
        '<div class="thinking-indicator">Thinking...</div>',
        '<p>Hello there<sup class="claim-cite">[1]</sup>.</p>',
        '<div class="copyable-header"><span class="code-language">python</span></div>',
        '<div class="code-block-wrapper"><pre><code>print(1)</code></pre></div>',
        '<div class="table-wrapper"><table><tr><td>42</td></tr></table></div>',
        '<ul><li>First [2] point, see https://example.com/x</li><li>Second</li></ul>',
        '<div class="message-files">report.pdf</div>',
      ].join('')
    );
    expect(getSpeechChunks(el)).toEqual(['Hello there.', 'First point, see', 'Second']);
    expect(el.querySelector('.thinking-indicator')).not.toBeNull();
  });

  it('reads plain text without blocks as one chunk', () => {
    expect(getSpeechChunks(content('Just text [3].'))).toEqual(['Just text.']);
  });

  it('splits a long paragraph at sentence ends', () => {
    const sentence = 'This sentence is about forty-five characters. ';
    const chunks = getSpeechChunks(content(`<p>${sentence.repeat(12)}</p>`));
    expect(chunks.length).toBeGreaterThan(1);
    expect(chunks.every((c) => c.length <= 240 && c.endsWith('.'))).toBe(true);
    expect(chunks.join(' ')).toBe(sentence.repeat(12).trim());
  });

  it('returns nothing for an empty element', () => {
    expect(getSpeechChunks(document.createElement('div'))).toEqual([]);
  });
});
