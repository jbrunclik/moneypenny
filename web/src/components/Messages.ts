import { escapeHtml, getElementById, scrollToBottom, isScrolledToBottom } from '../utils/dom';
import { renderMarkdown, highlightAllCodeBlocks, highlightCode } from '../utils/markdown';
import { observeThumbnail } from '../utils/thumbnails';
import { createUserAvatarElement } from '../utils/avatar';
import { AI_AVATAR_SVG, getFileIcon, DOWNLOAD_ICON, COPY_ICON, TOOL_ICON, SPINNER_ICON, CHEVRON_RIGHT_ICON, CHECK_ICON, THINKING_ICON } from '../utils/icons';
import { useStore } from '../state/store';
import { messages as messagesApi } from '../api/client';
import type { Message, FileMetadata, DetailEvent } from '../types/api';

/**
 * Format a timestamp for display using system locale
 * Shows time for today, "Yesterday HH:MM" for yesterday, or locale date + time for older
 */
function formatMessageTime(isoString: string): string {
  const date = new Date(isoString);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 24 * 60 * 60 * 1000);
  const messageDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());

  const timeStr = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });

  if (messageDay.getTime() === today.getTime()) {
    return timeStr;
  } else if (messageDay.getTime() === yesterday.getTime()) {
    // Use Intl.RelativeTimeFormat for localized "yesterday"
    const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
    const yesterdayStr = rtf.formatToParts(-1, 'day').find(p => p.type === 'literal')?.value || 'Yesterday';
    return `${yesterdayStr} ${timeStr}`;
  } else {
    // Full locale-aware date formatting
    return date.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }
}

/**
 * Render all messages in the container
 */
export function renderMessages(messages: Message[]): void {
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

  container.innerHTML = '';
  messages.forEach((msg) => {
    addMessageToUI(msg, container);
  });

  scrollToBottom(container);
}

/**
 * Add a single message to the UI
 */
export function addMessageToUI(
  message: Message,
  container: HTMLElement = getElementById('messages')!
): void {
  const messageEl = document.createElement('div');
  messageEl.className = `message ${message.role}`;
  messageEl.dataset.messageId = message.id;

  // Avatar
  const avatar = document.createElement('div');
  avatar.className = 'message-avatar';
  if (message.role === 'assistant') {
    avatar.innerHTML = AI_AVATAR_SVG;
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
    // Assistant: files, then text content with inline details toggle
    const hasDetails = message.hasDetails || (message.details && message.details.length > 0);

    if (message.files && message.files.length > 0) {
      const filesContainer = renderMessageFiles(message.files, message.id);
      contentWrapper.appendChild(filesContainer);
    }

    // Add details toggle inside message content if hasDetails
    if (hasDetails) {
      const detailsToggle = createInlineDetailsToggle(message.id);
      content.appendChild(detailsToggle);

      // Add details section (collapsed by default)
      const detailsSection = createDetailsSection(message.id, !!message.hasDetails, message.details);
      content.appendChild(detailsSection);
    }

    // Add the markdown content
    const textContent = document.createElement('div');
    textContent.className = 'message-text';
    textContent.innerHTML = renderMarkdown(message.content);
    highlightAllCodeBlocks(textContent);
    content.appendChild(textContent);

    contentWrapper.appendChild(content);
  } else {
    // User: text first, then files inside the bubble
    if (message.content) {
      content.innerHTML = `<p>${escapeHtml(message.content).replace(/\n/g, '<br>')}</p>`;
    }
    if (message.files && message.files.length > 0) {
      const filesContainer = renderMessageFiles(message.files, message.id);
      content.appendChild(filesContainer);
    }
    contentWrapper.appendChild(content);
  }

  // Add message actions (timestamp + copy button)
  const actions = document.createElement('div');
  actions.className = 'message-actions';
  const timeStr = message.created_at ? formatMessageTime(message.created_at) : '';
  actions.innerHTML = `
    ${timeStr ? `<span class="message-time">${timeStr}</span>` : ''}
    <button class="message-copy-btn" title="Copy message">
      ${COPY_ICON}
    </button>
  `;
  contentWrapper.appendChild(actions);

  messageEl.appendChild(contentWrapper);
  container.appendChild(messageEl);
}

