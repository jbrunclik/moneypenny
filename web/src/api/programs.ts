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
} from '../types/api';
import { request, requestWithRetry } from './http';

// Sports endpoints
export const sports = {
  async getPrograms(): Promise<SportsProgram[]> {
    const data = await requestWithRetry<SportsProgramsResponse>('/api/sports/programs');
    return data.programs;
  },

  async createProgram(data: { name: string; emoji: string }): Promise<SportsProgram> {
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
    return response.programs[0];
  },
};

// Language Learning endpoints
export const language = {
  async getPrograms(): Promise<LanguageProgram[]> {
    const data = await requestWithRetry<LanguageProgramsResponse>('/api/language/programs');
    return data.programs;
  },

  async createProgram(data: { name: string; emoji: string }): Promise<LanguageProgram> {
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
    return response.programs[0];
  },
};
