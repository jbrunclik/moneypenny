import type { User } from '../../types/api';
import type { AppSlice } from '../store';
import { initialAgentsData } from './agents';
import { initialArchiveData } from './archive';
import { initialTrashData } from './trash';
import { initialConversationsData } from './conversations';
import { initialLanguageData } from './language';
import { initialMessagesData } from './messages';
import { initialPlannerData } from './planner';
import { initialSearchData } from './search';
import { initialSportsData } from './sports';
import { initialStorageData } from './storage';
import { initialUiSessionData } from './ui';

export interface AuthSlice {
  token: string | null;
  user: User | null;
  googleClientId: string | null;

  setToken: (token: string | null) => void;
  setUser: (user: User | null) => void;
  setGoogleClientId: (clientId: string) => void;
  logout: () => void;
}

export const createAuthSlice: AppSlice<AuthSlice> = (set) => ({
  token: null,
  user: null,
  googleClientId: null,

  setToken: (token) => set({ token }),
  setUser: (user) => set({ user }),
  setGoogleClientId: (googleClientId) => set({ googleClientId }),
  logout: () =>
    // Wipe ALL user data, not just auth: the next login on a shared
    // browser may be a different account, and stale Maps (messages,
    // pagination, active requests, drafts) would leak the previous
    // user's content. Server config (models, uploadConfig), app
    // version state and UI preferences (streamingEnabled) stay.
    set({
      token: null,
      user: null,
      ...initialConversationsData(),
      ...initialMessagesData(),
      ...initialUiSessionData(),
      ...initialSearchData(),
      ...initialPlannerData(),
      ...initialAgentsData(),
      ...initialArchiveData(),
      ...initialTrashData(),
      ...initialStorageData(),
      ...initialSportsData(),
      ...initialLanguageData(),
    }),
});
