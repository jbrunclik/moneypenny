/**
 * Message rendering - HTML generation for individual messages and message lists.
 */

import { resetTurnAnchor } from './turn-anchor';
import { createElement, escapeHtml, getElementById, scrollToBottom, clearElement } from '../../utils/dom';
import { renderMarkdown, highlightAllCodeBlocks } from '../../utils/markdown';
import { renderMermaidIn } from '../../utils/mermaid';
import { linkifyText } from '../../utils/linkify';
import { observeThumbnail, setDeferImageObservation } from './thumbnail-loader';
import { countVisibleImagesForScroll } from './image-load-scroll';
import { beginProgrammaticScroll, endProgrammaticScroll } from '../../utils/programmatic-scroll';
import { checkScrollButtonVisibility, clearNewMessagesPill } from '../ScrollToBottom';
import { createWelcomeMessage } from '../WelcomeMessage';
import { AI_AVATAR, CHAIN_ICON, CHECK_ICON, CLOCK_ICON, CLOSE_ICON, PLAY_ICON, WARNING_ICON, createIconElement, iconNodes, setIcon, type IconHtml } from '../../utils/icons';
import { agents } from '../../api/agents';
import { toast } from '../Toast';
import { renderConversationsList } from '../Sidebar';
import { createLogger } from '../../utils/logger';
import { createMessageActions } from './actions';
import { appendStoppedEarlyNote } from './stopped-early';
import { renderMessageFiles } from './attachments';
import { applySendState } from './send-state';
import { setInputBlockedForApproval } from '../MessageInput';
import { applyCompactionMarkers } from '../CompactionIndicator';
import type { RenderMessagesOptions } from './types';
import type { Message } from '../../types/api';
import { decorateArtifacts } from './artifacts';
import { decorateGrounding } from './grounding';
import { finishResearchMessage } from './research-progress';
import { addActionRowToUI } from './action-row';

const log = createLogger('messages');

// ============================================================================
// Trigger Message Detection
// ============================================================================

// Regex to detect agent trigger messages
const TRIGGER_MESSAGE_PATTERN = /^\[(Scheduled run|Manual trigger|Triggered by another agent) at \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC\]$/;

// Canonical marker for app-generated user-role messages (session starts,
// future automation events). Rendered as a system chip, never a bubble;
// the backend prompt documents the same convention for the model.
const SYSTEM_MESSAGE_PATTERN = /^\[System: ([a-z0-9-]+)\]$/;

// Display labels for known system actions; unknown actions fall back to
// the humanized action text
const SYSTEM_ACTION_LABELS: Record<string, string> = {
  'session-start': 'Session started',
};

// Regex to detect approval request messages (with approval ID)
// Pattern handles both Unix (\n) and Windows (\r\n) line endings
const APPROVAL_REQUEST_PATTERN = /^\[approval-request:([a-f0-9-]+)\]\r?\n/;

// Regex to detect approved action messages
const ACTION_APPROVED_PATTERN = /^\[Action approved: (.+)\]$/;

/**
 * Check if a message is an agent trigger message.
 */
function isTriggerMessage(content: string): boolean {
  const trimmed = content.trim();
  return TRIGGER_MESSAGE_PATTERN.test(trimmed) || SYSTEM_MESSAGE_PATTERN.test(trimmed);
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
    if (msg === undefined) continue;
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
  if (approvalId === undefined) return null;

  // Extract description from "I need your permission to: **description**"
  const descMatch = content.match(/I need your permission to: \*\*(.+?)\*\*/);
  const description = descMatch?.[1] ?? 'Unknown action';

  // Extract tool name from "Tool: `tool_name`"
  const toolMatch = content.match(/Tool: `(.+?)`/);
  const toolName = toolMatch?.[1] ?? 'Unknown tool';

  return { approvalId, description, toolName };
}

// parseActionApprovedMessage removed - no longer needed since we show status on the request message

