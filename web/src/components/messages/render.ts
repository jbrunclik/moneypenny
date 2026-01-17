/**
 * Message rendering - HTML generation for individual messages and message lists.
 */

import { escapeHtml, getElementById, scrollToBottom, clearElement } from '../../utils/dom';
import { renderMarkdown, highlightAllCodeBlocks } from '../../utils/markdown';
import { linkifyText } from '../../utils/linkify';
import {
  observeThumbnail,
  markProgrammaticScrollStart,
  markProgrammaticScrollEnd,
  countVisibleImagesForScroll,
  setDeferImageObservation,
} from '../../utils/thumbnails';
import { createUserAvatarElement } from '../../utils/avatar';
import { checkScrollButtonVisibility } from '../ScrollToBottom';
import { AI_AVATAR, CHAIN_ICON, CHECK_ICON, CLOCK_ICON, CLOSE_ICON, PLAY_ICON, WARNING_ICON } from '../../utils/icons';
import { useStore } from '../../state/store';
import { createLogger } from '../../utils/logger';
import { createMessageActions } from './actions';
import { renderMessageFiles } from './attachments';
import { setInputBlockedForApproval } from '../MessageInput';
import type { RenderMessagesOptions } from './types';
import type { Message } from '../../types/api';

const log = createLogger('messages');

// ============================================================================
// Trigger Message Detection
// ============================================================================

// Regex to detect agent trigger messages
const TRIGGER_MESSAGE_PATTERN = /^\[(Scheduled run|Manual trigger|Triggered by another agent) at \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC\]$/;

// Regex to detect approval request messages (with approval ID)
// Pattern handles both Unix (\n) and Windows (\r\n) line endings
const APPROVAL_REQUEST_PATTERN = /^\[approval-request:([a-f0-9-]+)\]\r?\n/;

// Regex to detect approved action messages
const ACTION_APPROVED_PATTERN = /^\[Action approved: (.+)\]$/;

/**
 * Check if a message is an agent trigger message.
 */
function isTriggerMessage(content: string): boolean {
  return TRIGGER_MESSAGE_PATTERN.test(content.trim());
}

/**
 * Check if a message is an approval request message.
 */
function isApprovalRequestMessage(content: string): boolean {
  return APPROVAL_REQUEST_PATTERN.test(content.trim());
}

/**
 * Check if the last message in a list is a pending approval request.
 * Returns true if the last assistant message is an unresolved approval request.
 */
export function hasPendingApproval(messages: Message[]): boolean {
  // Find the last assistant message
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.role === 'assistant') {
      // Check if it's an approval request
      if (isApprovalRequestMessage(msg.content)) {
        return true;
      }
      // If the last assistant message is not an approval request, no pending approval
      return false;
    }
    // If we find a user message that's an action approved message, no pending approval
    if (msg.role === 'user' && isActionApprovedMessage(msg.content)) {
      return false;
    }
  }
  return false;
}

/**
 * Check if a message is an action approved message.
 */
function isActionApprovedMessage(content: string): boolean {
  return ACTION_APPROVED_PATTERN.test(content.trim());
}

/**
 * Parse approval request message into structured data.
 */
function parseApprovalRequestMessage(content: string): { approvalId: string; description: string; toolName: string } | null {
  const idMatch = content.match(APPROVAL_REQUEST_PATTERN);
  if (!idMatch) return null;

  const approvalId = idMatch[1];

  // Extract description from "I need your permission to: **description**"
  const descMatch = content.match(/I need your permission to: \*\*(.+?)\*\*/);
  const description = descMatch ? descMatch[1] : 'Unknown action';

  // Extract tool name from "Tool: `tool_name`"
  const toolMatch = content.match(/Tool: `(.+?)`/);
  const toolName = toolMatch ? toolMatch[1] : 'Unknown tool';

  return { approvalId, description, toolName };
}

// parseActionApprovedMessage removed - no longer needed since we show status on the request message

/**
 * Parse trigger message into structured data for nice display.
 */
function parseTriggerMessage(content: string): { type: string; timestamp: string } | null {
  const match = content.trim().match(/^\[(Scheduled run|Manual trigger|Triggered by another agent) at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC\]$/);
  if (!match) return null;
  return {
    type: match[1],
    timestamp: match[2],
  };
}

// ============================================================================
// Scroll and Image Observation Helpers
// ============================================================================

/**
 * Schedule programmatic scroll to bottom after layout settles.
 * Uses double RAF to ensure layout is accurate before scrolling.
 */
function scheduleScrollToBottom(container: HTMLElement): void {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      markProgrammaticScrollStart();
      scrollToBottom(container);
      requestAnimationFrame(() => {
        markProgrammaticScrollEnd();
      });
    });
  });
}

