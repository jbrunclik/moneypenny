/**
 * Text-to-speech module.
 * Handles speech synthesis and voice management.
 */

import { createLogger } from '../utils/logger';
import { toast } from '../components/Toast';
import { SPEAKER_ICON, STOP_ICON } from '../utils/icons';

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

/**
 * Extract text content for TTS, excluding UI elements.
 */
export function getTextContentForTTS(element: HTMLElement): string {
  // Clone to avoid modifying the actual DOM
  const clone = element.cloneNode(true) as HTMLElement;

  // Remove elements we don't want to read (UI elements, file attachments, etc.)
  clone.querySelectorAll('.thinking-indicator, .inline-copy-btn, .code-language, .copyable-header, .message-files').forEach(el => el.remove());

  // Get text content
  return clone.textContent || '';
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
        speakingButton.innerHTML = SPEAKER_ICON;
        return;
      }
    }
  }

  // Clear any previous speaking state and restore icons
  document.querySelectorAll('.message-speak-btn.speaking').forEach(btn => {
    btn.classList.remove('speaking');
    btn.innerHTML = SPEAKER_ICON;
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

  // Get text content, excluding thinking/tool traces and inline copy buttons
  const textContent = getTextContentForTTS(contentEl as HTMLElement);
  if (!textContent.trim()) {
    log.warn('No text content to speak', { messageId });
    return;
  }

  // Create utterance
  const utterance = new SpeechSynthesisUtterance(textContent);

  // Set language and find appropriate voice
  if (language) {
    // Set the lang attribute (browser may use this as fallback)
    utterance.lang = language;

    // Try to find a voice for this language
    const matchingVoice = findVoiceForLanguage(language);
    if (matchingVoice) {
      utterance.voice = matchingVoice;
    } else {
      log.warn('No voice found for language, using browser default', { language });
    }
  }

  // Mark button as speaking and swap to stop icon
  const speakBtn = messageEl.querySelector('.message-speak-btn');
  if (speakBtn) {
    speakBtn.classList.add('speaking');
    speakBtn.innerHTML = STOP_ICON;
  }

  // Handle end of speech - restore speaker icon
  utterance.onend = () => {
    speakBtn?.classList.remove('speaking');
    if (speakBtn) {
      speakBtn.innerHTML = SPEAKER_ICON;
    }
  };

  utterance.onerror = (event) => {
    log.error('TTS error', { error: event.error, messageId });
    speakBtn?.classList.remove('speaking');
    if (speakBtn) {
      speakBtn.innerHTML = SPEAKER_ICON;
    }
    // Don't show error for user-initiated cancellation or interruption
    if (event.error !== 'canceled' && event.error !== 'interrupted') {
      toast.error('Failed to read message aloud.');
    }
  };

  speechSynthesis.speak(utterance);
  log.info('Started TTS', { messageId, language, voice: utterance.voice?.name });
}
