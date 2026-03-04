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
    archivedConversations: [],
    archivedPagination: {
      nextCursor: null,
      hasMore: false,
      totalCount: 0,
      isLoadingMore: false,
    },
    isArchiveView: false,
  });
}

describe('Sidebar', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="app">
        <aside id="sidebar">
          <div id="conversations-list"></div>
          <div id="archive-entry-container"></div>
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

    it('includes archive button with correct data-archive-id attribute', () => {
      useStore.setState({
        conversations: [createConversation('conv-456', 'Archivable Chat')],
      });

      renderConversationsList();

      const archiveBtn = document.querySelector('.conversation-archive');
      expect(archiveBtn?.getAttribute('data-archive-id')).toBe('conv-456');
    });

    it('renders archive button for every conversation item', () => {
      useStore.setState({
        conversations: [
          createConversation('a', 'First'),
          createConversation('b', 'Second'),
          createConversation('c', 'Third'),
        ],
      });

      renderConversationsList();

      const archiveBtns = document.querySelectorAll('.conversation-archive');
      expect(archiveBtns.length).toBe(3);
      expect(archiveBtns[0].getAttribute('data-archive-id')).toBe('a');
      expect(archiveBtns[1].getAttribute('data-archive-id')).toBe('b');
      expect(archiveBtns[2].getAttribute('data-archive-id')).toBe('c');
    });

    it('renders archive entry in pinned container when archivedPagination.totalCount > 0', () => {
      useStore.setState({
        conversations: [createConversation('1', 'Active Chat')],
        archivedConversations: [createConversation('2', 'Archived Chat')],
        archivedPagination: {
          nextCursor: null,
          hasMore: false,
          totalCount: 1,
          isLoadingMore: false,
        },
      });

      renderConversationsList();

      const entryContainer = document.getElementById('archive-entry-container');
      const archiveEntry = entryContainer?.querySelector('.archive-entry');
      expect(archiveEntry).not.toBeNull();
    });

    it('renders archive entry when archivedConversations length > 0 with totalCount > 0', () => {
      useStore.setState({
        conversations: [createConversation('1', 'Active')],
        archivedConversations: [
          createConversation('arch-1', 'Old Chat'),
          createConversation('arch-2', 'Another Old Chat'),
        ],
        archivedPagination: {
          nextCursor: null,
          hasMore: false,
          totalCount: 2,
          isLoadingMore: false,
        },
      });

      renderConversationsList();

      const entryContainer = document.getElementById('archive-entry-container');
      const archiveEntry = entryContainer?.querySelector('.archive-entry');
      expect(archiveEntry).not.toBeNull();
    });

    it('hides archive entry when totalCount is 0 and no archived conversations', () => {
      useStore.setState({
        conversations: [createConversation('1', 'Active Chat')],
        archivedConversations: [],
        archivedPagination: {
          nextCursor: null,
          hasMore: false,
          totalCount: 0,
          isLoadingMore: false,
        },
      });

      renderConversationsList();

      const entryContainer = document.getElementById('archive-entry-container');
      const archiveEntry = entryContainer?.querySelector('.archive-entry');
      expect(archiveEntry).toBeNull();
    });

    it('renders archive view with back button and items when isArchiveView is true', () => {
      useStore.setState({
        conversations: [createConversation('1', 'Active')],
        archivedConversations: [createConversation('arch-1', 'Archived Chat')],
        archivedPagination: {
          nextCursor: null,
          hasMore: false,
          totalCount: 1,
          isLoadingMore: false,
        },
        isArchiveView: true,
      });

      renderConversationsList();

      const header = document.querySelector('.archive-view-header');
      expect(header).not.toBeNull();
      const backBtn = document.querySelector('.archive-back-btn');
      expect(backBtn).not.toBeNull();
      const unarchiveBtn = document.querySelector('.conversation-unarchive');
      expect(unarchiveBtn).not.toBeNull();
      expect(unarchiveBtn?.getAttribute('data-unarchive-id')).toBe('arch-1');
    });

    it('renders rename button on archived items in archive view', () => {
      useStore.setState({
        conversations: [createConversation('1', 'Active')],
        archivedConversations: [createConversation('arch-1', 'Archived Chat')],
        archivedPagination: {
          nextCursor: null,
          hasMore: false,
          totalCount: 1,
          isLoadingMore: false,
        },
        isArchiveView: true,
      });

      renderConversationsList();

      const renameBtn = document.querySelector('.conversation-rename');
      expect(renameBtn).not.toBeNull();
      expect(renameBtn?.getAttribute('data-rename-id')).toBe('arch-1');
    });

    it('renders unarchive button for each archived item in archive view', () => {
      useStore.setState({
        conversations: [createConversation('1', 'Active')],
        archivedConversations: [
          createConversation('a1', 'Archived One'),
          createConversation('a2', 'Archived Two'),
        ],
        archivedPagination: {
          nextCursor: null,
          hasMore: false,
          totalCount: 2,
          isLoadingMore: false,
        },
        isArchiveView: true,
      });

      renderConversationsList();

      const unarchiveBtns = document.querySelectorAll('.conversation-unarchive');
      expect(unarchiveBtns.length).toBe(2);
      expect(unarchiveBtns[0].getAttribute('data-unarchive-id')).toBe('a1');
      expect(unarchiveBtns[1].getAttribute('data-unarchive-id')).toBe('a2');
    });

    it('does not render archived items in normal view (only archive entry in pinned container)', () => {
      useStore.setState({
        conversations: [createConversation('1', 'Active')],
        archivedConversations: [createConversation('arch-1', 'Archived Chat')],
        archivedPagination: {
          nextCursor: null,
          hasMore: false,
          totalCount: 1,
          isLoadingMore: false,
        },
        isArchiveView: false,
      });

      renderConversationsList();

      // Archive entry should be in pinned container but items should not be visible
      const entryContainer = document.getElementById('archive-entry-container');
      const archiveEntry = entryContainer?.querySelector('.archive-entry');
      expect(archiveEntry).not.toBeNull();
      const unarchiveBtn = document.querySelector('.conversation-unarchive');
      expect(unarchiveBtn).toBeNull();
    });

    it('shows archive entry with totalCount even when local list is empty', () => {
      // totalCount > 0 but archivedConversations not yet loaded
      useStore.setState({
        conversations: [createConversation('1', 'Active')],
        archivedConversations: [],
        archivedPagination: {
          nextCursor: null,
          hasMore: false,
          totalCount: 3,
          isLoadingMore: false,
        },
      });

      renderConversationsList();

      const entryContainer = document.getElementById('archive-entry-container');
      const archiveEntry = entryContainer?.querySelector('.archive-entry');
      expect(archiveEntry).not.toBeNull();
      expect(archiveEntry?.innerHTML).toContain('3');
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
