/**
 * Message rendering - HTML generation for individual messages and message lists.
 */

import { renderDeliveryLabel } from './delivery-label';
import { renderMemoryNote } from './memory-note';
import { asReleaseCard } from './release-card';
import { useStore } from '../../state/store';
import { resetTurnAnchor } from './turn-anchor';
import { createElement, getElementById, scrollToBottom, clearElement, setSanitizedHtml } from '../../utils/dom';
import { renderMarkdown, highlightAllCodeBlocks } from '../../utils/markdown';
import { renderMermaidIn } from '../../utils/mermaid';
import { linkify } from '../../utils/linkify';
import { observeThumbnail, setDeferImageObservation } from './thumbnail-loader';
import { countVisibleImagesForScroll } from './image-load-scroll';
import { beginProgrammaticScroll, endProgrammaticScroll } from '../../utils/programmatic-scroll';
import { checkScrollButtonVisibility, clearNewMessagesPill } from '../ScrollToBottom';
import { createWelcomeMessage } from '../WelcomeMessage';
import { AI_AVATAR, CHAIN_ICON, CLOCK_ICON, PLAY_ICON, createIconElement, setIcon, type IconHtml } from '../../utils/icons';
import { createLogger } from '../../utils/logger';
import { createMessageActions } from './actions';
import { appendStoppedEarlyNote } from './stopped-early';
import { renderMessageFiles } from './attachments';
import { applySendState } from './send-state';
import { applyCompactionMarkers } from '../CompactionIndicator';
import type { RenderMessagesOptions } from './types';
import type { Message } from '../../types/api';
import { decorateArtifacts } from './artifacts';
import { decorateGrounding } from './grounding';
import { finishResearchMessage } from './research-progress';
import { decorateProposals } from './proposal-card';
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

// The marker an old run's waiting message opened with (before run cards,
// Nov 2026): stripped, the message renders as plain text
const OLD_APPROVAL_MARKER = /^\[approval-request:[a-f0-9-]+\]\r?\n/;

// The notes a run card's answer adds for the resumed run (run_approvals.py):
// not shown - the card shows the outcome
const ACTION_APPROVED_PATTERN = /^\[Action approved: .+\]/;

/**
 * Check if a message is an agent trigger message.
 */
function isTriggerMessage(content: string): boolean {
  const trimmed = content.trim();
  return TRIGGER_MESSAGE_PATTERN.test(trimmed) || SYSTEM_MESSAGE_PATTERN.test(trimmed);
}

/**
 * Check if a message is an action approved message.
 */
function isActionApprovedMessage(content: string): boolean {
  return ACTION_APPROVED_PATTERN.test(content.trim());
}

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

// UI-local (F2): bumped by every full render. A page load captures it and
// drops its response when the list was re-rendered meanwhile: the page belongs
// to the previous window (search jump, conversation reload) and would
// duplicate messages already in the new one.
let renderGeneration = 0;

/** The current full-render generation, for discarding stale page loads. */
export function getRenderGeneration(): number {
  return renderGeneration;
}

/**
 * Render all messages in the container
 */
export function renderMessages(messages: Message[], options: RenderMessagesOptions = {}): void {
  log.debug('Rendering messages', { count: messages.length, skipScrollToBottom: options.skipScrollToBottom });
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) return;
  renderGeneration++;
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

  messages.forEach((msg) => addMessageToUI(msg, container));
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
 */
export function addMessageToUI(
  message: Message,
  container: HTMLElement | null = getElementById('messages'),
  options?: { animate?: boolean }
): void {
  if (!container) {
    log.warn('Messages container not found, skipping message render');
    return;
  }
  if (renderSpecialMessage(message, container, options)) return;

  const messageEl = createMessageElement(message, options?.animate ?? false);

  const contentWrapper = renderContentWrapper(message);

  // Create message actions with all buttons and handlers
  if (message.role === 'assistant' && (message.stop_reason === 'user' || message.stopped_early)) {
    appendStoppedEarlyNote(contentWrapper, message.id, message.stop_reason === 'user' ? 'user' : 'budget');
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
    // Proposal cards: what the reply asks the user's yes for
    decorateProposals(messageEl, message);
  }
  container.appendChild(messageEl);
  updateLatestAssistantMarker(container);
}

/**
 * Messages that are not chat bubbles: agent triggers and app-sent actions
 * (rows), and a run card's answer notes (not rendered - the card shows the
 * outcome). Returns whether the message was one.
 */
function renderSpecialMessage(
  message: Message,
  container: HTMLElement,
  options: { animate?: boolean } | undefined
): boolean {
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
  // A run card's answer note for the resumed run: the card shows the outcome
  return isActionApprovedMessage(message.content) || isActionRejectedMessage(message.content);
}

/** A post in the read-only What's new chat (rendered as a release card). */
function isReleasePost(message: Message): boolean {
  return message.role === 'assistant' && !!useStore.getState().currentConversation?.is_whats_new;
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

  // What's new posts are release cards: no avatar, the card carries the mark
  if (isReleasePost(message)) {
    messageEl.classList.add('message--release');
    return messageEl;
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
/** The message's content with the labels around a reply. */
function renderContentWrapper(message: Message): HTMLDivElement {
  const contentWrapper = document.createElement('div');
  contentWrapper.className = 'message-content-wrapper';
  // A turn a scheduled item delivered (check-in, watcher, recurring) says so
  if (message.role === 'assistant' && message.delivery) {
    contentWrapper.appendChild(renderDeliveryLabel(message.delivery));
  }
  contentWrapper.appendChild(renderMessageContent(message));
  // What the background memory review saved after this reply
  if (message.role === 'assistant' && message.memory_note) {
    contentWrapper.appendChild(renderMemoryNote(message.memory_note));
  }
  return contentWrapper;
}

function renderMessageContent(message: Message): HTMLDivElement {
  const content = document.createElement('div');
  content.className = 'message-content';
  // Truthiness, not !== undefined: the server sends files: null
  const hasFiles = !!message.files && message.files.length > 0;

  if (message.role === 'assistant') {
    setSanitizedHtml(content, renderMarkdown(message.content.replace(OLD_APPROVAL_MARKER, '')));
    if (isReleasePost(message)) asReleaseCard(content, message.created_at, message.language);
    highlightAllCodeBlocks(content);
    void renderMermaidIn(content);
    if (hasFiles && message.files) {
      content.appendChild(renderMessageFiles(message.files, message.id));
    }
    return content;
  }

  if (message.content) {
    // Plain text: a line break per newline, URLs as links
    const paragraph = document.createElement('p');
    message.content.split('\n').forEach((line, i) => {
      if (i > 0) paragraph.append(document.createElement('br'));
      paragraph.append(linkify(line));
    });
    content.append(paragraph);
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
const ACTION_REJECTED_PATTERN = /^\[Action rejected: .+\]/;

/**
 * Check if a message is an action rejected message.
 */
function isActionRejectedMessage(content: string): boolean {
  return ACTION_REJECTED_PATTERN.test(content.trim());
}


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