/**
 * Render files attached to a message
 */
function renderMessageFiles(files: FileMetadata[], messageId: string): HTMLElement {
  const container = document.createElement('div');
  container.className = 'message-files';

  // Separate images from other files
  const images = files.filter((f) => f.type.startsWith('image/'));
  const documents = files.filter((f) => !f.type.startsWith('image/'));

  // Render images in horizontal gallery
  if (images.length > 0) {
    const gallery = document.createElement('div');
    gallery.className = 'message-images';

    images.forEach((file) => {
      const fileIndex = files.indexOf(file);
      const imgWrapper = document.createElement('div');
      imgWrapper.className = 'message-image-wrapper';

      const img = document.createElement('img');
      img.className = 'message-image';
      img.alt = file.name;
      img.dataset.messageId = file.messageId || messageId;
      img.dataset.fileIndex = String(file.fileIndex ?? fileIndex);

      // If we have a local preview URL (just-uploaded file), use it directly
      // Otherwise, use lazy loading to fetch thumbnail from server
      if (file.previewUrl) {
        img.src = file.previewUrl;
      } else {
        // Add loading state for server-fetched images
        imgWrapper.classList.add('loading');

        // Add placeholder with filename
        const placeholder = document.createElement('span');
        placeholder.className = 'image-placeholder';
        placeholder.textContent = file.name;
        imgWrapper.appendChild(placeholder);

        img.loading = 'lazy';

        // Set up lazy loading - remove loading class from wrapper when loaded
        img.addEventListener('load', () => {
          imgWrapper.classList.remove('loading');
        });
        observeThumbnail(img);
      }

      // Click to open lightbox
      img.addEventListener('click', () => {
        window.dispatchEvent(
          new CustomEvent('lightbox:open', {
            detail: {
              messageId: img.dataset.messageId,
              fileIndex: img.dataset.fileIndex,
            },
          })
        );
      });

      imgWrapper.appendChild(img);
      gallery.appendChild(imgWrapper);
    });

    container.appendChild(gallery);
  }

  // Render documents as list
  if (documents.length > 0) {
    const list = document.createElement('div');
    list.className = 'message-documents';

    documents.forEach((file) => {
      const fileIndex = files.indexOf(file);
      const doc = document.createElement('div');
      doc.className = 'message-document';
      doc.innerHTML = `
        <span class="document-icon">${getFileIcon(file.type)}</span>
        <span class="document-name">${escapeHtml(file.name)}</span>
        <button class="document-download"
                data-message-id="${file.messageId || messageId}"
                data-file-index="${file.fileIndex ?? fileIndex}"
                title="Download">
          ${DOWNLOAD_ICON}
        </button>
      `;
      list.appendChild(doc);
    });

    container.appendChild(list);
  }

  return container;
}

/**
 * Add a streaming message placeholder
 */
export function addStreamingMessage(): HTMLElement {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) throw new Error('Messages container not found');

  const messageEl = document.createElement('div');
  messageEl.className = 'message assistant streaming';
  messageEl.innerHTML = `
    <div class="message-avatar">${AI_AVATAR_SVG}</div>
    <div class="message-content-wrapper">
      <div class="message-content">
        <div class="message-text"><span class="streaming-cursor"></span></div>
      </div>
    </div>
  `;

  container.appendChild(messageEl);
  scrollToBottom(container);

  return messageEl;
}

/**
 * Update streaming message content
 */
export function updateStreamingMessage(
  messageEl: HTMLElement,
  content: string
): void {
  const contentEl = messageEl.querySelector('.message-content');
  if (!contentEl) return;

  const wasAtBottom = isScrolledToBottom(
    getElementById('messages')!
  );

  // Find or create the text container (preserve details toggle and section)
  let textContainer = contentEl.querySelector('.message-text') as HTMLElement;
  if (!textContainer) {
    textContainer = document.createElement('div');
    textContainer.className = 'message-text';
    contentEl.appendChild(textContainer);
  }

  // Render markdown for the accumulated content
  textContainer.innerHTML = renderMarkdown(content) + '<span class="streaming-cursor"></span>';

  if (wasAtBottom) {
    scrollToBottom(getElementById('messages')!);
  }
}

