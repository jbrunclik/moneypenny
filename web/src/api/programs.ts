/**
 * Program APIs: sports training and language learning.
 */
import {
  type SportsConversation,
  type SportsProgram,
  type SportsProgramsResponse,
  type QuickAction,
  type SportsResetResponse,
  type LanguageConversation,
  type LanguageProgram,
  type LanguageProgramsResponse,
  type LanguageResetResponse,
  type SetupReviewResponse,
  type SetupSuggestion,
} from '../types/api';
import { request, requestWithRetry } from './http';

// Sports endpoints
export const sports = {
  async getPrograms(): Promise<SportsProgram[]> {
    const data = await requestWithRetry<SportsProgramsResponse>('/api/sports/programs');
    return data.programs;
  },

  async createProgram(data: { name: string; emoji: string }): Promise<SportsProgram | undefined> {
    const response = await request<SportsProgramsResponse>('/api/sports/programs', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    return response.programs[0];
  },

  async deleteProgram(id: string): Promise<void> {
    await request<{ status: string }>(`/api/sports/programs/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    });
  },

  async getConversation(program: string): Promise<SportsConversation> {
    return requestWithRetry<SportsConversation>(`/api/sports/${encodeURIComponent(program)}/conversation`);
  },

  async reset(program: string): Promise<SportsResetResponse> {
    return request<SportsResetResponse>(`/api/sports/${encodeURIComponent(program)}/reset`, {
      method: 'POST',
    });
  },

  async updateQuickActions(programId: string, actions: QuickAction[]): Promise<SportsProgram> {
    const response = await request<SportsProgramsResponse>(
      `/api/sports/programs/${encodeURIComponent(programId)}/quick-actions`,
      { method: 'PUT', body: JSON.stringify({ quick_actions: actions }) }
    );
    const updated = response.programs[0];
    if (updated === undefined) throw new Error('Quick-action update returned no program');
    return updated;
  },
};

// Language Learning endpoints
export const language = {
  async getPrograms(): Promise<LanguageProgram[]> {
    const data = await requestWithRetry<LanguageProgramsResponse>('/api/language/programs');
    return data.programs;
  },

  async createProgram(data: { name: string; emoji: string }): Promise<LanguageProgram | undefined> {
    const response = await request<LanguageProgramsResponse>('/api/language/programs', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    return response.programs[0];
  },

  async deleteProgram(id: string): Promise<void> {
    await request<{ status: string }>(`/api/language/programs/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    });
  },

  async getConversation(program: string): Promise<LanguageConversation> {
    return requestWithRetry<LanguageConversation>(`/api/language/${encodeURIComponent(program)}/conversation`);
  },

  async reset(program: string): Promise<LanguageResetResponse> {
    return request<LanguageResetResponse>(`/api/language/${encodeURIComponent(program)}/reset`, {
      method: 'POST',
    });
  },

  async updateQuickActions(programId: string, actions: QuickAction[]): Promise<LanguageProgram> {
    const response = await request<LanguageProgramsResponse>(
      `/api/language/programs/${encodeURIComponent(programId)}/quick-actions`,
      { method: 'PUT', body: JSON.stringify({ quick_actions: actions }) }
    );
    const updated = response.programs[0];
    if (updated === undefined) throw new Error('Quick-action update returned no program');
    return updated;
  },
};

// A program's setup Review (quick actions + instructions), shared by both namespaces
export type ProgramNamespace = 'sports' | 'language';

function setupReviewUrl(ns: ProgramNamespace, programId: string, action = ''): string {
  return `/api/${ns}/programs/${encodeURIComponent(programId)}/setup-review${action}`;
}

function setupReviewClient(ns: ProgramNamespace) {
  return {
    async review(programId: string): Promise<SetupSuggestion[]> {
      const data = await request<SetupReviewResponse>(setupReviewUrl(ns, programId), { method: 'POST' });
      return data.suggestions;
    },

    /** Apply one accepted suggestion; resolves to the program's new quick actions. */
    async apply(programId: string, suggestion: SetupSuggestion): Promise<QuickAction[]> {
      const response = await request<SportsProgramsResponse | LanguageProgramsResponse>(
        setupReviewUrl(ns, programId, '/apply'),
        { method: 'POST', body: JSON.stringify({ change: suggestion.change, summary: suggestion.summary }) }
      );
      const updated = response.programs[0];
      if (updated === undefined) throw new Error('Setup change returned no program');
      return updated.quick_actions;
    },

    async reject(programId: string, suggestion: SetupSuggestion): Promise<void> {
      await request<unknown>(setupReviewUrl(ns, programId, '/reject'), {
        method: 'POST',
        body: JSON.stringify({ change: suggestion.change, summary: suggestion.summary }),
      });
    },
  };
}

export const sportsSetup = setupReviewClient('sports');
export const languageSetup = setupReviewClient('language');
