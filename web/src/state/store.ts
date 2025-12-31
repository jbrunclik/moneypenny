import { create } from 'zustand';
import { persist, subscribeWithSelector } from 'zustand/middleware';
import type {
  Conversation,
  FileUpload,
  Model,
  UploadConfig,
  User,
} from '../types/api';

/**
 * Notification for toast messages
 */
export interface Notification {
  id: string;
  type: 'success' | 'error' | 'warning' | 'info';
  message: string;
  action?: { label: string; onClick: () => void };
  duration?: number; // 0 for persistent
}

interface AppState {
  // Auth
  token: string | null;
  user: User | null;
  googleClientId: string | null;

  // Conversations
  conversations: Conversation[];
  currentConversation: Conversation | null;

  // Models
  models: Model[];
  defaultModel: string;
  pendingModel: string | null; // Model selected when no conversation exists

  // UI State
  isLoading: boolean;
  isSidebarOpen: boolean;
  streamingEnabled: boolean;
  forceTools: string[];

  // File upload
  pendingFiles: FileUpload[];
  uploadConfig: UploadConfig;

  // Version tracking
  appVersion: string | null;
  newVersionAvailable: boolean;
  versionBannerDismissed: boolean;

  // Notifications (toast messages)
  notifications: Notification[];

  // Draft message (for error recovery)
  draftMessage: string;
  draftFiles: FileUpload[];

  // Actions - Auth
  setToken: (token: string | null) => void;
  setUser: (user: User | null) => void;
  setGoogleClientId: (clientId: string) => void;
  logout: () => void;

  // Actions - Conversations
  setConversations: (conversations: Conversation[]) => void;
  addConversation: (conversation: Conversation) => void;
  updateConversation: (id: string, updates: Partial<Conversation>) => void;
  removeConversation: (id: string) => void;
  setCurrentConversation: (conversation: Conversation | null) => void;

  // Actions - Models
  setModels: (models: Model[], defaultModel: string) => void;
  setPendingModel: (model: string | null) => void;

  // Actions - UI
  setLoading: (loading: boolean) => void;
  toggleSidebar: () => void;
  closeSidebar: () => void;
  setStreamingEnabled: (enabled: boolean) => void;
  toggleForceTool: (tool: string) => void;
  clearForceTools: () => void;

  // Actions - Files
  addPendingFile: (file: FileUpload) => void;
  removePendingFile: (index: number) => void;
  clearPendingFiles: () => void;
  setUploadConfig: (config: UploadConfig) => void;

  // Actions - Version
  setAppVersion: (version: string | null) => void;
  setNewVersionAvailable: (available: boolean) => void;
  dismissVersionBanner: () => void;

  // Actions - Notifications
  addNotification: (notification: Notification) => void;
  dismissNotification: (id: string) => void;
  clearNotifications: () => void;

  // Actions - Draft
  setDraft: (message: string, files: FileUpload[]) => void;
  clearDraft: () => void;
}

const DEFAULT_UPLOAD_CONFIG: UploadConfig = {
  maxFileSize: 20 * 1024 * 1024,
  maxFilesPerMessage: 10,
  allowedFileTypes: [
    'image/png',
    'image/jpeg',
    'image/gif',
    'image/webp',
    'application/pdf',
    'text/plain',
    'text/markdown',
    'application/json',
    'text/csv',
  ],
};

export const useStore = create<AppState>()(
  subscribeWithSelector(
    persist(
    (set) => ({
      // Initial state
      token: null,
      user: null,
      googleClientId: null,
      conversations: [],
      currentConversation: null,
      models: [],
      defaultModel: 'gemini-3-flash-preview',
      pendingModel: null,
      isLoading: false,
      isSidebarOpen: false,
      streamingEnabled: true,
      forceTools: [],
      pendingFiles: [],
      uploadConfig: DEFAULT_UPLOAD_CONFIG,
      appVersion: null,
      newVersionAvailable: false,
      versionBannerDismissed: false,
      notifications: [],
      draftMessage: '',
      draftFiles: [],

      // Auth actions
      setToken: (token) => set({ token }),
      setUser: (user) => set({ user }),
      setGoogleClientId: (googleClientId) => set({ googleClientId }),
      logout: () =>
        set({
          token: null,
          user: null,
          currentConversation: null,
        }),

      // Conversation actions
      setConversations: (conversations) => set({ conversations }),
      addConversation: (conversation) =>
        set((state) => ({
          conversations: [conversation, ...state.conversations],
        })),
      updateConversation: (id, updates) =>
        set((state) => ({
          conversations: state.conversations.map((c) =>
            c.id === id ? { ...c, ...updates } : c
          ),
          currentConversation:
            state.currentConversation?.id === id
              ? { ...state.currentConversation, ...updates }
              : state.currentConversation,
        })),
      removeConversation: (id) =>
        set((state) => ({
          conversations: state.conversations.filter((c) => c.id !== id),
          currentConversation:
            state.currentConversation?.id === id
              ? null
              : state.currentConversation,
        })),
      setCurrentConversation: (currentConversation) =>
        set({ currentConversation }),

      // Model actions
      setModels: (models, defaultModel) => set({ models, defaultModel }),
      setPendingModel: (pendingModel) => set({ pendingModel }),

      // UI actions
      setLoading: (isLoading) => set({ isLoading }),
      toggleSidebar: () =>
        set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),
      closeSidebar: () => set({ isSidebarOpen: false }),
      setStreamingEnabled: (streamingEnabled) => set({ streamingEnabled }),
      toggleForceTool: (tool) =>
        set((state) => ({
          forceTools: state.forceTools.includes(tool)
            ? state.forceTools.filter((t) => t !== tool)
            : [...state.forceTools, tool],
        })),
      clearForceTools: () => set({ forceTools: [] }),

      // File actions
      addPendingFile: (file) =>
        set((state) => ({
          pendingFiles: [...state.pendingFiles, file],
        })),
      removePendingFile: (index) =>
        set((state) => ({
          pendingFiles: state.pendingFiles.filter((_, i) => i !== index),
        })),
      clearPendingFiles: () => set({ pendingFiles: [] }),
      setUploadConfig: (uploadConfig) => set({ uploadConfig }),

      // Version actions
      setAppVersion: (appVersion) => set({ appVersion }),
      setNewVersionAvailable: (newVersionAvailable) => set({ newVersionAvailable }),
      dismissVersionBanner: () => set({ versionBannerDismissed: true }),

      // Notification actions
      addNotification: (notification) =>
        set((state) => ({
          notifications: [...state.notifications, notification],
        })),
      dismissNotification: (id) =>
        set((state) => ({
          notifications: state.notifications.filter((n) => n.id !== id),
        })),
      clearNotifications: () => set({ notifications: [] }),

      // Draft actions (for error recovery)
      setDraft: (draftMessage, draftFiles) => set({ draftMessage, draftFiles }),
      clearDraft: () => set({ draftMessage: '', draftFiles: [] }),
    }),
    {
      name: 'ai-chatbot-storage',
      partialize: (state) => ({
        token: state.token,
        streamingEnabled: state.streamingEnabled,
        // Persist draft for crash recovery
        draftMessage: state.draftMessage,
        draftFiles: state.draftFiles,
      }),
    }
    )
  )
);