/**
 * Finalize streaming message
 */
export function finalizeStreamingMessage(
  messageEl: HTMLElement,
  messageId: string,
  createdAt?: string
): void {
  messageEl.classList.remove('streaming');
  messageEl.dataset.messageId = messageId;

  // Remove cursor
  const cursor = messageEl.querySelector('.streaming-cursor');
  cursor?.remove();

  // Apply syntax highlighting to code blocks
  const content = messageEl.querySelector('.message-content');
  if (content) {
    highlightAllCodeBlocks(content as HTMLElement);
  }

  // Add message actions (timestamp + copy button)
  const contentWrapper = messageEl.querySelector('.message-content-wrapper');
  if (contentWrapper && !contentWrapper.querySelector('.message-actions')) {
    const actions = document.createElement('div');
    actions.className = 'message-actions';
    const timeStr = createdAt ? formatMessageTime(createdAt) : '';
    actions.innerHTML = `
      ${timeStr ? `<span class="message-time">${timeStr}</span>` : ''}
      <button class="message-copy-btn" title="Copy message">
        ${COPY_ICON}
      </button>
    `;
    contentWrapper.appendChild(actions);
  }
}

/**
 * Show loading indicator in messages
 */
export function showLoadingIndicator(): void {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) return;

  // Remove existing loading indicator
  hideLoadingIndicator();

  const loading = document.createElement('div');
  loading.className = 'message-loading';
  loading.innerHTML = `
    <div class="loading-dots">
      <span></span>
      <span></span>
      <span></span>
    </div>
  `;
  container.appendChild(loading);
  scrollToBottom(container);
}

/**
 * Hide loading indicator
 */
export function hideLoadingIndicator(): void {
  const loading = document.querySelector('.message-loading');
  loading?.remove();
}

/**
 * Show conversation loading overlay
 */
export function showConversationLoader(): void {
  const container = getElementById<HTMLDivElement>('messages');
  if (!container) return;

  // Remove existing loader
  hideConversationLoader();

  const loader = document.createElement('div');
  loader.className = 'conversation-loader';
  loader.innerHTML = `
    <div class="conversation-loader-content">
      <div class="loading-dots">
        <span></span>
        <span></span>
        <span></span>
      </div>
      <p>Loading conversation...</p>
    </div>
  `;
  container.appendChild(loader);
}

/**
 * Hide conversation loading overlay
 */
export function hideConversationLoader(): void {
  const loader = document.querySelector('.conversation-loader');
  loader?.remove();
}

/**
 * Update chat title in mobile header
 */
export function updateChatTitle(title: string): void {
  const titleEl = getElementById<HTMLSpanElement>('current-chat-title');
  if (titleEl) {
    titleEl.textContent = title;
  }
}

/**
 * Render details (thinking/tool events) for a message
 */
