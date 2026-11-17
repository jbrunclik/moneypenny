/**
 * Text-to-speech module.
 * Handles speech synthesis and voice management.
 */

import { createLogger } from '../utils/logger';
import { toast } from '../components/Toast';
import { SPEAKER_ICON, STOP_ICON, setIcon } from '../utils/icons';

const log = createLogger('tts');

/**
 * Preload voices for TTS (some browsers load them asynchronously).
 */
export function initTTSVoices(): void {
  if (!('speechSynthesis' in window)) {
    log.debug('Speech synthesis not supported');
    return;
  }

  // Try to get voices immediately (works in some browsers)
  const voices = speechSynthesis.getVoices();
  if (voices.length > 0) {
    log.debug('TTS voices loaded', { count: voices.length });
    return;
  }

  // In Chrome, voices load asynchronously
  speechSynthesis.addEventListener('voiceschanged', () => {
    const loadedVoices = speechSynthesis.getVoices();
    log.debug('TTS voices loaded (async)', { count: loadedVoices.length });
  }, { once: true });
}

/**
 * Find the best voice for a language code.
 */
export function findVoiceForLanguage(langCode: string): SpeechSynthesisVoice | null {
  const voices = speechSynthesis.getVoices();
  if (voices.length === 0) {
    log.debug('No voices available yet');
    return null;
  }

  // Normalize the language code
  const normalizedLang = langCode.toLowerCase();

  // Try to find a voice that matches:
  // 1. Exact match (e.g., "cs" matches "cs" or "cs-CZ" matches "cs-CZ")
  // 2. Primary language match (e.g., "cs" matches "cs-CZ")

  // First, try to find a voice where the lang starts with our code
  const matchingVoice = voices.find(v =>
    v.lang.toLowerCase().startsWith(normalizedLang + '-') ||
    v.lang.toLowerCase() === normalizedLang
  );

  if (matchingVoice) {
    log.debug('Found matching voice', { langCode, voice: matchingVoice.name, voiceLang: matchingVoice.lang });
    return matchingVoice;
  }

  // Log available voices for debugging
  log.debug('No voice found for language', {
    langCode,
    availableVoices: voices.map(v => ({ name: v.name, lang: v.lang })),
  });

  return null;
}

// Not read aloud: UI chrome, and blocks that make no sense spoken (code,
// tables, diagrams, formulas, artifacts, citation marks, the grounding note)
const SKIPPED_FOR_SPEECH = [
  '.thinking-indicator',
  '.inline-copy-btn',
  '.code-language',
  '.copyable-header',
  '.message-files',
  'pre',
  '.code-block-wrapper',
  '.table-wrapper',
  'table',
  '.mermaid-diagram',
  '.katex',
  '.artifact-list',
  '.claim-cite',
  '.grounding-footer',
  'sup',
].join(', ');

// Blocks read as separate utterances: one long utterance gets cut off by
// some browsers, and a pause between paragraphs reads more naturally
const SPEECH_BLOCKS = 'p, li, h1, h2, h3, h4, h5, h6, blockquote, dt, dd';

// Inline citation numbers ("[1]", "[2, 3]") and bare links read as noise
const CITATION_NUMBERS = /\s*\[\d+(?:\s*[,–-]\s*\d+)*\]/g;
const URLS = /https?:\/\/\S+/g;

// Longer chunks are split at sentence ends (some voices stop after ~15 s)
const MAX_UTTERANCE_CHARS = 240;

function speakable(text: string): string {
  return text.replace(CITATION_NUMBERS, '').replace(URLS, '').replace(/\s+/g, ' ').trim();
}