/**
 * Parse trigger message into structured data for nice display.
 */
function parseTriggerMessage(content: string): { type: string; timestamp: string } | null {
  const match = content.trim().match(/^\[(Scheduled run|Manual trigger|Triggered by another agent) at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC\]$/);
  const [, type, timestamp] = match ?? [];
  if (type === undefined || timestamp === undefined) return null;
  return { type, timestamp };
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
      const token = beginProgrammaticScroll();
      scrollToBottom(container);
      requestAnimationFrame(() => {
        endProgrammaticScroll(token);
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
  for (const [i, msg] of messages.entries()) {
    if (msg.role === 'assistant' && isApprovalRequestMessage(msg.content)) {
      resolutions.set(msg.id, findApprovalResolution(messages, i + 1));
    }
  }

  return resolutions;
}

/** Look ahead from `start` for the user's approve/reject of an approval request. */
function findApprovalResolution(messages: Message[], start: number): { resolved: boolean; approved: boolean } {
  for (let j = start; j < messages.length; j++) {
    const laterMsg = messages[j];
    if (laterMsg === undefined) continue;
    if (laterMsg.role === 'user') {
      if (isActionApprovedMessage(laterMsg.content)) return { resolved: true, approved: true };
      if (isActionRejectedMessage(laterMsg.content)) return { resolved: true, approved: false };
    }
    // If we hit another assistant message (could be another approval or response), stop looking
    if (laterMsg.role === 'assistant') break;
  }
  return { resolved: false, approved: true };
}

/**
 * Render all messages in the container
 */
export function renderMessages(messages: Message[], options: RenderMessagesOptions = {}): void {
  log.debug('Rendering messages', { count: messages.length, skipScrollToBottom: options.skipScrollToBottom });
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) return;
  // A fresh render holds no reserved send-to-top space and no merged-in
  // "New messages" from the previous list
  resetTurnAnchor(container);
  clearNewMessagesPill();

  if (messages.length === 0) {
    container.replaceChildren(createWelcomeMessage());
    // A button shown for a previous (scrollable) conversation would
    // otherwise stay visible - no scroll event fires on content swap
    checkScrollButtonVisibility();
    return;
  }

  clearElement(container);

  // Defer observation until after we count visible images
  setDeferImageObservation(true);

  // Build map of approval resolutions before rendering
  const approvalResolutions = buildApprovalResolutionMap(messages);

  messages.forEach((msg) => addMessageToUI(msg, container, approvalResolutions));
  updateLatestAssistantMarker(container);

  // Lock quiz blocks in all messages except the last assistant message
  lockOlderQuizBlocks(container);

  // Re-place the compaction divider (cleared with the old messages)
  applyCompactionMarkers(container);

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
 * Mark the latest assistant message (must also be the conversation's last
 * message) so regenerate/continue reveal only where a re-run makes sense.
 * A CSS :last-child rule would be simpler, but WebKit doesn't re-evaluate
 * it reliably when siblings are appended dynamically.
 */
export function updateLatestAssistantMarker(
  container: HTMLElement | null = getElementById('messages')
): void {
  if (!container || container.id !== 'messages') return;
  container.querySelectorAll('.message--latest-assistant').forEach((el) => {
    el.classList.remove('message--latest-assistant');
  });
  const last = container.lastElementChild;
  if (last?.classList.contains('message') && last.classList.contains('assistant')) {
    last.classList.add('message--latest-assistant');
  }
}

/**
 * Remove the message with `messageId` and every message after it from the DOM,
 * leaving earlier turns untouched.
 *
 * Used by edit-and-resend: the tail is dropped so the edited text can be
 * re-sent. We do targeted DOM surgery rather than a full re-render from the
 * store, because the in-session store only holds user messages (streamed
 * assistant replies are rendered to the DOM but never appended to it) - so
 * re-rendering from it would wipe every assistant bubble until a reload.
 */
export function removeRenderedMessagesFrom(
  messageId: string,
  container: HTMLElement | null = getElementById('messages')
): void {
  if (!container) return;
  const target = container.querySelector<HTMLElement>(
    `.message[data-message-id="${messageId}"]`
  );
  if (!target) return;

  let sibling = target.nextElementSibling;
  while (sibling) {
    const next = sibling.nextElementSibling;
    sibling.remove();
    sibling = next;
  }
  target.remove();

  updateLatestAssistantMarker(container);
  checkScrollButtonVisibility();
}

/**
 * Add a single message to the UI
 * @param message - The message to add
 * @param container - The container element
 * @param approvalResolutions - Optional map of approval resolutions (for approval messages)
 */
export function addMessageToUI(
  message: Message,
  container: HTMLElement | null = getElementById('messages'),
  approvalResolutions?: Map<string, { resolved: boolean; approved: boolean }>,
  options?: { animate?: boolean }
): void {
  if (!container) {
    log.warn('Messages container not found, skipping message render');
    return;
  }
  if (renderSpecialMessage(message, container, approvalResolutions, options)) return;

  const messageEl = createMessageElement(message, options?.animate ?? false);

  // Content wrapper
  const contentWrapper = document.createElement('div');
  contentWrapper.className = 'message-content-wrapper';
  contentWrapper.appendChild(renderMessageContent(message));

  // Create message actions with all buttons and handlers
  if (message.role === 'assistant' && (message.stop_reason === 'user' || message.stopped_early)) {
    appendStoppedEarlyNote(contentWrapper, message.id, message.stop_reason === 'user' ? 'user' : 'round_cap');
  }

  const actions = createMessageActions(
    message.id,
    message.created_at,
    message.sources,
    message.generated_images,
    message.role,
    message.language
  );

  contentWrapper.appendChild(actions);

  if (message.role === 'user') {
    applySendState(messageEl, contentWrapper, message.id, message.status);
  }

  messageEl.appendChild(contentWrapper);
  if (message.role === 'assistant') {
    // Grounding-check underlines, source numbers and footer
    decorateGrounding(messageEl, message);
    // Sandboxed artifact frames under the text
    decorateArtifacts(messageEl, message);
    // Report chip and open research offer
    finishResearchMessage(messageEl, message);
  }
  container.appendChild(messageEl);
  updateLatestAssistantMarker(container);
}

/**
 * Messages that are not chat bubbles: agent triggers and app-sent actions
 * (rows), approval requests (cards), and approval outcomes (not rendered -
 * the request shows the status). Returns whether the message was one.
 */
function renderSpecialMessage(
  message: Message,
  container: HTMLElement,
  approvalResolutions: Map<string, { resolved: boolean; approved: boolean }> | undefined,
  options: { animate?: boolean } | undefined
): boolean {
  if (message.role === 'assistant') {
    // An approval request (assistant asking for permission)
    if (!isApprovalRequestMessage(message.content)) return false;
    const resolution = approvalResolutions?.get(message.id);
    addApprovalRequestMessageToUI(
      message,
      container,
      resolution?.resolved ?? false,
      resolution?.approved ?? true
    );
    return true;
  }
  if (message.role !== 'user') return false;
  // A trigger message (agent execution notification)
  if (isTriggerMessage(message.content)) {
    addTriggerMessageToUI(message, container);
    return true;
  }
  // Sent by the app for the user (Look it up, deep-research start): a row, not a bubble
  if (message.action) {
    addActionRowToUI(message, container, options);
    return true;
  }
  // Don't render the "Action approved/rejected" message as separate - status is shown on the approval request
  return isActionApprovedMessage(message.content) || isActionRejectedMessage(message.content);
}

/** The message bubble element, with the reply avatar and (live appends only) the entrance animation. */
function createMessageElement(message: Message, animate: boolean): HTMLDivElement {
  const messageEl = document.createElement('div');
  messageEl.className = `message ${message.role}`;
  messageEl.dataset.messageId = message.id;

  // Entrance animation only for live appends (never on history load).
  // Transform/opacity only - does not affect layout or scroll anchoring.
  if (animate) {
    messageEl.classList.add('message--entering');
    messageEl.addEventListener(
      'animationend',
      () => messageEl.classList.remove('message--entering'),
      { once: true },
    );
  }

  // Avatar: replies only - in a 1:1 chat the user's own right-aligned bubble
  // needs no marker (as in ChatGPT / Claude.ai)
  if (message.role === 'assistant') {
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    setIcon(avatar, AI_AVATAR);
    messageEl.appendChild(avatar);
  }
  return messageEl;
}

/** The bubble's content: text first, then files inside the bubble. */
function renderMessageContent(message: Message): HTMLDivElement {
  const content = document.createElement('div');
  content.className = 'message-content';
  // Truthiness, not !== undefined: the server sends files: null
  const hasFiles = !!message.files && message.files.length > 0;

  if (message.role === 'assistant') {
    content.innerHTML = renderMarkdown(message.content);
    highlightAllCodeBlocks(content);
    void renderMermaidIn(content);
    if (hasFiles && message.files) {
      content.appendChild(renderMessageFiles(message.files, message.id));
    }
    return content;
  }

  if (message.content) {
    // Escape HTML, replace newlines, then linkify URLs
    const escapedContent = escapeHtml(message.content).replace(/\n/g, '<br>');
    const linkedContent = linkifyText(escapedContent);
    content.innerHTML = `<p>${linkedContent}</p>`;
  }
  if (hasFiles && message.files) {
    // Unconfirmed sends (pending/failed) have no server-side blobs yet
    content.appendChild(renderMessageFiles(message.files, message.id, !!message.status));
  }
  return content;
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
  const triggerDisplayMap: Record<string, { icon: IconHtml; label: string; cssClass: string }> = {
    'Scheduled run': { icon: CLOCK_ICON, label: 'Scheduled', cssClass: 'trigger--scheduled' },
    'Manual trigger': { icon: PLAY_ICON, label: 'Manual', cssClass: 'trigger--manual' },
    'Triggered by another agent': { icon: CHAIN_ICON, label: 'Agent chain', cssClass: 'trigger--chain' },
  };

  // [System: <action>] markers render as a plain system chip
  const systemAction = message.content.trim().match(SYSTEM_MESSAGE_PATTERN)?.[1];
  const systemDisplay = systemAction !== undefined
    ? {
        icon: PLAY_ICON,
        label: SYSTEM_ACTION_LABELS[systemAction] ?? systemAction.replace(/-/g, ' '),
        cssClass: 'trigger--system',
      }
    : null;

  const display = systemDisplay
    ?? (parsed
      ? triggerDisplayMap[parsed.type] || { icon: PLAY_ICON, label: parsed.type, cssClass: '' }
      : { icon: PLAY_ICON, label: 'Execution', cssClass: '' });

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

  messageEl.append(
    createElement('div', { class: 'trigger-message-content' }, [
      createIconElement('trigger-icon', display.icon),
      createElement('span', { class: 'trigger-label' }, [display.label]),
      !!formattedTime && createElement('span', { class: 'trigger-time' }, [formattedTime]),
    ])
  );

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

/** The outcome shown on a handled approval request. */
function approvalResult(approved: boolean): HTMLElement {
  return createElement('div', { class: `approval-result ${approved ? 'approved' : 'rejected'}` }, [
    iconNodes(approved ? CHECK_ICON : CLOSE_ICON),
    createElement('span', {}, [approved ? 'Approved' : 'Rejected']),
  ]);
}

/** Approve/reject buttons of a pending approval request. */
function approvalButtons(approvalId: string): HTMLElement[] {
  return [
    createElement('button', { class: 'btn btn-approve', 'data-approval-id': approvalId }, [
      iconNodes(CHECK_ICON),
      createElement('span', {}, ['Approve']),
    ]),
    createElement('button', { class: 'btn btn-reject', 'data-approval-id': approvalId }, [
      iconNodes(CLOSE_ICON),
      createElement('span', {}, ['Reject']),
    ]),
  ];
}

/** Header icon and title of an approval request: pending, approved or rejected. */
function approvalHeader(isResolved: boolean, wasApproved: boolean): { icon: IconHtml; title: string } {
  if (!isResolved) return { icon: WARNING_ICON, title: 'Action requires approval' };
  return wasApproved
    ? { icon: CHECK_ICON, title: 'Action approved' }
    : { icon: CLOSE_ICON, title: 'Action rejected' };
}

/** The tool line of an approval request; '' for generic placeholder names. */
function approvalTool(toolName: string): HTMLElement | null {
  const generic = !toolName || toolName === 'custom_action' || toolName === 'unknown' || toolName === 'Unknown tool';
  return generic ? null : createElement('p', { class: 'approval-tool' }, ['Tool: ', createElement('code', {}, [toolName])]);
}

function wireApprovalButtons(messageEl: HTMLElement, approvalId: string): void {
  messageEl.querySelector('.btn-approve')?.addEventListener('click', () => {
    void handleApprovalAction(approvalId, true, messageEl);
  });
  messageEl.querySelector('.btn-reject')?.addEventListener('click', () => {
    void handleApprovalAction(approvalId, false, messageEl);
  });
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
  // Show buttons if pending, show result if resolved
  const actions = isResolved ? [approvalResult(wasApproved)] : approvalButtons(parsed?.approvalId || '');
  const header = approvalHeader(isResolved, wasApproved);

  messageEl.append(
    createElement('div', { class: 'approval-request-content' }, [
      createElement('div', { class: 'approval-request-header' }, [
        createIconElement('approval-icon', header.icon),
        createElement('span', { class: 'approval-title' }, [header.title]),
      ]),
      createElement('div', { class: 'approval-request-body' }, [
        createElement('p', { class: 'approval-description' }, [description]),
        approvalTool(parsed?.toolName || ''),
      ]),
      createElement('div', { class: 'approval-request-actions' }, actions),
    ])
  );

  // Only add event listeners if not resolved
  if (!isResolved && parsed?.approvalId) {
    wireApprovalButtons(messageEl, parsed.approvalId);
  }

  container.appendChild(messageEl);
}

/**
 * Handle approval action (approve or reject).
 */
async function handleApprovalAction(approvalId: string, approved: boolean, messageEl: HTMLElement): Promise<void> {
  // Import dynamically to avoid circular dependencies


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
      actionsDiv.replaceChildren(approvalResult(approved));
    }

    // Refresh the sidebar to update badges
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

// ============================================================================
// Quiz Block Locking
// ============================================================================

/**
 * Lock quiz blocks in all messages except the last assistant message.
 * Quizzes in older messages become non-interactive (opacity reduced, no pointer events).
 * Called after rendering all messages and after streaming finalization.
 */
export function lockOlderQuizBlocks(container?: HTMLElement): void {
  const el = container ?? getElementById<HTMLDivElement>('messages');
  if (!el) return;

  const allMessages = el.querySelectorAll('.message');
  if (allMessages.length === 0) return;

  // Find the last assistant message
  let lastAssistantMsg: Element | null = null;
  for (let i = allMessages.length - 1; i >= 0; i--) {
    const candidate = allMessages[i];
    if (candidate?.classList.contains('assistant')) {
      lastAssistantMsg = candidate;
      break;
    }
  }

  // Lock quiz blocks in all messages that aren't the last assistant message
  for (const msg of allMessages) {
    const quizBlocks = msg.querySelectorAll('.quiz-block');
    if (quizBlocks.length === 0) continue;

    const shouldLock = msg !== lastAssistantMsg;
    for (const block of quizBlocks) {
      block.classList.toggle('locked', shouldLock);
    }
  }
}
