/**
 * Component tests for Messages
 *
 * Tests the scroll-to-bottom behavior when rendering messages,
 * particularly focusing on the fix for switching between conversations
 * of different lengths with lazy-loaded images.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { useStore } from '@/state/store';
import type { Message, User } from '@/types/api';

// Mock the costs API
vi.mock('@/api/client', () => ({
  costs: {
    getMessageCost: vi.fn().mockResolvedValue({
      cost_usd: 0.001,
      formatted: '0.025 CZK',
    }),
  },
}));

// Create mocks at module level (vi.fn() is hoisted)
const scrollToBottomMock = vi.fn();
const observeThumbnailMock = vi.fn();

// Mock scrollToBottom to track calls (don't call actual since jsdom doesn't support scrollTo)
vi.mock('@/utils/dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/dom')>();
  return {
    ...actual,
    scrollToBottom: (...args: Parameters<typeof actual.scrollToBottom>) => {
      scrollToBottomMock(...args);
      // Don't call actual - jsdom doesn't implement scrollTo
    },
  };
});

// Mock observeThumbnail to track image observations
vi.mock('@/utils/thumbnails', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/thumbnails')>();
  return {
    ...actual,
    observeThumbnail: (...args: Parameters<typeof actual.observeThumbnail>) => {
      observeThumbnailMock(...args);
    },
  };
});

// Import after mocks are set up
import { renderMessages, addMessageToUI } from '@/components/messages';
import {
  enableScrollOnImageLoad,
  disableScrollOnImageLoad,
} from '@/utils/thumbnails';

// Helper to create mock message
function createMessage(
  id: string,
  content: string,
  role: 'user' | 'assistant' = 'user',
  files?: { name: string; type: string; previewUrl?: string }[]
): Message {
  return {
    id,
    role,
    content,
    created_at: '2024-01-01T00:00:00Z',
    files: files?.map((f, i) => ({
      name: f.name,
      type: f.type,
      fileIndex: i,
      previewUrl: f.previewUrl,
    })),
  };
}

// Helper to create mock user
function createUser(): User {
  return {
    id: 'user-1',
    email: 'test@example.com',
    name: 'Test User',
    picture: 'https://example.com/pic.jpg',
  };
}

// Reset store state
function resetStore() {
  useStore.setState({
    conversations: [],
    currentConversation: null,
    isLoading: false,
    isSidebarOpen: false,
    user: createUser(),
    token: 'test-token',
    googleClientId: null,
    models: [],
    defaultModel: 'gemini-3-flash-preview',
    streamingEnabled: true,
    forceTools: [],
    pendingFiles: [],
    uploadConfig: {
      maxFileSize: 20 * 1024 * 1024,
      maxFilesPerMessage: 10,
      allowedFileTypes: [],
    },
    appVersion: null,
    newVersionAvailable: false,
    versionBannerDismissed: false,
  });
}

describe('Messages - renderMessages', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="app">
        <div id="messages" class="messages"></div>
      </div>
    `;
    resetStore();
    scrollToBottomMock.mockClear();
    observeThumbnailMock.mockClear();
    disableScrollOnImageLoad();
  });

  afterEach(() => {
    disableScrollOnImageLoad();
  });

  describe('scroll behavior', () => {
    it('scrolls to bottom when rendering messages without images', async () => {
      const messages = [
        createMessage('1', 'Hello'),
        createMessage('2', 'Hi there', 'assistant'),
        createMessage('3', 'How are you?'),
      ];

      renderMessages(messages);

      // Wait for requestAnimationFrame callbacks to complete
      await vi.waitFor(() => {
        expect(scrollToBottomMock).toHaveBeenCalled();
      });
    });

    it('scrolls to bottom when rendering messages with preloaded images', async () => {
      const messages = [
        createMessage('1', 'Check this out', 'user', [
          { name: 'photo.jpg', type: 'image/jpeg', previewUrl: 'blob:preview' },
        ]),
        createMessage('2', 'Nice image!', 'assistant'),
      ];

      renderMessages(messages);

      // Wait for requestAnimationFrame callbacks to complete
      await vi.waitFor(() => {
        expect(scrollToBottomMock).toHaveBeenCalled();
      });

      // Should NOT observe thumbnails for images with previewUrl
      expect(observeThumbnailMock).not.toHaveBeenCalled();
    });

    it('scrolls to bottom when rendering messages with lazy-loaded images', async () => {
      const messages = [
        createMessage('1', 'Check this out', 'user', [
          { name: 'photo.jpg', type: 'image/jpeg' }, // No previewUrl = lazy loaded
        ]),
        createMessage('2', 'Nice image!', 'assistant'),
      ];

      enableScrollOnImageLoad();
      renderMessages(messages);

      // Wait for requestAnimationFrame callbacks to complete
      await vi.waitFor(() => {
        expect(scrollToBottomMock).toHaveBeenCalled();
      });

      // Should ALWAYS scroll to bottom first (this is the fix)
      // The scroll-on-image-load system handles subsequent scrolls after images load
      // Should observe thumbnails for lazy-loaded images
      expect(observeThumbnailMock).toHaveBeenCalled();
    });

    it('scrolls to bottom for long conversations with many messages', async () => {
      // Create a long conversation
      const messages: Message[] = [];
      for (let i = 0; i < 50; i++) {
        messages.push(createMessage(`${i}`, `Message ${i}`, i % 2 === 0 ? 'user' : 'assistant'));
      }

      renderMessages(messages);

      // Wait for requestAnimationFrame callbacks to complete
      await vi.waitFor(() => {
        expect(scrollToBottomMock).toHaveBeenCalled();
      });
    });

    it('scrolls to bottom for long conversations with lazy-loaded images', async () => {
      // Create a long conversation with images
      const messages: Message[] = [];
      for (let i = 0; i < 30; i++) {
        if (i % 5 === 0) {
          // Every 5th message has an image
          messages.push(
            createMessage(`${i}`, `Message ${i} with image`, i % 2 === 0 ? 'user' : 'assistant', [
              { name: `image${i}.jpg`, type: 'image/jpeg' }, // Lazy loaded
            ])
          );
        } else {
          messages.push(
            createMessage(`${i}`, `Message ${i}`, i % 2 === 0 ? 'user' : 'assistant')
          );
        }
      }

      enableScrollOnImageLoad();
      renderMessages(messages);

      // Wait for requestAnimationFrame callbacks to complete
      await vi.waitFor(() => {
        expect(scrollToBottomMock).toHaveBeenCalled();
      });

      // Should ALWAYS scroll to bottom first (the key fix)
      // This ensures images at the bottom become visible, triggering IntersectionObserver
    });
  });

  describe('empty state', () => {
    it('renders welcome message when no messages', () => {
      renderMessages([]);

      const container = document.getElementById('messages');
      expect(container?.innerHTML).toContain('Welcome to AI Chatbot');
      expect(container?.innerHTML).toContain('Start a conversation');
    });

    it('does not scroll when rendering empty messages', () => {
      renderMessages([]);

      // No scroll needed for welcome message
      expect(scrollToBottomMock).not.toHaveBeenCalled();
    });
  });

  describe('message rendering', () => {
    it('renders user messages correctly', () => {
      const messages = [createMessage('1', 'Hello world')];

      renderMessages(messages);

      const container = document.getElementById('messages');
      const userMessage = container?.querySelector('.message.user');
      expect(userMessage).not.toBeNull();
      expect(userMessage?.innerHTML).toContain('Hello world');
    });

    it('renders assistant messages correctly', () => {
      const messages = [createMessage('1', 'Hello!', 'assistant')];

      renderMessages(messages);

      const container = document.getElementById('messages');
      const assistantMessage = container?.querySelector('.message.assistant');
      expect(assistantMessage).not.toBeNull();
      expect(assistantMessage?.innerHTML).toContain('Hello!');
    });

    it('renders images with loading state for lazy-loaded images', () => {
      const messages = [
        createMessage('1', 'Image', 'user', [{ name: 'test.jpg', type: 'image/jpeg' }]),
      ];

      renderMessages(messages);

      const container = document.getElementById('messages');
      const imageWrapper = container?.querySelector('.message-image-wrapper');
      expect(imageWrapper?.classList.contains('loading')).toBe(true);
    });

    it('does not add loading state for images with previewUrl', () => {
      const messages = [
        createMessage('1', 'Image', 'user', [
          { name: 'test.jpg', type: 'image/jpeg', previewUrl: 'blob:preview' },
        ]),
      ];

      renderMessages(messages);

      const container = document.getElementById('messages');
      const imageWrapper = container?.querySelector('.message-image-wrapper');
      expect(imageWrapper?.classList.contains('loading')).toBe(false);
    });
  });
});

describe('Messages - addMessageToUI', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="app">
        <div id="messages" class="messages"></div>
      </div>
    `;
    resetStore();
    scrollToBottomMock.mockClear();
    observeThumbnailMock.mockClear();
  });

  it('adds message to container', () => {
    const container = document.getElementById('messages')!;
    const message = createMessage('1', 'Test message');

    addMessageToUI(message, container);

    expect(container.querySelector('.message')).not.toBeNull();
    expect(container.innerHTML).toContain('Test message');
  });

  it('adds message with correct role class', () => {
    const container = document.getElementById('messages')!;

    addMessageToUI(createMessage('1', 'User message', 'user'), container);
    addMessageToUI(createMessage('2', 'Assistant message', 'assistant'), container);

    expect(container.querySelectorAll('.message.user').length).toBe(1);
    expect(container.querySelectorAll('.message.assistant').length).toBe(1);
  });

  it('observes lazy-loaded images', () => {
    const container = document.getElementById('messages')!;
    const message = createMessage('1', 'Image', 'user', [
      { name: 'test.jpg', type: 'image/jpeg' },
    ]);

    addMessageToUI(message, container);

    expect(observeThumbnailMock).toHaveBeenCalled();
  });

  it('does not observe images with previewUrl', () => {
    const container = document.getElementById('messages')!;
    const message = createMessage('1', 'Image', 'user', [
      { name: 'test.jpg', type: 'image/jpeg', previewUrl: 'blob:preview' },
    ]);

    addMessageToUI(message, container);

    expect(observeThumbnailMock).not.toHaveBeenCalled();
  });
});