function renderDetails(details: DetailEvent[]): string {
  // Track which tool calls have results for loading state
  const toolResultIds = new Set<string>();
  details.forEach(event => {
    if (event.type === 'tool_result') {
      toolResultIds.add(event.tool_call_id);
    }
  });
  
  return `<div class="message-details-content">${details
    .map((event) => {
      if (event.type === 'thinking') {
        // Trim leading/trailing whitespace but preserve internal formatting
        const trimmedContent = event.content.trim();
        // Render markdown for thinking content (supports bold, italic, code, etc.)
        const renderedContent = renderMarkdown(trimmedContent);
        return `
          <div class="detail-thinking">
            <div class="thinking-header">
              ${THINKING_ICON}
              <span class="thinking-label">Thinking</span>
            </div>
            <div class="thinking-content">${renderedContent}</div>
          </div>
        `;
      } else if (event.type === 'tool_call') {
        const argsStr = JSON.stringify(event.args, null, 2);
        // Use syntax highlighting for JSON args
        const highlightedArgs = highlightCode(argsStr, 'json');
        // Check if this tool call has a corresponding result
        const hasResult = toolResultIds.has(event.id);
        return `
          <div class="detail-tool-call" data-tool-id="${escapeHtml(event.id)}">
            <div class="tool-call-header">
              ${TOOL_ICON}
              <span class="tool-name">${escapeHtml(event.name)}</span>
              ${!hasResult ? `<span class="tool-spinner">${SPINNER_ICON}</span>` : ''}
            </div>
            <pre class="tool-args"><code class="hljs language-json">${highlightedArgs}</code></pre>
          </div>
        `;
      } else if (event.type === 'tool_result') {
        // Try to parse and highlight as JSON if it's valid JSON
        const content = event.content;
        let renderedContent: string;

        // Try JSON parsing first (more reliable than heuristics)
        try {
          const parsed = JSON.parse(content);
          const formatted = JSON.stringify(parsed, null, 2);
          renderedContent = `<pre class="tool-result-content"><code class="hljs language-json">${highlightCode(formatted, 'json')}</code></pre>`;
        } catch {
          // Not valid JSON - check if it looks like JSON and might be truncated
          const trimmed = content.trim();
          const looksLikeJson = trimmed.startsWith('{') || trimmed.startsWith('[');
          
          if (looksLikeJson) {
            // Might be truncated JSON - still try to highlight as JSON
            renderedContent = `<pre class="tool-result-content"><code class="hljs language-json">${highlightCode(content, 'json')}</code></pre>`;
          } else {
            // Render as markdown (e.g., fetch_url returns markdown text from HTML conversion)
            renderedContent = `<div class="tool-result-markdown">${renderMarkdown(content)}</div>`;
          }
        }
        return `
          <div class="detail-tool-result" data-tool-id="${escapeHtml(event.tool_call_id)}">
            <div class="tool-result-header">
              ${CHECK_ICON}
              <span class="tool-result-label">Result</span>
            </div>
            ${renderedContent}
          </div>
        `;
      }
      return '';
    })
    .join('')}</div>`;
}

/**
 * Create inline details toggle for inside the message bubble
 * This creates a small toggle that sits at the top-right of the message content
 */
function createInlineDetailsToggle(messageId: string): HTMLElement {
  const toggle = document.createElement('button');
  toggle.className = 'inline-details-toggle';
  toggle.title = 'Show details';
  toggle.setAttribute('aria-expanded', 'false');
  toggle.innerHTML = `${CHEVRON_RIGHT_ICON}`;

  toggle.addEventListener('click', async () => {
    const messageEl = toggle.closest('.message');
    if (!messageEl) return;

    const detailsSection = messageEl.querySelector('.message-details');
    if (!detailsSection) return;

    const isExpanded = toggle.getAttribute('aria-expanded') === 'true';

    if (isExpanded) {
      // Collapse
      toggle.setAttribute('aria-expanded', 'false');
      detailsSection.classList.add('collapsed');
      useStore.getState().toggleMessageDetails(messageId);
      // Scroll button visibility will be updated by ResizeObserver in ScrollToBottom.ts
    } else {
      // Expand
      toggle.setAttribute('aria-expanded', 'true');
      detailsSection.classList.remove('collapsed');
      useStore.getState().toggleMessageDetails(messageId);

      // Check if we need to lazy load the details
      const cachedDetails = useStore.getState().messageDetails.get(messageId);
      if (!cachedDetails && detailsSection.classList.contains('loading')) {
        // Fetch details from API
        try {
          const details = await messagesApi.getDetails(messageId);
          useStore.getState().setMessageDetails(messageId, details);
          detailsSection.classList.remove('loading');
          detailsSection.innerHTML = renderDetails(details);
          // Apply syntax highlighting to code blocks in thinking content
          const thinkingContent = detailsSection.querySelector('.thinking-content');
          if (thinkingContent) {
            highlightAllCodeBlocks(thinkingContent as HTMLElement);
          }
        } catch (error) {
          console.error('Failed to load message details:', error);
          detailsSection.classList.remove('loading');
          detailsSection.innerHTML = '<div class="detail-error">Failed to load details</div>';
        }
      }
      // Scroll button visibility will be updated by ResizeObserver in ScrollToBottom.ts
    }
  });

  return toggle;
}

/**
 * Create details section for a message (collapsed by default)
 */
