import { create } from 'zustand';
import { persist, subscribeWithSelector } from 'zustand/middleware';
import type {
  Agent,
  CommandCenterResponse,
  Conversation,
  ConversationsPagination,
  FileUpload,
  Message,
  MessagesPagination,
  Model,
  PlannerConversation,
  PlannerDashboard,
  SearchResult,
  UploadConfig,
  User,
  ThinkingState,
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

/**
 * Active request state for a conversation
 * Used to restore UI when switching back to a conversation with an active request
 */
export interface ActiveRequestState {
  conversationId: string;
  type: 'stream' | 'batch';
  // Streaming-specific state
  content?: string;
  thinkingState?: ThinkingState;
}

/**
 * Pagination state for conversations list
 */
export interface ConversationsPaginationState {
  nextCursor: string | null;
  hasMore: boolean;
  totalCount: number;
  isLoadingMore: boolean;
}

/**
 * Pagination state for messages in a conversation
 */
export interface MessagesPaginationState {
  olderCursor: string | null;
  newerCursor: string | null;
  hasOlder: boolean;
  hasNewer: boolean;
  totalCount: number;
  isLoadingOlder: boolean;
  isLoadingNewer: boolean;
}

interface AppState {
  // Auth
  token: string | null;
  user: User | null;
  googleClientId: string | null;

  // Conversations
  conversations: Conversation[];
  currentConversation: Conversation | null;
  conversationsPagination: ConversationsPaginationState;

  // Messages (per conversation)
  messages: Map<string, Message[]>;
  messagesPagination: Map<string, MessagesPaginationState>;

  // Models
  models: Model[];
  defaultModel: string;
  pendingModel: string | null; // Model selected when no conversation exists

  // UI State
  isLoading: boolean;
  isSidebarOpen: boolean;
  streamingEnabled: boolean;
  forceTools: string[];
  anonymousModeByConversation: Map<string, boolean>; // Anonymous mode per conversation
  pendingAnonymousMode: boolean; // Anonymous mode when no conversation exists
  streamingConversationId: string | null; // Which conversation is currently streaming
  activeRequests: Map<string, ActiveRequestState>; // Active requests by conversation ID
  uploadProgress: number | null; // Upload progress 0-100, null when not uploading

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

  // Search state
  searchQuery: string;
  searchResults: SearchResult[];
  searchTotal: number;
  isSearching: boolean;
  isSearchActive: boolean; // True when search UI is shown (even with empty query)
  viewedSearchResultId: number | null; // Index of currently viewed search result (unique per result list)

  // Navigation state
  // navigationToken is incremented on each navigation to detect stale async operations
  // When an async operation completes, it compares its starting token to the current one
  // If they differ, the user navigated away and the operation should be cancelled
  navigationToken: number;

  // Planner state
  plannerDashboard: PlannerDashboard | null;
  plannerConversation: PlannerConversation | null;
  plannerDashboardLastFetch: number | null; // Timestamp for cache invalidation
  isPlannerView: boolean;

  // Agents state
  agents: Agent[];
  commandCenterData: CommandCenterResponse | null;
  commandCenterLastFetch: number | null; // Timestamp for cache invalidation
  isAgentsView: boolean;

  // Actions - Auth
  setToken: (token: string | null) => void;
  setUser: (user: User | null) => void;
  setGoogleClientId: (clientId: string) => void;
  logout: () => void;

  // Actions - Conversations
  setConversations: (conversations: Conversation[], pagination: ConversationsPagination) => void;
  appendConversations: (conversations: Conversation[], pagination: ConversationsPagination) => void;
  addConversation: (conversation: Conversation) => void;
  updateConversation: (id: string, updates: Partial<Conversation>) => void;
  removeConversation: (id: string) => void;
  setCurrentConversation: (conversation: Conversation | null) => void;
  setLoadingMoreConversations: (loading: boolean) => void;

  // Actions - Messages
  setMessages: (convId: string, messages: Message[], pagination: MessagesPagination) => void;
  prependMessages: (convId: string, messages: Message[], pagination: MessagesPagination) => void;
  appendMessages: (convId: string, messages: Message[], pagination: MessagesPagination) => void;
  appendMessage: (convId: string, message: Message) => void;
  clearMessages: (convId: string) => void;
  setLoadingOlderMessages: (convId: string, loading: boolean) => void;
  setLoadingNewerMessages: (convId: string, loading: boolean) => void;
  getMessages: (convId: string) => Message[];
  getMessagesPagination: (convId: string) => MessagesPaginationState | undefined;

  // Actions - Models
  setModels: (models: Model[], defaultModel: string) => void;
  setPendingModel: (model: string | null) => void;

  // Actions - UI
  setLoading: (loading: boolean) => void;
  toggleSidebar: () => void;
  closeSidebar: () => void;
  setStreamingEnabled: (enabled: boolean) => void;
  setStreamingConversation: (convId: string | null) => void;
  toggleForceTool: (tool: string) => void;
  clearForceTools: () => void;
  setAnonymousMode: (convId: string, enabled: boolean) => void;
  getAnonymousMode: (convId: string) => boolean;
  setPendingAnonymousMode: (enabled: boolean) => void;
  setActiveRequest: (convId: string, state: ActiveRequestState) => void;
  updateActiveRequestContent: (convId: string, content: string, thinkingState?: ThinkingState) => void;
  removeActiveRequest: (convId: string) => void;
  getActiveRequest: (convId: string) => ActiveRequestState | undefined;
  setUploadProgress: (progress: number | null) => void;

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

  // Actions - Search
  setSearchQuery: (query: string) => void;
  setSearchResults: (results: SearchResult[], total: number) => void;
  setIsSearching: (searching: boolean) => void;
  activateSearch: () => void;
  deactivateSearch: () => void;
  clearSearch: () => void;
  setViewedSearchResult: (resultIndex: number | null) => void;

  // Actions - Navigation
  // Increment navigation token when starting a new navigation.
  // Returns the new token which should be stored and checked after async operations.
  // See docs/features/agents.md for details on the navigation race condition pattern.
  startNavigation: () => number;
  // Check if a navigation token is still valid (matches current token).
  // Returns true if the navigation should proceed, false if cancelled.
  isNavigationValid: (token: number) => boolean;

  // Actions - Planner
  setPlannerDashboard: (dashboard: PlannerDashboard | null) => void;
  setPlannerConversation: (conversation: PlannerConversation | null) => void;
  setIsPlannerView: (active: boolean) => void;
  invalidatePlannerCache: () => void;
  clearPlannerState: () => void;

  // Actions - Agents
  setAgents: (agents: Agent[]) => void;
  addAgent: (agent: Agent) => void;
  updateAgent: (id: string, updates: Partial<Agent>) => void;
  removeAgent: (id: string) => void;
  setCommandCenterData: (data: CommandCenterResponse | null) => void;
  setIsAgentsView: (active: boolean) => void;
  invalidateCommandCenterCache: () => void;
  clearAgentsState: () => void;
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
    (set, get) => ({
      // Initial state
      token: null,
      user: null,
      googleClientId: null,
      conversations: [],
      currentConversation: null,
      conversationsPagination: {
        nextCursor: null,
        hasMore: false,
        totalCount: 0,
        isLoadingMore: false,
      },
      messages: new Map(),
      messagesPagination: new Map(),
      models: [],
      defaultModel: 'gemini-3-flash-preview',
      pendingModel: null,
      isLoading: false,
      isSidebarOpen: false,
      streamingEnabled: true,
      forceTools: [],
      anonymousModeByConversation: new Map(),
      pendingAnonymousMode: false,
      streamingConversationId: null,
      activeRequests: new Map(),
      uploadProgress: null,
      pendingFiles: [],
      uploadConfig: DEFAULT_UPLOAD_CONFIG,
      appVersion: null,
      newVersionAvailable: false,
      versionBannerDismissed: false,
      notifications: [],
      draftMessage: '',
      draftFiles: [],
      searchQuery: '',
      searchResults: [],
      searchTotal: 0,
      isSearching: false,
      isSearchActive: false,
      viewedSearchResultId: null,

      // Navigation state - token for detecting stale async operations
      navigationToken: 0,

      // Planner state
      plannerDashboard: null,
      plannerConversation: null,
      plannerDashboardLastFetch: null,
      isPlannerView: false,

      // Agents state
      agents: [],
      commandCenterData: null,
      commandCenterLastFetch: null,
      isAgentsView: false,

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
      setConversations: (conversations, pagination) =>
        set({
          conversations,
          conversationsPagination: {
            nextCursor: pagination.next_cursor,
            hasMore: pagination.has_more,
            totalCount: pagination.total_count,
            isLoadingMore: false,
          },
        }),
      appendConversations: (newConversations, pagination) =>
        set((state) => {
          // Deduplicate: filter out conversations already in the store
          const existingIds = new Set(state.conversations.map((c) => c.id));
          const filtered = newConversations.filter((c) => !existingIds.has(c.id));

          return {
            conversations: [...state.conversations, ...filtered],
            conversationsPagination: {
              nextCursor: pagination.next_cursor,
              hasMore: pagination.has_more,
              totalCount: pagination.total_count,
              isLoadingMore: false,
            },
          };
        }),
      addConversation: (conversation) =>
        set((state) => {
          // Idempotent: If conversation already exists, update it instead of adding duplicate
          const existingIndex = state.conversations.findIndex((c) => c.id === conversation.id);
          if (existingIndex !== -1) {
            // Merge with existing, preserving unreadCount if not provided in new data
            const existing = state.conversations[existingIndex];
            const merged = {
              ...existing,
              ...conversation,
              // Preserve unreadCount if the new conversation doesn't specify it
              unreadCount: conversation.unreadCount ?? existing.unreadCount,
            };
            const newConvs = [...state.conversations];
            newConvs[existingIndex] = merged;
            return {
              conversations: newConvs,
              conversationsPagination: state.conversationsPagination, // Don't increment count
            };
          }

          // Insert conversation at correct sorted position (by updated_at DESC)
          // This ensures conversations discovered via sync appear in correct order
          // For temp conversations (newly created), always prepend to ensure they appear at top
          // For other conversations, use <= so that conversations with same timestamp are prepended (newer first)
          const isTempConversation = conversation.id.startsWith('temp-');
          const newConvs = [...state.conversations];

          if (isTempConversation) {
            // Newly created conversations should always be at the top
            newConvs.unshift(conversation);
          } else {
            // For conversations from sync, insert at correct sorted position
            // Use <= so that conversations with same timestamp are prepended (newer first)
            const insertIndex = newConvs.findIndex(
              (c) => c.updated_at <= conversation.updated_at
            );
            if (insertIndex === -1) {
              // No conversation is older or equal, append at end
              newConvs.push(conversation);
            } else {
              // Insert before the first older-or-equal conversation
              newConvs.splice(insertIndex, 0, conversation);
            }
          }

          return {
            conversations: newConvs,
            conversationsPagination: {
              ...state.conversationsPagination,
              totalCount: state.conversationsPagination.totalCount + 1,
            },
          };
        }),
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
          conversationsPagination: {
            ...state.conversationsPagination,
            totalCount: Math.max(0, state.conversationsPagination.totalCount - 1),
          },
        })),
      setCurrentConversation: (currentConversation) =>
        set({ currentConversation }),
      setLoadingMoreConversations: (loading) =>
        set((state) => ({
          conversationsPagination: {
            ...state.conversationsPagination,
            isLoadingMore: loading,
          },
        })),

      // Message actions
      setMessages: (convId, messages, pagination) =>
        set((state) => {
          const newMessages = new Map(state.messages);
          newMessages.set(convId, messages);
          const newPagination = new Map(state.messagesPagination);
          newPagination.set(convId, {
            olderCursor: pagination.older_cursor,
            newerCursor: pagination.newer_cursor,
            hasOlder: pagination.has_older,
            hasNewer: pagination.has_newer,
            totalCount: pagination.total_count,
            isLoadingOlder: false,
            isLoadingNewer: false,
          });
          return { messages: newMessages, messagesPagination: newPagination };
        }),
      prependMessages: (convId, newMsgs, pagination) =>
        set((state) => {
          const existing = state.messages.get(convId) || [];
          const newMessages = new Map(state.messages);
          newMessages.set(convId, [...newMsgs, ...existing]);
          const newPagination = new Map(state.messagesPagination);
          newPagination.set(convId, {
            olderCursor: pagination.older_cursor,
            newerCursor: pagination.newer_cursor,
            hasOlder: pagination.has_older,
            hasNewer: pagination.has_newer,
            totalCount: pagination.total_count,
            isLoadingOlder: false,
            isLoadingNewer: false,
          });
          return { messages: newMessages, messagesPagination: newPagination };
        }),
      appendMessages: (convId, newMsgs, pagination) =>
        set((state) => {
          const existing = state.messages.get(convId) || [];
          const newMessages = new Map(state.messages);
          newMessages.set(convId, [...existing, ...newMsgs]);
          const newPagination = new Map(state.messagesPagination);
          newPagination.set(convId, {
            olderCursor: pagination.older_cursor,
            newerCursor: pagination.newer_cursor,
            hasOlder: pagination.has_older,
            hasNewer: pagination.has_newer,
            totalCount: pagination.total_count,
            isLoadingOlder: false,
            isLoadingNewer: false,
          });
          return { messages: newMessages, messagesPagination: newPagination };
        }),
      appendMessage: (convId, message) =>
        set((state) => {
          const existing = state.messages.get(convId) || [];
          const newMessages = new Map(state.messages);
          newMessages.set(convId, [...existing, message]);
          // Update total count in pagination
          const pag = state.messagesPagination.get(convId);
          if (pag) {
            const newPagination = new Map(state.messagesPagination);
            newPagination.set(convId, { ...pag, totalCount: pag.totalCount + 1 });
            return { messages: newMessages, messagesPagination: newPagination };
          }
          return { messages: newMessages };
        }),
      clearMessages: (convId) =>
        set((state) => {
          const newMessages = new Map(state.messages);
          newMessages.delete(convId);
          const newPagination = new Map(state.messagesPagination);
          newPagination.delete(convId);
          return { messages: newMessages, messagesPagination: newPagination };
        }),
      setLoadingOlderMessages: (convId, loading) =>
        set((state) => {
          const pag = state.messagesPagination.get(convId);
          if (!pag) return state;
          const newPagination = new Map(state.messagesPagination);
          newPagination.set(convId, { ...pag, isLoadingOlder: loading });
          return { messagesPagination: newPagination };
        }),
      setLoadingNewerMessages: (convId, loading) =>
        set((state) => {
          const pag = state.messagesPagination.get(convId);
          if (!pag) return state;
          const newPagination = new Map(state.messagesPagination);
          newPagination.set(convId, { ...pag, isLoadingNewer: loading });
          return { messagesPagination: newPagination };
        }),
      getMessages: (convId) => get().messages.get(convId) || [],
      getMessagesPagination: (convId) => get().messagesPagination.get(convId),

      // Model actions
      setModels: (models, defaultModel) => set({ models, defaultModel }),
      setPendingModel: (pendingModel) => set({ pendingModel }),

      // UI actions
      setLoading: (isLoading) => set({ isLoading }),
      toggleSidebar: () =>
        set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),
      closeSidebar: () => set({ isSidebarOpen: false }),
      setStreamingEnabled: (streamingEnabled) => set({ streamingEnabled }),
      setStreamingConversation: (streamingConversationId) => set({ streamingConversationId }),
      toggleForceTool: (tool) =>
        set((state) => ({
          forceTools: state.forceTools.includes(tool)
            ? state.forceTools.filter((t) => t !== tool)
            : [...state.forceTools, tool],
        })),
      clearForceTools: () => set({ forceTools: [] }),
      setAnonymousMode: (convId, enabled) =>
        set((s) => {
          const newMap = new Map(s.anonymousModeByConversation);
          if (enabled) {
            newMap.set(convId, true);
          } else {
            newMap.delete(convId);
          }
          return { anonymousModeByConversation: newMap };
        }),
      getAnonymousMode: (convId) => get().anonymousModeByConversation.get(convId) ?? false,
      setPendingAnonymousMode: (enabled) => set({ pendingAnonymousMode: enabled }),
      setActiveRequest: (convId, state) =>
        set((s) => {
          const newMap = new Map(s.activeRequests);
          newMap.set(convId, state);
          return { activeRequests: newMap };
        }),
      updateActiveRequestContent: (convId, content, thinkingState) =>
        set((s) => {
          const existing = s.activeRequests.get(convId);
          if (!existing) return s;
          const newMap = new Map(s.activeRequests);
          newMap.set(convId, { ...existing, content, thinkingState: thinkingState ?? existing.thinkingState });
          return { activeRequests: newMap };
        }),
      removeActiveRequest: (convId) =>
        set((s) => {
          const newMap = new Map(s.activeRequests);
          newMap.delete(convId);
          return { activeRequests: newMap };
        }),
      getActiveRequest: (convId) => get().activeRequests.get(convId),
      setUploadProgress: (uploadProgress) => set({ uploadProgress }),

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

      // Search actions
      setSearchQuery: (searchQuery) => set({ searchQuery }),
      setSearchResults: (searchResults, searchTotal) => set({ searchResults, searchTotal }),
      setIsSearching: (isSearching) => set({ isSearching }),
      activateSearch: () => set({ isSearchActive: true }),
      deactivateSearch: () => set({ isSearchActive: false, searchQuery: '', searchResults: [], searchTotal: 0, viewedSearchResultId: null }),
      clearSearch: () => set({ searchQuery: '', searchResults: [], searchTotal: 0, isSearching: false, isSearchActive: false, viewedSearchResultId: null }),
      setViewedSearchResult: (viewedSearchResultId) => set({ viewedSearchResultId }),

      // Navigation actions - for race condition prevention
      // See docs/features/agents.md section "Routing Race Condition Prevention"
      startNavigation: () => {
        const newToken = get().navigationToken + 1;
        set({ navigationToken: newToken });
        return newToken;
      },
      isNavigationValid: (token) => get().navigationToken === token,

      // Planner actions
      setPlannerDashboard: (plannerDashboard) =>
        set({ plannerDashboard, plannerDashboardLastFetch: plannerDashboard ? Date.now() : null }),
      setPlannerConversation: (plannerConversation) => set({ plannerConversation }),
      setIsPlannerView: (isPlannerView) => set({ isPlannerView }),
      invalidatePlannerCache: () => set({ plannerDashboardLastFetch: null }),
      clearPlannerState: () =>
        set({
          plannerDashboard: null,
          plannerConversation: null,
          plannerDashboardLastFetch: null,
          isPlannerView: false,
        }),

      // Agents actions
      setAgents: (agents) => set({ agents }),
      addAgent: (agent) =>
        set((state) => ({
          agents: [agent, ...state.agents],
        })),
      updateAgent: (id, updates) =>
        set((state) => ({
          agents: state.agents.map((a) =>
            a.id === id ? { ...a, ...updates } : a
          ),
        })),
      removeAgent: (id) =>
        set((state) => ({
          agents: state.agents.filter((a) => a.id !== id),
        })),
      setCommandCenterData: (commandCenterData) =>
        set({ commandCenterData, commandCenterLastFetch: commandCenterData ? Date.now() : null }),
      setIsAgentsView: (isAgentsView) => set({ isAgentsView }),
      invalidateCommandCenterCache: () => set({ commandCenterLastFetch: null }),
      clearAgentsState: () =>
        set({
          agents: [],
          commandCenterData: null,
          commandCenterLastFetch: null,
          isAgentsView: false,
        }),
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