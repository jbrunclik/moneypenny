/**
 * Voice input: recognized speech lands in the composer after what was
 * typed, the button reflects recording, and recognition errors explain
 * themselves (or stay quiet for timeouts and aborts).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

const toastError = vi.hoisted(() => vi.fn());
vi.mock('@/components/Toast', () => ({ toast: { error: toastError } }));
vi.mock('@/components/MessageInput', () => ({ updateSendButtonState: vi.fn() }));
vi.mock('@/utils/haptics', () => ({ hapticTick: vi.fn() }));

import { initVoiceInput } from '@/components/VoiceInput';

class FakeRecognition {
  static last: FakeRecognition | null = null;
  continuous = false;
  interimResults = false;
  lang = '';
  onresult: ((event: unknown) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onend: (() => void) | null = null;
  onstart: (() => void) | null = null;
  start = vi.fn(() => this.onstart?.());
  stop = vi.fn(() => this.onend?.());
  abort = vi.fn();
  constructor() {
    FakeRecognition.last = this;
  }
}

/** A recognition result event: [transcript, isFinal] per result. */
function results(resultIndex: number, ...items: [string, boolean][]): unknown {
  return {
    resultIndex,
    results: items.map(([transcript, isFinal]) => Object.assign([{ transcript }], { isFinal })),
  };
}

describe('voice input', () => {
  let btn: HTMLButtonElement;
  let input: HTMLTextAreaElement;
  const rec = (): FakeRecognition => FakeRecognition.last as FakeRecognition;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('SpeechRecognition', FakeRecognition);
    localStorage.setItem('voice-input-lang', 'en-US');
    document.body.innerHTML = '<button id="voice-btn"></button><textarea id="message-input"></textarea>';
    btn = document.getElementById('voice-btn') as HTMLButtonElement;
    input = document.getElementById('message-input') as HTMLTextAreaElement;
    initVoiceInput();
  });

  afterEach(() => {
    rec().onend?.(); // recording state is module-level: end it between tests
    vi.unstubAllGlobals();
  });

  it('configures continuous recognition with interim results', () => {
    expect(rec().continuous).toBe(true);
    expect(rec().interimResults).toBe(true);
  });

  it('appends speech after typed text with a separating space', () => {
    input.value = 'Hello';
    btn.click();
    expect(btn.classList.contains('recording')).toBe(true);
    expect(btn.getAttribute('aria-pressed')).toBe('true');

    rec().onresult?.(results(0, ['world', false]));
    expect(input.value).toBe('Hello world');

    rec().onresult?.(results(0, ['world. ', true], ['How', false]));
    expect(input.value).toBe('Hello world. How');
  });

  it('stops on a second click and resets the button', () => {
    btn.click();
    btn.click();
    expect(rec().stop).toHaveBeenCalled();
    expect(btn.classList.contains('recording')).toBe(false);
    expect(btn.getAttribute('aria-pressed')).toBe('false');
    expect(btn.title).toMatch(/^Voice input \(/);
  });

  it.each([
    ['not-allowed', 'Microphone access denied'],
    ['network', 'requires an internet connection'],
    ['service-not-allowed', 'not available'],
    ['bad-grammar', 'Speech recognition failed'],
  ])('explains a %s error', (error, text) => {
    btn.click();
    rec().onerror?.({ error });
    expect(toastError).toHaveBeenCalledWith(expect.stringContaining(text));
    expect(btn.classList.contains('recording')).toBe(false);
  });

  it.each([['no-speech'], ['aborted']])('stays quiet on %s', (error) => {
    btn.click();
    rec().onerror?.({ error });
    expect(toastError).not.toHaveBeenCalled();
    expect(btn.classList.contains('recording')).toBe(false);
  });
});
