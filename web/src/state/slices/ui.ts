import type { FileUpload, Model, ThinkingState, UploadConfig } from '../../types/api';
import type { AppSlice } from '../store';

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
  /** Stop was sent to the server; the turn ends at its next checkpoint */
  stopping?: boolean;
}

export type ActiveView = 'chat' | 'planner' | 'agents' | 'storage' | 'sports' | 'language';

/** UI state that belongs to the signed-in user's session (wiped on logout). */
export interface UiSessionData {
  pendingModel: string | null; // Model selected when no conversation exists
  isLoading: boolean;
  forceTools: string[];
  anonymousModeByConversation: Map<string, boolean>; // Anonymous mode per conversation
  pendingAnonymousMode: boolean; // Anonymous mode when no conversation exists
  streamingConversationId: string | null; // Which conversation is currently streaming
  activeRequests: Map<string, ActiveRequestState>; // Active requests by conversation ID
  uploadProgress: number | null; // Upload progress 0-100, null when not uploading
  pendingFiles: FileUpload[];
  // Notifications (toast messages)
  notifications: Notification[];
}

export interface UiSlice extends UiSessionData {
  // Models
  models: Model[];
  defaultModel: string;

  // UI State
  isSidebarOpen: boolean;
  streamingEnabled: boolean;

  // File upload
  uploadConfig: UploadConfig;

  // Version tracking
  appVersion: string | null;
  newVersionAvailable: boolean;
  versionBannerDismissed: boolean;

  // Navigation state
  // navigationToken is incremented on each navigation to detect stale async operations
  // When an async operation completes, it compares its starting token to the current one
  // If they differ, the user navigated away and the operation should be cancelled
  navigationToken: number;

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

  // Actions - Navigation
  // Increment navigation token when starting a new navigation.
  // Returns the new token which should be stored and checked after async operations.
  // See docs/features/agents.md for details on the navigation race condition pattern.
  startNavigation: () => number;
  // Check if a navigation token is still valid (matches current token).
  // Returns true if the navigation should proceed, false if cancelled.
  isNavigationValid: (token: number) => boolean;

  // Actions - View switching
  // Atomically sets the active view, clearing all other view flags.
  // Prefer this over individual setIsXXXView calls to avoid forgetting to clear flags.
  setActiveView: (view: ActiveView) => void;
}

const DEFAULT_UPLOAD_CONFIG: UploadConfig = {
  maxFileSize: 20 * 1024 * 1024,
  maxVideoFileSize: 100 * 1024 * 1024,
  maxFilesPerMessage: 10,
  allowedFileTypes: [
    'image/png',
    'image/jpeg',
    'image/gif',
    'image/webp',
    'image/heic',
    'image/heif',
    'application/pdf',
    'text/plain',
    'text/markdown',
    'application/json',
    'text/csv',
    'video/mp4',
    'video/quicktime',
    'video/webm',
  ],
};

/**
 * Initial per-session UI state; also what logout resets to. Server config
 * (models, uploadConfig), app version state and UI preferences stay.
 */
export function initialUiSessionData(): UiSessionData {
  return {
    pendingModel: null,
    isLoading: false,
    forceTools: [],
    anonymousModeByConversation: new Map(),
    pendingAnonymousMode: false,
    streamingConversationId: null,
    activeRequests: new Map(),
    uploadProgress: null,
    pendingFiles: [],
    notifications: [],
  };
}

type UiSet = Parameters<AppSlice<UiSlice>>[0];
type UiGet = Parameters<AppSlice<UiSlice>>[1];

function conversationFlagActions(set: UiSet, get: UiGet) {
  return {
    setAnonymousMode: (convId: string, enabled: boolean) =>
      set((s) => {
        const newMap = new Map(s.anonymousModeByConversation);
        if (enabled) {
          newMap.set(convId, true);
        } else {
          newMap.delete(convId);
        }
        return { anonymousModeByConversation: newMap };
      }),
    getAnonymousMode: (convId: string) => get().anonymousModeByConversation.get(convId) ?? false,
    setPendingAnonymousMode: (enabled: boolean) => set({ pendingAnonymousMode: enabled }),
    setActiveRequest: (convId: string, state: ActiveRequestState) =>
      set((s) => {
        const newMap = new Map(s.activeRequests);
        newMap.set(convId, state);
        return { activeRequests: newMap };
      }),
    updateActiveRequestContent: (convId: string, content: string, thinkingState?: ThinkingState) =>
      set((s) => {
        const existing = s.activeRequests.get(convId);
        if (!existing) return s;
        const newMap = new Map(s.activeRequests);
        newMap.set(convId, { ...existing, content, thinkingState: thinkingState ?? existing.thinkingState });
        return { activeRequests: newMap };
      }),
    removeActiveRequest: (convId: string) =>
      set((s) => {
        const newMap = new Map(s.activeRequests);
        newMap.delete(convId);
        return { activeRequests: newMap };
      }),
    getActiveRequest: (convId: string) => get().activeRequests.get(convId),
  };
}

export const createUiSlice: AppSlice<UiSlice> = (set, get) => ({
  ...initialUiSessionData(),
  models: [],
  defaultModel: 'gemini-3.8-flash',
  isSidebarOpen: false,
  streamingEnabled: true,
  uploadConfig: DEFAULT_UPLOAD_CONFIG,
  appVersion: null,
  newVersionAvailable: false,
  versionBannerDismissed: false,
  // Navigation state - token for detecting stale async operations
  navigationToken: 0,

  // Model actions
  setModels: (models, defaultModel) => set({ models, defaultModel }),
  setPendingModel: (pendingModel) => set({ pendingModel }),

  // UI actions
  setLoading: (isLoading) => set({ isLoading }),
  toggleSidebar: () => set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),
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
  ...conversationFlagActions(set, get),
  setUploadProgress: (uploadProgress) => set({ uploadProgress }),

  // File actions
  addPendingFile: (file) => set((state) => ({ pendingFiles: [...state.pendingFiles, file] })),
  removePendingFile: (index) =>
    set((state) => ({ pendingFiles: state.pendingFiles.filter((_, i) => i !== index) })),
  clearPendingFiles: () => set({ pendingFiles: [] }),
  setUploadConfig: (uploadConfig) => set({ uploadConfig }),

  // Version actions
  setAppVersion: (appVersion) => set({ appVersion }),
  setNewVersionAvailable: (newVersionAvailable) => set({ newVersionAvailable }),
  dismissVersionBanner: () => set({ versionBannerDismissed: true }),

  // Notification actions
  addNotification: (notification) =>
    set((state) => ({ notifications: [...state.notifications, notification] })),
  dismissNotification: (id) =>
    set((state) => ({ notifications: state.notifications.filter((n) => n.id !== id) })),
  clearNotifications: () => set({ notifications: [] }),

  // Navigation actions - for race condition prevention
  // See docs/features/agents.md section "Routing Race Condition Prevention"
  startNavigation: () => {
    const newToken = get().navigationToken + 1;
    set({ navigationToken: newToken });
    return newToken;
  },
  isNavigationValid: (token) => get().navigationToken === token,

  // View switching
  setActiveView: (view) =>
    set({
      isPlannerView: view === 'planner',
      isAgentsView: view === 'agents',
      isStorageView: view === 'storage',
      isSportsView: view === 'sports',
      isLanguageView: view === 'language',
    }),
});
