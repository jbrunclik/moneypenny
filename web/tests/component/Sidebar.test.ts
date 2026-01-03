/**
 * Component tests for Sidebar
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '@/state/store';
import {
  renderConversationsList,
  renderUserInfo,
  updateConversationTitle,
  setActiveConversation,
  toggleSidebar,
  closeSidebar,
} from '@/components/Sidebar';
import type { Conversation, User } from '@/types/api';

// Mock the costs API
vi.mock('@/api/client', () => ({
  costs: {
    getMonthlyCost: vi.fn().mockResolvedValue({ formatted: '10.50 CZK' }),
  },
}));

// Helper to create mock conversation
function createConversation(id: string, title: string): Conversation {
  return {
    id,
    title,
    model: 'gemini-3-flash-preview',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
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
    user: null,
    token: null,
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

describe('Sidebar', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="app">
        <aside id="sidebar">
          <div id="conversations-list"></div>
          <div id="user-info"></div>
        </aside>
      </div>
    `;
    resetStore();
  });

  describe('renderConversationsList', () => {
    it('renders empty state when no conversations', () => {
      renderConversationsList();

      const container = document.getElementById('conversations-list');
      expect(container?.innerHTML).toContain('No conversations yet');
      expect(container?.innerHTML).toContain('Start a new chat');
    });

    it('renders loading state when loading with no conversations', () => {
      useStore.setState({ isLoading: true });

      renderConversationsList();

      const container = document.getElementById('conversations-list');
      expect(container?.innerHTML).toContain('loading-spinner');
    });

    it('renders conversations list', () => {
      useStore.setState({
        conversations: [
          createConversation('1', 'First Chat'),
          createConversation('2', 'Second Chat'),
        ],
      });

      renderConversationsList();

      const container = document.getElementById('conversations-list');
      const items = container?.querySelectorAll('.conversation-item-wrapper');

      expect(items?.length).toBe(2);
      expect(container?.innerHTML).toContain('First Chat');
      expect(container?.innerHTML).toContain('Second Chat');
    });

    it('marks current conversation as active', () => {
      const conv = createConversation('1', 'Active Chat');
      useStore.setState({
        conversations: [conv, createConversation('2', 'Other')],
        currentConversation: conv,
      });

      renderConversationsList();

      const activeWrapper = document.querySelector('[data-conv-id="1"]');
      const otherWrapper = document.querySelector('[data-conv-id="2"]');

      expect(activeWrapper?.classList.contains('active')).toBe(true);
      expect(otherWrapper?.classList.contains('active')).toBe(false);
    });

    it('escapes HTML in conversation titles', () => {
      useStore.setState({
        conversations: [createConversation('1', '<script>alert("xss")</script>')],
      });

      renderConversationsList();

      const container = document.getElementById('conversations-list');
      expect(container?.innerHTML).not.toContain('<script>');
      expect(container?.innerHTML).toContain('&lt;script&gt;');
    });

    it('uses default title for untitled conversations', () => {
      useStore.setState({
        conversations: [{ ...createConversation('1', ''), title: '' }],
      });

      renderConversationsList();

      const container = document.getElementById('conversations-list');
      expect(container?.innerHTML).toContain('New Conversation');
    });

    it('includes delete buttons with correct data attributes', () => {
      useStore.setState({
        conversations: [createConversation('conv-123', 'Test')],
      });

      renderConversationsList();

      const deleteBtn = document.querySelector('.conversation-delete');
      expect(deleteBtn?.getAttribute('data-delete-id')).toBe('conv-123');
    });

    it('shows load more indicator when hasMore is true', () => {
      useStore.setState({
        conversations: [createConversation('1', 'Test')],
        conversationsPagination: {
          nextCursor: 'cursor-123',
          hasMore: true,
          totalCount: 10,
          isLoadingMore: false,
        },
      });

      renderConversationsList();

      const loadMore = document.querySelector('.conversations-load-more');
      expect(loadMore).not.toBeNull();
      expect(loadMore?.classList.contains('loading')).toBe(false);
    });

    it('shows loading dots when isLoadingMore is true', () => {
      useStore.setState({
        conversations: [createConversation('1', 'Test')],
        conversationsPagination: {
          nextCursor: 'cursor-123',
          hasMore: true,
          totalCount: 10,
          isLoadingMore: true,
        },
      });

      renderConversationsList();

      const loadMore = document.querySelector('.conversations-load-more');
      expect(loadMore?.classList.contains('loading')).toBe(true);

      const loadingDots = loadMore?.querySelector('.loading-dots');
      expect(loadingDots).not.toBeNull();
      expect(loadingDots?.querySelectorAll('span')).toHaveLength(3);
    });

    it('does not show load more indicator when hasMore is false', () => {
      useStore.setState({
        conversations: [createConversation('1', 'Test')],
        conversationsPagination: {
          nextCursor: null,
          hasMore: false,
          totalCount: 1,
          isLoadingMore: false,
        },
      });

      renderConversationsList();

      const loadMore = document.querySelector('.conversations-load-more');
      expect(loadMore).toBeNull();
    });

    it('loader visibility updates when loading state changes', () => {
      useStore.setState({
        conversations: [createConversation('1', 'Test')],
        conversationsPagination: {
          nextCursor: 'cursor-123',
          hasMore: true,
          totalCount: 10,
          isLoadingMore: false,
        },
      });

      renderConversationsList();

      // Initially not loading
      const loadMore = document.querySelector('.conversations-load-more');
      expect(loadMore?.classList.contains('loading')).toBe(false);

      // Set loading state
      useStore.getState().setLoadingMoreConversations(true);
      renderConversationsList();

      // Should now show loading
      const loadMoreLoading = document.querySelector('.conversations-load-more');
      expect(loadMoreLoading?.classList.contains('loading')).toBe(true);

      // Reset loading state
      useStore.getState().setLoadingMoreConversations(false);
      renderConversationsList();

      // Should no longer show loading
      const loadMoreDone = document.querySelector('.conversations-load-more');
      expect(loadMoreDone?.classList.contains('loading')).toBe(false);
    });

    it('loader state persists correctly after re-render', () => {
      useStore.setState({
        conversations: [createConversation('1', 'Test')],
        conversationsPagination: {
          nextCursor: 'cursor-123',
          hasMore: true,
          totalCount: 10,
          isLoadingMore: true, // Start in loading state
        },
      });

      renderConversationsList();

      // Should show loading
      const loadMore = document.querySelector('.conversations-load-more');
      expect(loadMore?.classList.contains('loading')).toBe(true);

      // Re-render without changing state
      renderConversationsList();

      // Should still show loading (regression: state should persist)
      const loadMoreAfterRerender = document.querySelector('.conversations-load-more');
      expect(loadMoreAfterRerender?.classList.contains('loading')).toBe(true);
      expect(useStore.getState().conversationsPagination.isLoadingMore).toBe(true);
    });
  });

  describe('renderUserInfo', () => {
    it('renders empty when no user', () => {
      renderUserInfo();

      const container = document.getElementById('user-info');
      expect(container?.innerHTML).toBe('');
    });

    it('renders user profile with name', async () => {
      useStore.setState({ user: createUser() });

      renderUserInfo();

      const container = document.getElementById('user-info');
      expect(container?.innerHTML).toContain('Test User');
      expect(container?.innerHTML).toContain('user-avatar');
    });

    it('renders logout button', () => {
      useStore.setState({ user: createUser() });

      renderUserInfo();

      const logoutBtn = document.getElementById('logout-btn');
      expect(logoutBtn).not.toBeNull();
    });

    it('renders monthly cost button', () => {
      useStore.setState({ user: createUser() });

      renderUserInfo();

      const costBtn = document.getElementById('monthly-cost');
      expect(costBtn).not.toBeNull();
      expect(costBtn?.innerHTML).toContain('This month:');
    });

    it('escapes HTML in user name', () => {
      useStore.setState({
        user: { ...createUser(), name: '<b>Bold Name</b>' },
      });

      renderUserInfo();

      // Check that the displayed user name text is escaped (not rendered as HTML)
      const userName = document.querySelector('.user-name');
      expect(userName?.innerHTML).toContain('&lt;b&gt;');
      expect(userName?.textContent).toBe('<b>Bold Name</b>');
    });

    it('falls back to email if no name', () => {
      useStore.setState({
        user: { ...createUser(), name: '' },
      });

      renderUserInfo();

      const container = document.getElementById('user-info');
      expect(container?.innerHTML).toContain('test@example.com');
    });
  });

  describe('updateConversationTitle', () => {
    beforeEach(() => {
      useStore.setState({
        conversations: [createConversation('1', 'Original Title')],
      });
      renderConversationsList();
    });

    it('updates title in DOM', () => {
      updateConversationTitle('1', 'New Title');

      const titleEl = document.querySelector('.conversation-title');
      expect(titleEl?.textContent).toBe('New Title');
    });

    it('does nothing for non-existent conversation', () => {
      updateConversationTitle('nonexistent', 'New Title');

      // Should not throw
      const titleEl = document.querySelector('.conversation-title');
      expect(titleEl?.textContent).toBe('Original Title');
    });
  });

  describe('setActiveConversation', () => {
    beforeEach(() => {
      useStore.setState({
        conversations: [
          createConversation('1', 'First'),
          createConversation('2', 'Second'),
        ],
      });
      renderConversationsList();
    });

    it('sets active class on correct conversation', () => {
      setActiveConversation('1');

      const wrapper1 = document.querySelector('[data-conv-id="1"]');
      const wrapper2 = document.querySelector('[data-conv-id="2"]');

      expect(wrapper1?.classList.contains('active')).toBe(true);
      expect(wrapper2?.classList.contains('active')).toBe(false);
    });

    it('removes active class from previous active', () => {
      setActiveConversation('1');
      setActiveConversation('2');

      const wrapper1 = document.querySelector('[data-conv-id="1"]');
      const wrapper2 = document.querySelector('[data-conv-id="2"]');

      expect(wrapper1?.classList.contains('active')).toBe(false);
      expect(wrapper2?.classList.contains('active')).toBe(true);
    });

    it('removes all active classes when null', () => {
      setActiveConversation('1');
      setActiveConversation(null);

      const activeItems = document.querySelectorAll('.active');
      expect(activeItems.length).toBe(0);
    });
  });

  describe('toggleSidebar', () => {
    it('toggles sidebar open state in store', () => {
      expect(useStore.getState().isSidebarOpen).toBe(false);

      toggleSidebar();
      expect(useStore.getState().isSidebarOpen).toBe(true);

      toggleSidebar();
      expect(useStore.getState().isSidebarOpen).toBe(false);
    });

    it('adds open class to sidebar when opened', () => {
      toggleSidebar();

      const sidebar = document.getElementById('sidebar');
      expect(sidebar?.classList.contains('open')).toBe(true);
    });

    it('creates overlay when opened', () => {
      toggleSidebar();

      const overlay = document.querySelector('.sidebar-overlay');
      expect(overlay).not.toBeNull();
      expect(overlay?.classList.contains('visible')).toBe(true);
    });

    it('removes open class when closed', () => {
      toggleSidebar(); // Open
      toggleSidebar(); // Close

      const sidebar = document.getElementById('sidebar');
      expect(sidebar?.classList.contains('open')).toBe(false);
    });
  });

  describe('closeSidebar', () => {
    it('closes sidebar', () => {
      toggleSidebar(); // Open
      closeSidebar();

      expect(useStore.getState().isSidebarOpen).toBe(false);
      const sidebar = document.getElementById('sidebar');
      expect(sidebar?.classList.contains('open')).toBe(false);
    });

    it('removes visible class from overlay', () => {
      toggleSidebar(); // Open - creates overlay
      closeSidebar();

      const overlay = document.querySelector('.sidebar-overlay');
      expect(overlay?.classList.contains('visible')).toBe(false);
    });
  });
});
