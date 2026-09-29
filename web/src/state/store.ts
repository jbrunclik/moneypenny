import { create, type StateCreator } from 'zustand';
import { persist, subscribeWithSelector } from 'zustand/middleware';
import { createAgentsSlice, type AgentsSlice } from './slices/agents';
import { createArchiveSlice, type ArchiveSlice } from './slices/archive';
import { createAuthSlice, type AuthSlice } from './slices/auth';
import { createConversationsSlice, type ConversationsSlice } from './slices/conversations';
import { createLanguageSlice, type LanguageSlice } from './slices/language';
import { createMessagesSlice, type MessagesSlice } from './slices/messages';
import { createPlannerSlice, type PlannerSlice } from './slices/planner';
import { createSearchSlice, type SearchSlice } from './slices/search';
import { createSportsSlice, type SportsSlice } from './slices/sports';
import { createStorageSlice, type StorageSlice } from './slices/storage';
import { createUiSlice, type UiSlice } from './slices/ui';

/**
 * The whole app state: one Zustand store composed from per-domain slices
 * (see ./slices). Every slice sees the full AppState through set/get, so
 * cross-domain actions (logout, setActiveView) stay single atomic updates.
 */
export type AppState = AuthSlice &
  ConversationsSlice &
  MessagesSlice &
  UiSlice &
  SearchSlice &
  PlannerSlice &
  AgentsSlice &
  ArchiveSlice &
  StorageSlice &
  SportsSlice &
  LanguageSlice;

/** A slice creator contributing `T` to AppState under this store's middleware. */
export type AppSlice<T> = StateCreator<
  AppState,
  [['zustand/subscribeWithSelector', never], ['zustand/persist', unknown]],
  [],
  T
>;

export const useStore = create<AppState>()(
  subscribeWithSelector(
    persist(
      (...a) => ({
        ...createAuthSlice(...a),
        ...createConversationsSlice(...a),
        ...createMessagesSlice(...a),
        ...createUiSlice(...a),
        ...createSearchSlice(...a),
        ...createPlannerSlice(...a),
        ...createAgentsSlice(...a),
        ...createArchiveSlice(...a),
        ...createStorageSlice(...a),
        ...createSportsSlice(...a),
        ...createLanguageSlice(...a),
      }),
      {
        name: 'ai-chatbot-storage',
        partialize: (state) => ({
          token: state.token,
          streamingEnabled: state.streamingEnabled,
          // Persist composer drafts so they survive reloads
          conversationDrafts: state.conversationDrafts,
        }),
      }
    )
  )
);