/**
 * Schedule image observation after layout settles.
 * Counts visible images first, then starts observing in the next tick.
 */
function scheduleImageObservation(container: HTMLElement): void {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      countVisibleImagesForScroll();

      // Observe in next tick to prevent IntersectionObserver from firing before count
      setTimeout(() => {
        setDeferImageObservation(false);
        const images = container.querySelectorAll<HTMLImageElement>(
          'img[data-message-id][data-file-index]:not([src])'
        );
        images.forEach((img) => observeThumbnail(img));
      }, 0);
    });
  });
}

/**
 * Final check for scroll button visibility after layout settles.
 */
function scheduleFinalScrollCheck(): void {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      countVisibleImagesForScroll();
      checkScrollButtonVisibility();
    });
  });
}

// ============================================================================
// Main Render Function
// ============================================================================

/**
 * Build a map of approval resolutions from the message list.
 * Scans user messages for "[Action approved: ...]" or "[Action rejected: ...]" patterns.
 * Returns a map from approval message ID to resolution status.
 */
function buildApprovalResolutionMap(messages: Message[]): Map<string, { resolved: boolean; approved: boolean }> {
  const resolutions = new Map<string, { resolved: boolean; approved: boolean }>();

  // Find all approval request messages and check if they're followed by a resolution
  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    if (msg.role === 'assistant' && isApprovalRequestMessage(msg.content)) {
      // Look ahead for resolution message
      let isResolved = false;
      let wasApproved = true;

      for (let j = i + 1; j < messages.length; j++) {
        const laterMsg = messages[j];
        if (laterMsg.role === 'user') {
          if (isActionApprovedMessage(laterMsg.content)) {
            isResolved = true;
            wasApproved = true;
            break;
          }
          if (isActionRejectedMessage(laterMsg.content)) {
            isResolved = true;
            wasApproved = false;
            break;
          }
        }
        // If we hit another assistant message (could be another approval or response), stop looking
        if (laterMsg.role === 'assistant') {
          break;
        }
      }

      resolutions.set(msg.id, { resolved: isResolved, approved: wasApproved });
    }
  }

  return resolutions;
}

/**
 * Render all messages in the container
 */
export function renderMessages(messages: Message[], options: RenderMessagesOptions = {}): void {
  log.debug('Rendering messages', { count: messages.length, skipScrollToBottom: options.skipScrollToBottom });
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) return;

  if (messages.length === 0) {
    container.innerHTML = `
      <div class="welcome-message">
        <h2>Welcome to AI Chatbot</h2>
        <p>Start a conversation with Gemini AI</p>
      </div>
    `;
    return;
  }

  clearElement(container);

  // Defer observation until after we count visible images
  setDeferImageObservation(true);

  // Build map of approval resolutions before rendering
  const approvalResolutions = buildApprovalResolutionMap(messages);

  messages.forEach((msg) => addMessageToUI(msg, container, approvalResolutions));

  if (!options.skipScrollToBottom) {
    scheduleScrollToBottom(container);
  }

  scheduleImageObservation(container);
  scheduleFinalScrollCheck();

  // Check if there's a pending approval and block input accordingly
  // Use server's value if provided, otherwise fall back to message content check
  const pendingApproval = options.hasPendingApproval ?? hasPendingApproval(messages);
  setInputBlockedForApproval(pendingApproval);
}

/**
 * Add a single message to the UI
 * @param message - The message to add
 * @param container - The container element
 * @param approvalResolutions - Optional map of approval resolutions (for approval messages)
 */
