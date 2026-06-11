import { getElementById, autoResizeTextarea } from '../utils/dom';
import { MICROPHONE_ICON, STOP_ICON } from '../utils/icons';
import { updateSendButtonState } from './MessageInput';
import { toast } from './Toast';
import { isTouchDevice } from '../gestures/swipe';
import { createLogger } from '../utils/logger';

const log = createLogger('voice');

// Language display names
const LANGUAGE_NAMES: Record<string, string> = {
  'en-US': 'English',
  'en': 'English',
  'cs-CZ': 'Čeština',
  'cs': 'Čeština',
};

// Storage key for persisted language preference
const STORAGE_KEY_LANG = 'voice-input-lang';

// Long-press duration in milliseconds
const LONG_PRESS_DURATION = 500;

// Extend Window interface for SpeechRecognition
interface SpeechRecognitionEvent extends Event {
  results: SpeechRecognitionResultList;
  resultIndex: number;
}

interface SpeechRecognitionErrorEvent extends Event {
  error: string;
  message?: string;
}

interface SpeechRecognition extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
}

declare global {
  interface Window {
    SpeechRecognition: new () => SpeechRecognition;
    webkitSpeechRecognition: new () => SpeechRecognition;
  }
}

let recognition: SpeechRecognition | null = null;
let isRecording = false;
let currentLang = '';
let langSelectorVisible = false;

/**
 * Check if SpeechRecognition is supported in the browser
 */
function isSpeechRecognitionSupported(): boolean {
  return 'SpeechRecognition' in window || 'webkitSpeechRecognition' in window;
}

/**
 * Get the SpeechRecognition constructor
 */
function getSpeechRecognition(): new () => SpeechRecognition {
  return window.SpeechRecognition || window.webkitSpeechRecognition;
}


/**
 * Get display name for a language code
 */
function getLanguageDisplayName(langCode: string): string {
  // Try exact match first
  if (LANGUAGE_NAMES[langCode]) {
    return LANGUAGE_NAMES[langCode];
  }
  // Try base language (e.g., 'en' from 'en-US')
  const baseLang = langCode.split('-')[0];
  if (LANGUAGE_NAMES[baseLang]) {
    return LANGUAGE_NAMES[baseLang];
  }
  // Fallback to the code itself
  return langCode;
}

/**
 * Get the saved language or default from browser
 */
function getSavedLanguage(): string {
  const saved = localStorage.getItem(STORAGE_KEY_LANG);
  if (saved) {
    return saved;
  }
  // Default to browser's first preferred language
  return navigator.languages?.[0] || navigator.language || 'en-US';
}

/**
 * Save selected language
 */
function saveLanguage(lang: string): void {
  localStorage.setItem(STORAGE_KEY_LANG, lang);
}

/**
 * Get list of available languages for voice input
 * Browser's preferred language is shown first if supported
 */
function getAvailableLanguages(): string[] {
  const supportedLanguages = ['en-US', 'cs-CZ'];
  const browserLang = normalizeLanguageCode(navigator.languages?.[0] || navigator.language || 'en-US');

  // Put browser's preferred language first if it's supported
  if (supportedLanguages.includes(browserLang)) {
    return [browserLang, ...supportedLanguages.filter(l => l !== browserLang)];
  }
  return supportedLanguages;
}

/**
 * Normalize a language code to its regional variant
 */
function normalizeLanguageCode(lang: string): string {
  if (lang.includes('-')) {
    return lang;
  }
  const variants: Record<string, string> = { 'en': 'en-US', 'cs': 'cs-CZ' };
  return variants[lang] || lang;
}

/**
 * Create and show the language selector popup
 */
