import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type {
  Conversation,
  DetailEvent,
  FileUpload,
  Model,
  UploadConfig,
  User,
} from '../types/api';

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

  // UI State
  isLoading: boolean;
  isSidebarOpen: boolean;
  streamingEnabled: boolean;
  forceTools: string[];

  // File upload
  pendingFiles: FileUpload[];
  uploadConfig: UploadConfig;

  // Message details (for lazy loading)
  expandedMessages: Set<string>;
  messageDetails: Map<string, DetailEvent[]>;

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

  // Actions - Message Details
  toggleMessageDetails: (messageId: string) => void;
  setMessageDetails: (messageId: string, details: DetailEvent[]) => void;
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
      isLoading: false,
      isSidebarOpen: false,
      streamingEnabled: true,
      forceTools: [],
      pendingFiles: [],
      uploadConfig: DEFAULT_UPLOAD_CONFIG,
      expandedMessages: new Set<string>(),
      messageDetails: new Map<string, DetailEvent[]>(),

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

      // Message details actions
      toggleMessageDetails: (messageId) =>
        set((state) => {
          const newExpanded = new Set(state.expandedMessages);
          if (newExpanded.has(messageId)) {
            newExpanded.delete(messageId);
          } else {
            newExpanded.add(messageId);
          }
          return { expandedMessages: newExpanded };
        }),
      setMessageDetails: (messageId, details) =>
        set((state) => {
          const newDetails = new Map(state.messageDetails);
          newDetails.set(messageId, details);
          
          // Limit cache size to 50 messages to prevent memory issues
          if (newDetails.size > 50) {
            // Remove oldest entry (first key in insertion order)
            const firstKey = newDetails.keys().next().value;
            if (firstKey) {
              newDetails.delete(firstKey);
            }
          }
          
          return { messageDetails: newDetails };
        }),
    }),
    {
      name: 'ai-chatbot-storage',
      partialize: (state) => ({
        token: state.token,
        streamingEnabled: state.streamingEnabled,
      }),
    }
  )
);