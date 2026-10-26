/**
 * Window events that message actions dispatch (delete, read aloud).
 */
import { createLogger } from '../../utils/logger';
import { deleteMessage } from '../conversation-actions';
import { speakMessageInternal as speakMessage } from '../tts';

const log = createLogger('init');

/**
 * Listen for message:delete and message:speak.
 */
export function initMessageEvents(): void {
  // Listen for message delete events
  window.addEventListener('message:delete', (event: Event) => {
    const customEvent = event as CustomEvent<{ messageId: string }>;
    const { messageId } = customEvent.detail;
    log.debug('Message delete event received', { messageId });
    void deleteMessage(messageId);
  });

  // Listen for message speak events (TTS)
  window.addEventListener('message:speak', (event: Event) => {
    const customEvent = event as CustomEvent<{ messageId: string; language?: string }>;
    const { messageId, language } = customEvent.detail;
    log.debug('Message speak event received', { messageId, language });
    speakMessage(messageId, language);
  });
}