function showLanguageSelector(voiceBtn: HTMLButtonElement): void {
  // Remove any existing selector
  hideLanguageSelector();

  const languages = getAvailableLanguages();

  // Create the popup
  const popup = document.createElement('div');
  popup.id = 'voice-lang-selector';
  popup.className = 'voice-lang-selector';

  // Create language options
  for (const lang of languages) {
    const option = document.createElement('button');
    option.className = 'voice-lang-option';
    option.type = 'button';
    if (lang === currentLang) {
      option.classList.add('selected');
    }
    option.textContent = getLanguageDisplayName(lang);
    option.dataset.lang = lang;

    // Click handler for desktop (and fallback for touch)
    option.addEventListener('click', (e) => {
      e.stopPropagation();
      selectLanguage(lang);
      hideLanguageSelector();
    });
    popup.appendChild(option);
  }

  // Touch devices: handle drag-to-select on the entire document
  // This allows the user to drag from the mic button into the popup
  if (isTouchDevice()) {
    const handleTouchMove = (e: TouchEvent) => {
      const touch = e.touches[0];
      const element = document.elementFromPoint(touch.clientX, touch.clientY);
      // Update visual highlight
      popup.querySelectorAll('.voice-lang-option').forEach(opt => {
        opt.classList.remove('hover');
      });
      if (element?.classList.contains('voice-lang-option')) {
        element.classList.add('hover');
      }
    };

    const handleTouchEnd = (e: TouchEvent) => {
      // Clean up listeners
      document.removeEventListener('touchmove', handleTouchMove);
      document.removeEventListener('touchend', handleTouchEnd);

      // Find which option the touch ended on
      const touch = e.changedTouches[0];
      const element = document.elementFromPoint(touch.clientX, touch.clientY);
      if (element?.classList.contains('voice-lang-option')) {
        e.preventDefault();
        const selectedLang = (element as HTMLElement).dataset.lang;
        if (selectedLang) {
          selectLanguage(selectedLang);
        }
        hideLanguageSelector();
      } else {
        // Touch ended outside options - just close
        hideLanguageSelector();
      }
    };

    document.addEventListener('touchmove', handleTouchMove, { passive: true });
    document.addEventListener('touchend', handleTouchEnd);
  }

  // Position the popup above the button, aligned to right edge
  const rect = voiceBtn.getBoundingClientRect();
  popup.style.bottom = `${window.innerHeight - rect.top + 8}px`;
  popup.style.right = `${window.innerWidth - rect.right}px`;

  document.body.appendChild(popup);
  langSelectorVisible = true;

  // Close on click outside
  setTimeout(() => {
    document.addEventListener('click', handleOutsideClick);
  }, 0);
}

/**
 * Hide the language selector popup
 */
function hideLanguageSelector(): void {
  const existing = document.getElementById('voice-lang-selector');
  if (existing) {
    existing.remove();
  }
  langSelectorVisible = false;
  document.removeEventListener('click', handleOutsideClick);
}

/**
 * Handle clicks outside the language selector
 */
function handleOutsideClick(e: MouseEvent): void {
  const selector = document.getElementById('voice-lang-selector');
  if (selector && !selector.contains(e.target as Node)) {
    hideLanguageSelector();
  }
}

/**
 * Select a language for speech recognition
 */
function selectLanguage(lang: string): void {
  currentLang = lang;
  saveLanguage(lang);
  if (recognition) {
    recognition.lang = lang;
  }
  // Update button title to show current language
  const voiceBtn = getElementById<HTMLButtonElement>('voice-btn');
  if (voiceBtn && !isRecording) {
    voiceBtn.title = `Voice input (${getLanguageDisplayName(lang)})`;
  }
}

// Aborts all button listeners from a previous init (F2): re-initializing
// used to stack duplicate listeners and leave a zombie SpeechRecognition
// whose handlers kept writing into the input
let initAbort: AbortController | null = null;

/**
 * Initialize voice input component (idempotent - safe to call on re-mount).
 */