function createDetailsSection(
  _messageId: string,
  hasDetails: boolean,
  details?: DetailEvent[]
): HTMLElement {
  const section = document.createElement('div');
  section.className = 'message-details collapsed';

  if (details && details.length > 0) {
    // We have the details data - render it
    section.innerHTML = renderDetails(details);
    // Apply syntax highlighting to code blocks in thinking content
    const thinkingContent = section.querySelector('.thinking-content');
    if (thinkingContent) {
      highlightAllCodeBlocks(thinkingContent as HTMLElement);
    }
  } else if (hasDetails) {
    // Details exist but need to be lazy loaded
    section.classList.add('loading');
    section.innerHTML = `<div class="detail-loading">${SPINNER_ICON} Loading...</div>`;
  }

  return section;
}

/**
 * Add details section to a streaming message
 */
export function addStreamingDetails(messageEl: HTMLElement): void {
  const content = messageEl.querySelector('.message-content');
  if (!content) return;

  // Check if details section already exists
  if (content.querySelector('.message-details')) return;

  // Add inline toggle button (hidden until we have details)
  const toggle = document.createElement('button');
  toggle.className = 'inline-details-toggle';
  toggle.title = 'Show details';
  toggle.setAttribute('aria-expanded', 'false'); // Start collapsed
  toggle.innerHTML = `${CHEVRON_RIGHT_ICON}`;
  toggle.style.display = 'none'; // Hidden until we have details

  // Add details section (collapsed by default, even during streaming)
  const section = document.createElement('div');
  section.className = 'message-details streaming-details collapsed';

  // Insert at beginning of content
  content.insertBefore(section, content.firstChild);
  content.insertBefore(toggle, content.firstChild);

  // Set up toggle click handler for streaming
  toggle.addEventListener('click', () => {
    const isExpanded = toggle.getAttribute('aria-expanded') === 'true';
    if (isExpanded) {
      toggle.setAttribute('aria-expanded', 'false');
      section.classList.add('collapsed');
      // Scroll button visibility will be updated by ResizeObserver in ScrollToBottom.ts
    } else {
      toggle.setAttribute('aria-expanded', 'true');
      section.classList.remove('collapsed');
      // Scroll button visibility will be updated by ResizeObserver in ScrollToBottom.ts
    }
  });
}

/**
 * Update details section during streaming
 */
export function updateStreamingDetails(
  messageEl: HTMLElement,
  details: DetailEvent[]
): void {
  const section = messageEl.querySelector('.message-details') as HTMLElement | null;
  const toggle = messageEl.querySelector('.inline-details-toggle') as HTMLElement | null;

  if (!section || !toggle) return;

  if (details.length > 0) {
    // Check scroll position before updating DOM
    const messagesContainer = getElementById('messages')!;
    const wasAtBottom = isScrolledToBottom(messagesContainer);
    
    // Show toggle when we have details
    toggle.style.display = '';
    section.innerHTML = renderDetails(details);
    
    // Apply syntax highlighting to code blocks in thinking content
    const thinkingContent = section.querySelector('.thinking-content');
    if (thinkingContent) {
      highlightAllCodeBlocks(thinkingContent as HTMLElement);
    }

    // Maintain scroll position if user was at bottom (details are collapsed by default)
    // This ensures autoscroll works during streaming
    if (wasAtBottom) {
      // Use double RAF to ensure DOM has fully updated
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          scrollToBottom(messagesContainer);
        });
      });
    }
  }
}

/**
 * Finalize details section after streaming completes
 */
export function finalizeStreamingDetails(
  messageEl: HTMLElement,
  messageId: string,
  details?: DetailEvent[]
): void {
  const section = messageEl.querySelector('.message-details') as HTMLElement | null;
  const toggle = messageEl.querySelector('.inline-details-toggle') as HTMLElement | null;

  if (!section || !toggle) return;

  section.classList.remove('streaming-details');

  if (details && details.length > 0) {
    // Store details in cache
    useStore.getState().setMessageDetails(messageId, details);

    // Preserve expanded state if user had expanded during streaming
    // Otherwise keep collapsed (the click handler was already set up in addStreamingDetails)
    const wasExpanded = toggle.getAttribute('aria-expanded') === 'true';
    if (!wasExpanded) {
      section.classList.add('collapsed');
    }
  } else {
    // No details - hide the toggle and section
    toggle.style.display = 'none';
    section.classList.add('collapsed');
  }
}