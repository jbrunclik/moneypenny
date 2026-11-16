/**
 * The composer: message input (send / stop), the outbox, model selector,
 * attachments and voice input.
 */
import { initFileUpload } from '../../components/FileUpload';
import { initMessageInput, renderFilePreview, updateSendButtonState } from '../../components/MessageInput';
import { initModelSelector } from '../../components/ModelSelector';
import { initVoiceInput } from '../../components/VoiceInput';
import { createLogger } from '../../utils/logger';
import { handleStopStreaming } from '../active-requests';
import { sendMessage } from '../messaging';
import { initOutboxHandlers } from '../rerun';
import { initOutboxResend } from '../outbox-resend';

const log = createLogger('init');

/**
 * Wire up the composer.
 */
export function initComposer(): void {
  initMessageInput(() => {
    void sendMessage().catch((error: unknown) => log.error('Failed to send message', { error }));
  }, handleStopStreaming);
  initOutboxHandlers();
  initOutboxResend();
  initModelSelector();
  initFileUpload(() => {
    renderFilePreview();
    updateSendButtonState();
  });
  initVoiceInput();
}
