/**
 * Unit tests for Zustand store
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '@/state/store';
import type { Conversation, ConversationsPagination, User, FileUpload, Model } from '@/types/api';

// Helper to reset store state
function resetStore() {
  useStore.setState({
    token: null,
    user: null,
    googleClientId: null,
    conversations: [],
    currentConversation: null,
    models: [],
    defaultModel: 'gemini-3-flash-preview',
    isLoading: false,
    isSidebarOpen: false,
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

// Helper to create a mock conversation
function createConversation(id: string, title: string): Conversation {
  return {
    id,
    title,
    model: 'gemini-3-flash-preview',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
  };
}

// Helper to create mock pagination
function createPagination(hasMore = false, totalCount = 0): ConversationsPagination {
  return {
    next_cursor: hasMore ? 'next-cursor' : null,
    has_more: hasMore,
    total_count: totalCount,
  };
}

// Helper to create a mock user
function createUser(email: string): User {
  return {
    id: `user-${email}`,
    email,
    name: 'Test User',
    picture: null,
  };
}

describe('Store - Auth', () => {
  beforeEach(resetStore);

  describe('setToken', () => {
    it('sets token', () => {
      useStore.getState().setToken('test-token');
      expect(useStore.getState().token).toBe('test-token');
    });

    it('clears token when null', () => {
      useStore.getState().setToken('test-token');
      useStore.getState().setToken(null);
      expect(useStore.getState().token).toBeNull();
    });
  });

  describe('setUser', () => {
    it('sets user', () => {
      const user = createUser('test@example.com');
      useStore.getState().setUser(user);
      expect(useStore.getState().user).toEqual(user);
    });

    it('clears user when null', () => {
      useStore.getState().setUser(createUser('test@example.com'));
      useStore.getState().setUser(null);
      expect(useStore.getState().user).toBeNull();
    });
  });

  describe('setGoogleClientId', () => {
    it('sets client ID', () => {
      useStore.getState().setGoogleClientId('client-123');
      expect(useStore.getState().googleClientId).toBe('client-123');
    });
  });

  describe('logout', () => {
    it('clears auth state and current conversation', () => {
      const user = createUser('test@example.com');
      const conv = createConversation('1', 'Test');

      useStore.getState().setToken('token');
      useStore.getState().setUser(user);
      useStore.getState().setCurrentConversation(conv);

      useStore.getState().logout();

      expect(useStore.getState().token).toBeNull();
      expect(useStore.getState().user).toBeNull();
      expect(useStore.getState().currentConversation).toBeNull();
    });

    it('preserves conversations list', () => {
      const conv = createConversation('1', 'Test');
      useStore.getState().addConversation(conv);
      useStore.getState().logout();

      expect(useStore.getState().conversations).toHaveLength(1);
    });
  });
});

describe('Store - Conversations', () => {
  beforeEach(resetStore);

  describe('setConversations', () => {
    it('sets conversation list', () => {
      const convs = [createConversation('1', 'First'), createConversation('2', 'Second')];
      useStore.getState().setConversations(convs, createPagination(false, 2));
      expect(useStore.getState().conversations).toHaveLength(2);
    });

    it('replaces existing conversations', () => {
      useStore.getState().addConversation(createConversation('1', 'Old'));
      useStore.getState().setConversations([createConversation('2', 'New')], createPagination(false, 1));
      expect(useStore.getState().conversations).toHaveLength(1);
      expect(useStore.getState().conversations[0].title).toBe('New');
    });

    it('updates pagination state', () => {
      const convs = [createConversation('1', 'Test')];
      useStore.getState().setConversations(convs, createPagination(true, 10));
      const pagination = useStore.getState().conversationsPagination;
      expect(pagination.hasMore).toBe(true);
      expect(pagination.totalCount).toBe(10);
      expect(pagination.nextCursor).toBe('next-cursor');
    });
  });

  describe('addConversation', () => {
    it('prepends conversation to list', () => {
      useStore.getState().addConversation(createConversation('1', 'First'));
      useStore.getState().addConversation(createConversation('2', 'Second'));

      const convs = useStore.getState().conversations;
      expect(convs).toHaveLength(2);
      expect(convs[0].id).toBe('2'); // Most recent first
      expect(convs[1].id).toBe('1');
    });
  });

  describe('updateConversation', () => {
    it('updates conversation in list', () => {
      useStore.getState().addConversation(createConversation('1', 'Original'));
      useStore.getState().updateConversation('1', { title: 'Updated' });

      expect(useStore.getState().conversations[0].title).toBe('Updated');
    });

    it('updates current conversation if matching', () => {
      const conv = createConversation('1', 'Original');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      useStore.getState().updateConversation('1', { title: 'Updated' });

      expect(useStore.getState().currentConversation?.title).toBe('Updated');
    });

    it('does not update current conversation if not matching', () => {
      useStore.getState().addConversation(createConversation('1', 'First'));
      useStore.getState().addConversation(createConversation('2', 'Second'));
      useStore.getState().setCurrentConversation(createConversation('2', 'Second'));

      useStore.getState().updateConversation('1', { title: 'Updated' });

      expect(useStore.getState().currentConversation?.title).toBe('Second');
    });

    it('preserves other properties', () => {
      const conv = createConversation('1', 'Test');
      useStore.getState().addConversation(conv);
      useStore.getState().updateConversation('1', { title: 'Updated' });

      expect(useStore.getState().conversations[0].model).toBe('gemini-3-flash-preview');
    });
  });

  describe('removeConversation', () => {
    it('removes conversation from list', () => {
      useStore.getState().addConversation(createConversation('1', 'First'));
      useStore.getState().addConversation(createConversation('2', 'Second'));

      useStore.getState().removeConversation('1');

      expect(useStore.getState().conversations).toHaveLength(1);
      expect(useStore.getState().conversations[0].id).toBe('2');
    });

    it('clears current conversation if removed', () => {
      const conv = createConversation('1', 'Test');
      useStore.getState().addConversation(conv);
      useStore.getState().setCurrentConversation(conv);

      useStore.getState().removeConversation('1');

      expect(useStore.getState().currentConversation).toBeNull();
    });

    it('keeps current conversation if different', () => {
      useStore.getState().addConversation(createConversation('1', 'First'));
      useStore.getState().addConversation(createConversation('2', 'Second'));
      useStore.getState().setCurrentConversation(createConversation('2', 'Second'));

      useStore.getState().removeConversation('1');

      expect(useStore.getState().currentConversation?.id).toBe('2');
    });
  });

  describe('setCurrentConversation', () => {
    it('sets current conversation', () => {
      const conv = createConversation('1', 'Test');
      useStore.getState().setCurrentConversation(conv);
      expect(useStore.getState().currentConversation).toEqual(conv);
    });

    it('clears current conversation when null', () => {
      useStore.getState().setCurrentConversation(createConversation('1', 'Test'));
      useStore.getState().setCurrentConversation(null);
      expect(useStore.getState().currentConversation).toBeNull();
    });
  });
});

describe('Store - Models', () => {
  beforeEach(resetStore);

  describe('setModels', () => {
    it('sets models and default model', () => {
      const models: Model[] = [
        { id: 'model-1', name: 'Model 1' },
        { id: 'model-2', name: 'Model 2' },
      ];
      useStore.getState().setModels(models, 'model-2');

      expect(useStore.getState().models).toEqual(models);
      expect(useStore.getState().defaultModel).toBe('model-2');
    });
  });
});

describe('Store - UI State', () => {
  beforeEach(resetStore);

  describe('setLoading', () => {
    it('sets loading state', () => {
      useStore.getState().setLoading(true);
      expect(useStore.getState().isLoading).toBe(true);

      useStore.getState().setLoading(false);
      expect(useStore.getState().isLoading).toBe(false);
    });
  });

  describe('toggleSidebar', () => {
    it('toggles sidebar open/closed', () => {
      expect(useStore.getState().isSidebarOpen).toBe(false);

      useStore.getState().toggleSidebar();
      expect(useStore.getState().isSidebarOpen).toBe(true);

      useStore.getState().toggleSidebar();
      expect(useStore.getState().isSidebarOpen).toBe(false);
    });
  });

  describe('closeSidebar', () => {
    it('closes sidebar', () => {
      useStore.getState().toggleSidebar(); // Open
      useStore.getState().closeSidebar();
      expect(useStore.getState().isSidebarOpen).toBe(false);
    });

    it('is idempotent', () => {
      useStore.getState().closeSidebar();
      useStore.getState().closeSidebar();
      expect(useStore.getState().isSidebarOpen).toBe(false);
    });
  });

  describe('setStreamingEnabled', () => {
    it('sets streaming enabled state', () => {
      useStore.getState().setStreamingEnabled(false);
      expect(useStore.getState().streamingEnabled).toBe(false);

      useStore.getState().setStreamingEnabled(true);
      expect(useStore.getState().streamingEnabled).toBe(true);
    });
  });

  describe('toggleForceTool', () => {
    it('adds tool when not present', () => {
      useStore.getState().toggleForceTool('web_search');
      expect(useStore.getState().forceTools).toContain('web_search');
    });

    it('removes tool when present', () => {
      useStore.getState().toggleForceTool('web_search');
      useStore.getState().toggleForceTool('web_search');
      expect(useStore.getState().forceTools).not.toContain('web_search');
    });

    it('handles multiple tools', () => {
      useStore.getState().toggleForceTool('web_search');
      useStore.getState().toggleForceTool('fetch_url');

      expect(useStore.getState().forceTools).toContain('web_search');
      expect(useStore.getState().forceTools).toContain('fetch_url');
      expect(useStore.getState().forceTools).toHaveLength(2);
    });
  });

  describe('clearForceTools', () => {
    it('clears all force tools', () => {
      useStore.getState().toggleForceTool('web_search');
      useStore.getState().toggleForceTool('fetch_url');
      useStore.getState().clearForceTools();

      expect(useStore.getState().forceTools).toHaveLength(0);
    });
  });
});

describe('Store - Files', () => {
  beforeEach(resetStore);

  const sampleFile: FileUpload = {
    name: 'test.png',
    type: 'image/png',
    data: 'base64data',
  };

  describe('addPendingFile', () => {
    it('adds file to pending list', () => {
      useStore.getState().addPendingFile(sampleFile);
      expect(useStore.getState().pendingFiles).toHaveLength(1);
      expect(useStore.getState().pendingFiles[0]).toEqual(sampleFile);
    });

    it('appends multiple files', () => {
      useStore.getState().addPendingFile(sampleFile);
      useStore.getState().addPendingFile({ ...sampleFile, name: 'test2.png' });
      expect(useStore.getState().pendingFiles).toHaveLength(2);
    });
  });

  describe('removePendingFile', () => {
    it('removes file at index', () => {
      useStore.getState().addPendingFile(sampleFile);
      useStore.getState().addPendingFile({ ...sampleFile, name: 'test2.png' });
      useStore.getState().removePendingFile(0);

      expect(useStore.getState().pendingFiles).toHaveLength(1);
      expect(useStore.getState().pendingFiles[0].name).toBe('test2.png');
    });
  });

  describe('clearPendingFiles', () => {
    it('clears all pending files', () => {
      useStore.getState().addPendingFile(sampleFile);
      useStore.getState().addPendingFile({ ...sampleFile, name: 'test2.png' });
      useStore.getState().clearPendingFiles();

      expect(useStore.getState().pendingFiles).toHaveLength(0);
    });
  });

  describe('setUploadConfig', () => {
    it('sets upload config', () => {
      const config = {
        maxFileSize: 10 * 1024 * 1024,
        maxFilesPerMessage: 5,
        allowedFileTypes: ['image/png'],
      };
      useStore.getState().setUploadConfig(config);
      expect(useStore.getState().uploadConfig).toEqual(config);
    });
  });
});

describe('Store - Version', () => {
  beforeEach(resetStore);

  describe('setAppVersion', () => {
    it('sets app version', () => {
      useStore.getState().setAppVersion('1.0.0');
      expect(useStore.getState().appVersion).toBe('1.0.0');
    });
  });

  describe('setNewVersionAvailable', () => {
    it('sets new version available flag', () => {
      useStore.getState().setNewVersionAvailable(true);
      expect(useStore.getState().newVersionAvailable).toBe(true);
    });
  });

  describe('dismissVersionBanner', () => {
    it('sets version banner dismissed', () => {
      useStore.getState().dismissVersionBanner();
      expect(useStore.getState().versionBannerDismissed).toBe(true);
    });
  });
});