export function addMessageToUI(
  message: Message,
  container: HTMLElement = getElementById('messages')!,
  approvalResolutions?: Map<string, { resolved: boolean; approved: boolean }>
): void {
  // Check if this is a trigger message (agent execution notification)
  if (message.role === 'user' && isTriggerMessage(message.content)) {
    addTriggerMessageToUI(message, container);
    return;
  }

  // Check if this is an approval request message (assistant asking for permission)
  if (message.role === 'assistant' && isApprovalRequestMessage(message.content)) {
    const resolution = approvalResolutions?.get(message.id);
    addApprovalRequestMessageToUI(
      message,
      container,
      resolution?.resolved ?? false,
      resolution?.approved ?? true
    );
    return;
  }

  // Check if this is an action approved/rejected message - skip rendering since status is shown on the request
  if (message.role === 'user' && (isActionApprovedMessage(message.content) || isActionRejectedMessage(message.content))) {
    // Don't render the "Action approved/rejected" message as separate - status is shown on the approval request
    return;
  }

  const messageEl = document.createElement('div');
  messageEl.className = `message ${message.role}`;
  messageEl.dataset.messageId = message.id;

  // Avatar
  const avatar = document.createElement('div');
  avatar.className = 'message-avatar';
  if (message.role === 'assistant') {
    avatar.innerHTML = AI_AVATAR;
  } else {
    // User avatar - show picture or initials
    const user = useStore.getState().user;
    const name = user?.name || user?.email || 'User';
    const avatarContent = createUserAvatarElement(user?.picture || undefined, name, '');
    // For message avatars, we add content to the existing div instead of replacing it
    if (avatarContent instanceof HTMLImageElement) {
      avatar.appendChild(avatarContent);
    } else {
      avatar.textContent = avatarContent.textContent;
    }
  }
  messageEl.appendChild(avatar);

  // Content wrapper
  const contentWrapper = document.createElement('div');
  contentWrapper.className = 'message-content-wrapper';

  // Render text content
  const content = document.createElement('div');
  content.className = 'message-content';

  if (message.role === 'assistant') {
    // Assistant: text first, then files inside the bubble (same as user)
    content.innerHTML = renderMarkdown(message.content);
    highlightAllCodeBlocks(content);
    if (message.files && message.files.length > 0) {
      const filesContainer = renderMessageFiles(message.files, message.id);
      content.appendChild(filesContainer);
    }
    contentWrapper.appendChild(content);
  } else {
    // User: text first, then files inside the bubble
    if (message.content) {
      // Escape HTML, replace newlines, then linkify URLs
      const escapedContent = escapeHtml(message.content).replace(/\n/g, '<br>');
      const linkedContent = linkifyText(escapedContent);
      content.innerHTML = `<p>${linkedContent}</p>`;
    }
    if (message.files && message.files.length > 0) {
      const filesContainer = renderMessageFiles(message.files, message.id);
      content.appendChild(filesContainer);
    }
    contentWrapper.appendChild(content);
  }

  // Create message actions with all buttons and handlers
  const actions = createMessageActions(
    message.id,
    message.created_at,
    message.sources,
    message.generated_images,
    message.role,
    message.language
  );

  contentWrapper.appendChild(actions);

  messageEl.appendChild(contentWrapper);
  container.appendChild(messageEl);
}

/**
 * Add a trigger message (agent execution notification) to the UI.
 * These are displayed as centered system notifications, not as chat bubbles.
 */
function addTriggerMessageToUI(message: Message, container: HTMLElement): void {
  const parsed = parseTriggerMessage(message.content);

  const messageEl = document.createElement('div');
  messageEl.dataset.messageId = message.id;

  // Map trigger types to display text, icons, and CSS classes
  const triggerDisplayMap: Record<string, { icon: string; label: string; cssClass: string }> = {
    'Scheduled run': { icon: CLOCK_ICON, label: 'Scheduled', cssClass: 'trigger--scheduled' },
    'Manual trigger': { icon: PLAY_ICON, label: 'Manual', cssClass: 'trigger--manual' },
    'Triggered by another agent': { icon: CHAIN_ICON, label: 'Agent chain', cssClass: 'trigger--chain' },
  };

  const display = parsed
    ? triggerDisplayMap[parsed.type] || { icon: PLAY_ICON, label: parsed.type, cssClass: '' }
    : { icon: PLAY_ICON, label: 'Execution', cssClass: '' };

  messageEl.className = `message trigger-message ${display.cssClass}`;

  // Format timestamp for display (e.g., "Jan 15, 2026 at 9:00 AM")
  let formattedTime = '';
  if (parsed?.timestamp) {
    try {
      const date = new Date(parsed.timestamp.replace(' ', 'T') + ':00Z');
      formattedTime = date.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      });
    } catch {
      formattedTime = parsed.timestamp + ' UTC';
    }
  }

  messageEl.innerHTML = `
    <div class="trigger-message-content">
      <span class="trigger-icon">${display.icon}</span>
      <span class="trigger-label">${escapeHtml(display.label)}</span>
      ${formattedTime ? `<span class="trigger-time">${escapeHtml(formattedTime)}</span>` : ''}
    </div>
  `;

  container.appendChild(messageEl);
}

// Regex to detect rejected action messages
const ACTION_REJECTED_PATTERN = /^\[Action rejected: (.+)\]$/;

/**
 * Check if a message is an action rejected message.
 */
function isActionRejectedMessage(content: string): boolean {
  return ACTION_REJECTED_PATTERN.test(content.trim());
}

/**
 * Add an approval request message to the UI.
 * These show the action requiring approval with approve/reject buttons.
 * If the approval has already been handled (approved or rejected), show status instead of buttons.
 *
 * @param message - The message containing the approval request
 * @param container - The container to append to
 * @param isResolved - Whether this approval has been resolved (check via subsequent messages)
 * @param wasApproved - If resolved, whether it was approved (true) or rejected (false)
 */
