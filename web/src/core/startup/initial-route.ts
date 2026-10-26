/**
 * Opening the view the URL hash names when the app boots or the user signs in.
 */
import {
  isValidConversationId,
  parseHash,
  getSportsProgramFromHash,
  getLanguageProgramFromHash,
} from '../../router/deeplink';
import type { InitialRoute } from '../../router/deeplink';
import { navigateToAgents } from '../agents';
import { navigateToArchive } from '../archive';
import { loadDeepLinkedConversation } from '../conversation-deeplink';
import { navigateToStorage } from '../kv-store';
import { navigateToLanguage, navigateToLanguageProgram } from '../language';
import { navigateToPlanner } from '../planner';
import { navigateToSports, navigateToSportsProgram } from '../sports';
import { navigateToTrash } from '../trash';

/**
 * The initial route for the current URL hash (a sign-in after logout reads
 * it again: the user may have logged out and back in on a deep link).
 */
export function initialRouteFromHash(): InitialRoute {
  const route = parseHash();
  return {
    conversationId: route.type === 'conversation' ? route.conversationId ?? null : null,
    isPlanner: route.type === 'planner',
    isAgents: route.type === 'agents',
    isStorage: route.type === 'storage',
    isSports: route.type === 'sports',
    isLanguage: route.type === 'language',
    isArchive: route.type === 'archive',
    isTrash: route.type === 'trash',
  };
}

async function openSportsRoute(): Promise<void> {
  const sportsProgramId = getSportsProgramFromHash();
  if (sportsProgramId) {
    await navigateToSportsProgram(sportsProgramId);
  } else {
    await navigateToSports();
  }
}

async function openLanguageRoute(): Promise<void> {
  const languageProgramId = getLanguageProgramFromHash();
  if (languageProgramId) {
    await navigateToLanguageProgram(languageProgramId);
  } else {
    await navigateToLanguage();
  }
}

/**
 * Open the view the initial route names; the home route opens nothing.
 */
export async function openInitialRoute(initialRoute: InitialRoute | null | undefined): Promise<void> {
  if (!initialRoute) return;
  if (initialRoute.isPlanner) {
    await navigateToPlanner();
  } else if (initialRoute.isAgents) {
    await navigateToAgents();
  } else if (initialRoute.isStorage) {
    await navigateToStorage();
  } else if (initialRoute.isSports) {
    await openSportsRoute();
  } else if (initialRoute.isLanguage) {
    await openLanguageRoute();
  } else if (initialRoute.isArchive) {
    navigateToArchive();
  } else if (initialRoute.isTrash) {
    navigateToTrash();
  } else if (initialRoute.conversationId && isValidConversationId(initialRoute.conversationId)) {
    await loadDeepLinkedConversation(initialRoute.conversationId);
  }
}
