/**
 * Scrolling the message list: scroll-to-bottom, the turn anchor, the
 * auto-hiding header and restoring the position on rotation.
 */
import { initScrollToBottom, setBeforeScrollToBottomCallback } from '../../components/ScrollToBottom';
import {
  initOrientationChangeHandler,
  cleanupNewerMessagesScrollListener,
  loadAllRemainingNewerMessages,
} from '../../components/messages';
import { initTurnAnchorResizeHold } from '../../components/messages/turn-anchor';
import { useStore } from '../../state/store';
import { createLogger } from '../../utils/logger';
import { initHeaderAutoHide } from '../header-autohide';

const log = createLogger('init');

/**
 * In a partial view (after search navigation) scroll-to-bottom first loads
 * the missing newer messages, so the user sees the actual latest ones.
 */
async function loadRemainingNewerMessages(): Promise<void> {
  const store = useStore.getState();
  const { currentConversation } = store;
  if (!currentConversation) return;

  const pagination = store.getMessagesPagination(currentConversation.id);
  if (pagination?.hasNewer) {
    log.debug('Loading remaining newer messages before scroll-to-bottom', {
      conversationId: currentConversation.id,
    });
    await loadAllRemainingNewerMessages(currentConversation.id);
    cleanupNewerMessagesScrollListener();
  }
}

/**
 * Wire up message-list scrolling.
 */
export function initMessageScrolling(): void {
  initScrollToBottom();
  const messagesList = document.getElementById('messages');
  if (messagesList) initTurnAnchorResizeHold(messagesList);
  initHeaderAutoHide();
  setBeforeScrollToBottomCallback(loadRemainingNewerMessages);
  initOrientationChangeHandler();
}