function addApprovalRequestMessageToUI(
  message: Message,
  container: HTMLElement,
  isResolved: boolean = false,
  wasApproved: boolean = true
): void {
  const parsed = parseApprovalRequestMessage(message.content);

  const messageEl = document.createElement('div');
  messageEl.className = 'message approval-request-message';
  messageEl.dataset.messageId = message.id;
  if (parsed) {
    messageEl.dataset.approvalId = parsed.approvalId;
  }

  const description = parsed?.description || 'Unknown action';
  const toolName = parsed?.toolName || '';

  // Only show tool name if it's a meaningful value (not generic placeholders)
  const showTool = toolName && toolName !== 'custom_action' && toolName !== 'unknown' && toolName !== 'Unknown tool';
  const toolHtml = showTool
    ? `<p class="approval-tool">Tool: <code>${escapeHtml(toolName)}</code></p>`
    : '';

  // Show buttons if pending, show result if resolved
  let actionsHtml: string;
  if (isResolved) {
    // Show the result status
    actionsHtml = `
      <div class="approval-result ${wasApproved ? 'approved' : 'rejected'}">
        ${wasApproved ? CHECK_ICON : CLOSE_ICON}
        <span>${wasApproved ? 'Approved' : 'Rejected'}</span>
      </div>
    `;
  } else {
    // Show approve/reject buttons
    actionsHtml = `
      <button class="btn btn-approve" data-approval-id="${parsed?.approvalId || ''}">
        ${CHECK_ICON}
        <span>Approve</span>
      </button>
      <button class="btn btn-reject" data-approval-id="${parsed?.approvalId || ''}">
        ${CLOSE_ICON}
        <span>Reject</span>
      </button>
    `;
  }

  messageEl.innerHTML = `
    <div class="approval-request-content">
      <div class="approval-request-header">
        <span class="approval-icon">${isResolved ? (wasApproved ? CHECK_ICON : CLOSE_ICON) : WARNING_ICON}</span>
        <span class="approval-title">${isResolved ? (wasApproved ? 'Action approved' : 'Action rejected') : 'Action requires approval'}</span>
      </div>
      <div class="approval-request-body">
        <p class="approval-description">${escapeHtml(description)}</p>
        ${toolHtml}
      </div>
      <div class="approval-request-actions">
        ${actionsHtml}
      </div>
    </div>
  `;

  // Only add event listeners if not resolved
  if (!isResolved && parsed?.approvalId) {
    const approveBtn = messageEl.querySelector('.btn-approve');
    const rejectBtn = messageEl.querySelector('.btn-reject');

    if (approveBtn) {
      approveBtn.addEventListener('click', () => handleApprovalAction(parsed.approvalId, true, messageEl));
    }

    if (rejectBtn) {
      rejectBtn.addEventListener('click', () => handleApprovalAction(parsed.approvalId, false, messageEl));
    }
  }

  container.appendChild(messageEl);
}

/**
 * Handle approval action (approve or reject).
 */
async function handleApprovalAction(approvalId: string, approved: boolean, messageEl: HTMLElement): Promise<void> {
  // Import dynamically to avoid circular dependencies
  const { agents } = await import('../../api/client');
  const { toast } = await import('../Toast');

  // Disable buttons to prevent double-click
  const buttons = messageEl.querySelectorAll<HTMLButtonElement>('.approval-request-actions button');
  buttons.forEach(btn => {
    btn.disabled = true;
  });

  try {
    if (approved) {
      await agents.approveRequest(approvalId);
      toast.success('Action approved. Agent will continue.');
    } else {
      await agents.rejectRequest(approvalId);
      toast.info('Action rejected.');
    }

    // Update the UI to show the result
    const actionsDiv = messageEl.querySelector('.approval-request-actions');
    if (actionsDiv) {
      actionsDiv.innerHTML = `
        <div class="approval-result ${approved ? 'approved' : 'rejected'}">
          ${approved ? CHECK_ICON : CLOSE_ICON}
          <span>${approved ? 'Approved' : 'Rejected'}</span>
        </div>
      `;
    }

    // Refresh the sidebar to update badges
    const { renderConversationsList } = await import('../Sidebar');
    renderConversationsList();

    // Unblock the message input since approval has been handled
    setInputBlockedForApproval(false);

  } catch (error) {
    // Re-enable buttons on error
    buttons.forEach(btn => {
      btn.disabled = false;
    });
    toast.error('Failed to process approval.');
    log.error('Approval action failed', { approvalId, approved, error });
  }
}

// Note: addActionApprovedMessageToUI removed - approval status is now shown
// directly on the approval request message instead of as a separate message
