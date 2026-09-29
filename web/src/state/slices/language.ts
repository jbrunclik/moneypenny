import type { LanguageProgram } from '../../types/api';
import type { AppSlice } from '../store';

export interface LanguageData {
  isLanguageView: boolean;
  languagePrograms: LanguageProgram[] | null;
  languageCurrentProgram: string | null;
  languageProgramsLastFetch: number | null;
}

export interface LanguageSlice extends LanguageData {
  setLanguagePrograms: (programs: LanguageProgram[] | null) => void;
  setLanguageCurrentProgram: (programId: string | null) => void;
  invalidateLanguageCache: () => void;
  clearLanguageState: () => void;
}

/** Initial language-learning state; also what logout and clearLanguageState reset to. */
export function initialLanguageData(): LanguageData {
  return {
    isLanguageView: false,
    languagePrograms: null,
    languageCurrentProgram: null,
    languageProgramsLastFetch: null,
  };
}

export const createLanguageSlice: AppSlice<LanguageSlice> = (set) => ({
  ...initialLanguageData(),

  setLanguagePrograms: (languagePrograms) =>
    set({ languagePrograms, languageProgramsLastFetch: languagePrograms ? Date.now() : null }),
  setLanguageCurrentProgram: (languageCurrentProgram) => set({ languageCurrentProgram }),
  invalidateLanguageCache: () => set({ languageProgramsLastFetch: null }),
  clearLanguageState: () => set(initialLanguageData()),
});
