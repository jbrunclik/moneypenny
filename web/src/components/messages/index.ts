/**
 * Messages component - displays and manages chat messages.
 *
 * This module is split into focused files:
 * - render.ts: Message rendering (HTML generation, markdown)
 * - streaming.ts: Streaming message state and updates
 * - attachments.ts: File attachments display (images, documents)
 * - actions.ts: Message action buttons (copy, delete, speak, cost, sources)
 * - loading.ts: Loading indicators
 * - pagination.ts: Older/newer messages loading via infinite scroll
 * - orientation.ts: Orientation change handling for scroll position
 * - utils.ts: Shared utilities (time formatting, ID updates)
 * - types.ts: TypeScript interfaces
 */

// Render
export { renderMessages, addMessageToUI, hasPendingApproval } from './render';

// Streaming
export {
  addStreamingMessage,
  updateStreamingMessage,
  finalizeStreamingMessage,
  restoreStreamingMessage,
  cleanupStreamingContext,
  hasActiveStreamingContext,
  getStreamingContextConversationId,
  getStreamingMessageElement,
  updateStreamingThinking,
  updateStreamingToolStart,
  updateStreamingToolDetail,
  updateStreamingToolEnd,
} from './streaming';

// Loading indicators
export {
  showLoadingIndicator,
  hideLoadingIndicator,
  showConversationLoader,
  hideConversationLoader,
} from './loading';

// Pagination
export {
  setupOlderMessagesScrollListener,
  cleanupOlderMessagesScrollListener,
  setupNewerMessagesScrollListener,
  cleanupNewerMessagesScrollListener,
  loadAllRemainingNewerMessages,
} from './pagination';

// Orientation
export { initOrientationChangeHandler } from './orientation';

// Utils
export { updateChatTitle, updateUserMessageId } from './utils';

// Types
export type { RenderMessagesOptions, StreamingMessageContext } from './types';