export function initVoiceInput(): void {
  const voiceBtn = getElementById<HTMLButtonElement>('voice-btn');
  const input = getElementById<HTMLTextAreaElement>('message-input');

  if (!voiceBtn || !input) return;

  // Hide button if not supported
  if (!isSpeechRecognitionSupported()) {
    voiceBtn.classList.add('hidden');
    return;
  }

  // Drop listeners and recognition from any previous init (F2)
  initAbort?.abort();
  initAbort = new AbortController();
  recognition?.abort();

  // Initialize SpeechRecognition
  const SpeechRecognition = getSpeechRecognition();
  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;

  // Get saved language or default from browser
  currentLang = getSavedLanguage();
  recognition.lang = currentLang;
  voiceBtn.title = `Voice input (${getLanguageDisplayName(currentLang)})`;
  log.info('Voice input initialized', { language: currentLang });

  // Track the position where we started inserting text
  let insertPosition = 0;
  let finalTranscript = '';

  recognition.onstart = () => {
    isRecording = true;
    voiceBtn.classList.add('recording');
    voiceBtn.innerHTML = STOP_ICON;
    voiceBtn.setAttribute('aria-pressed', 'true');
    voiceBtn.title = 'Stop recording';
    // Remember where to insert text
    insertPosition = input.value.length;
    if (insertPosition > 0 && !input.value.endsWith(' ')) {
      input.value += ' ';
      insertPosition = input.value.length;
    }
    finalTranscript = '';
  };

  recognition.onresult = (event: SpeechRecognitionEvent) => {
    let interimTranscript = '';

    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      if (result.isFinal) {
        finalTranscript += result[0].transcript;
      } else {
        interimTranscript += result[0].transcript;
      }
    }

    // Update textarea with current transcript
    const beforeInsert = input.value.substring(0, insertPosition);
    input.value = beforeInsert + finalTranscript + interimTranscript;

    // Trigger input event for auto-resize and send button state
    autoResizeTextarea(input);
    updateSendButtonState();
  };

  recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
    log.error('Speech recognition error', { error: event.error, message: event.message });

    // Handle specific errors
    switch (event.error) {
      case 'not-allowed':
        toast.error('Microphone access denied. Please allow microphone access in your browser settings.');
        break;
      case 'network':
        toast.error('Speech recognition requires an internet connection. Please check your connection.');
        break;
      case 'service-not-allowed':
        toast.error('Speech recognition service is not available. This may require HTTPS.');
        break;
      case 'no-speech':
        // Silent timeout, just stop quietly
        break;
      case 'aborted':
        // User or system aborted, no message needed
        break;
      default:
        log.error('Unexpected speech recognition error', { error: event.error });
        toast.error('Speech recognition failed. Please try again.');
    }

    resetRecordingState(voiceBtn);
  };

  recognition.onend = () => {
    resetRecordingState(voiceBtn);
    // Focus the input after recording
    input.focus();
  };

  // Long-press handling for language selector
  let longPressTimer: ReturnType<typeof setTimeout> | null = null;
  let isLongPress = false;

  const startLongPress = (e: Event) => {
    if (isRecording) return;

    isLongPress = false;
    longPressTimer = setTimeout(() => {
      isLongPress = true;
      e.preventDefault();
      showLanguageSelector(voiceBtn);
    }, LONG_PRESS_DURATION);
  };

  const cancelLongPress = () => {
    if (longPressTimer) {
      clearTimeout(longPressTimer);
      longPressTimer = null;
    }
  };

  const handleClick = async () => {
    // If it was a long press, don't toggle recording
    if (isLongPress) {
      isLongPress = false;
      return;
    }

    // If language selector is visible, hide it
    if (langSelectorVisible) {
      hideLanguageSelector();
      return;
    }

    if (isRecording) {
      recognition?.stop();
    } else {
      // SpeechRecognition will automatically prompt for microphone permission when start() is called
      try {
        recognition?.start();
      } catch (error) {
        // Already started or other error
        log.error('Failed to start recognition', { error });
      }
    }
  };

  // All button listeners are tied to this init's AbortController so a
  // re-init cleans them up instead of stacking duplicates (F2)
  const { signal } = initAbort;

  // Mouse events for desktop
  voiceBtn.addEventListener('mousedown', startLongPress, { signal });
  voiceBtn.addEventListener('mouseup', cancelLongPress, { signal });
  voiceBtn.addEventListener('mouseleave', cancelLongPress, { signal });

  // Prevent context menu on long press (desktop)
  voiceBtn.addEventListener(
    'contextmenu',
    (e) => {
      e.preventDefault();
    },
    { signal }
  );

  // Touch events for mobile
  voiceBtn.addEventListener('touchstart', startLongPress, { passive: true, signal });
  voiceBtn.addEventListener('touchend', cancelLongPress, { signal });
  voiceBtn.addEventListener('touchcancel', cancelLongPress, { signal });

  // Click event for toggling recording
  voiceBtn.addEventListener('click', handleClick, { signal });
}

/**
 * Reset recording state and button appearance
 */
function resetRecordingState(voiceBtn: HTMLButtonElement): void {
  isRecording = false;
  voiceBtn.classList.remove('recording');
  voiceBtn.innerHTML = MICROPHONE_ICON;
  voiceBtn.setAttribute('aria-pressed', 'false');
  voiceBtn.title = `Voice input (${getLanguageDisplayName(currentLang)})`;
}

/**
 * Check if currently recording
 */
export function isVoiceRecording(): boolean {
  return isRecording;
}

/**
 * Stop recording if active
 * Uses abort() instead of stop() to discard any pending results,
 * preventing transcribed text from being re-added after input is cleared
 */
export function stopVoiceRecording(): void {
  if (isRecording && recognition) {
    recognition.abort();
  }
}