function splitLong(text: string): string[] {
  if (text.length <= MAX_UTTERANCE_CHARS) return [text];
  const sentences = text.match(/[^.!?…]+[.!?…]*\s*/g) ?? [text];
  const chunks: string[] = [];
  let current = '';
  for (const sentence of sentences) {
    if (current && current.length + sentence.length > MAX_UTTERANCE_CHARS) {
      chunks.push(current.trim());
      current = '';
    }
    current += sentence;
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks;
}

/**
 * The message text read aloud, as utterance-sized chunks: prose blocks in
 * order, without UI chrome, code, tables, citation numbers or links.
 */
export function getSpeechChunks(element: HTMLElement): string[] {
  // Clone to avoid modifying the actual DOM
  const clone = element.cloneNode(true) as HTMLElement;
  clone.querySelectorAll(SKIPPED_FOR_SPEECH).forEach((el) => el.remove());

  // Innermost blocks only (a list item's nested list is its own block)
  const blocks = [...clone.querySelectorAll<HTMLElement>(SPEECH_BLOCKS)].filter(
    (el) => !el.querySelector(SPEECH_BLOCKS)
  );
  const texts = blocks.length ? blocks.map((el) => el.textContent ?? '') : [clone.textContent ?? ''];
  return texts.map(speakable).filter(Boolean).flatMap(splitLong);
}



/**
 * Speak a message using Web Speech API.
 */
export function speakMessageInternal(messageId: string, language?: string): void {
  // Cancel any ongoing speech first
  if (speechSynthesis.speaking) {
    speechSynthesis.cancel();
    // If clicking the same message that was speaking, just stop (toggle behavior)
    const speakingButton = document.querySelector('.message-speak-btn.speaking');
    if (speakingButton) {
      const speakingMsgId = speakingButton.closest('.message')?.getAttribute('data-message-id');
      if (speakingMsgId === messageId) {
        speakingButton.classList.remove('speaking');
        setIcon(speakingButton, SPEAKER_ICON);
        return;
      }
    }
  }

  // Clear any previous speaking state and restore icons
  document.querySelectorAll('.message-speak-btn.speaking').forEach(btn => {
    btn.classList.remove('speaking');
    setIcon(btn, SPEAKER_ICON);
  });

  // Get the message content
  const messageEl = document.querySelector(`.message[data-message-id="${messageId}"]`);
  if (!messageEl) {
    log.warn('Message not found for TTS', { messageId });
    return;
  }

  const contentEl = messageEl.querySelector('.message-content');
  if (!contentEl) {
    log.warn('Message content not found for TTS', { messageId });
    return;
  }

  const chunks = getSpeechChunks(contentEl as HTMLElement);
  if (!chunks.length) {
    log.warn('No text content to speak', { messageId });
    return;
  }

  // One utterance per chunk, queued; the last one's end restores the button
  const voice = language ? findVoiceForLanguage(language) : null;
  if (language && !voice) {
    log.warn('No voice found for language, using browser default', { language });
  }
  const utterances = chunks.map((chunk) => {
    const utterance = new SpeechSynthesisUtterance(chunk);
    if (language) utterance.lang = language; // the browser's fallback when there is no voice
    if (voice) utterance.voice = voice;
    return utterance;
  });
  const utterance = utterances.at(-1);
  if (!utterance) return;

  // Mark button as speaking and swap to stop icon
  const speakBtn = messageEl.querySelector('.message-speak-btn');
  if (speakBtn) {
    speakBtn.classList.add('speaking');
    setIcon(speakBtn, STOP_ICON);
  }

  // Handle end of speech - restore speaker icon
  utterance.onend = () => {
    speakBtn?.classList.remove('speaking');
    if (speakBtn) {
      setIcon(speakBtn, SPEAKER_ICON);
    }
  };

  const onError = (event: SpeechSynthesisErrorEvent): void => {
    // Don't log or toast user-initiated cancellation or interruption
    if (event.error === 'canceled' || event.error === 'interrupted') return;
    log.error('TTS error', { error: event.error, messageId });
    speechSynthesis.cancel(); // drop the rest of the queue
    speakBtn?.classList.remove('speaking');
    if (speakBtn) {
      setIcon(speakBtn, SPEAKER_ICON);
    }
    toast.error('Failed to read message aloud.');
  };
  utterances.forEach((u) => {
    u.onerror = onError;
    speechSynthesis.speak(u);
  });
  log.info('Started TTS', { messageId, language, voice: voice?.name, chunks: utterances.length });
}
