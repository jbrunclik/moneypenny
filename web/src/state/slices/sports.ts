import type { SportsProgram } from '../../types/api';
import type { AppSlice } from '../store';

export interface SportsData {
  isSportsView: boolean;
  sportsPrograms: SportsProgram[] | null;
  sportsCurrentProgram: string | null;
  sportsProgramsLastFetch: number | null;
}

export interface SportsSlice extends SportsData {
  setSportsPrograms: (programs: SportsProgram[] | null) => void;
  setSportsCurrentProgram: (programId: string | null) => void;
  invalidateSportsCache: () => void;
  clearSportsState: () => void;
}

/** Initial sports state; also what logout and clearSportsState reset to. */
export function initialSportsData(): SportsData {
  return {
    isSportsView: false,
    sportsPrograms: null,
    sportsCurrentProgram: null,
    sportsProgramsLastFetch: null,
  };
}

export const createSportsSlice: AppSlice<SportsSlice> = (set) => ({
  ...initialSportsData(),

  setSportsPrograms: (sportsPrograms) =>
    set({ sportsPrograms, sportsProgramsLastFetch: sportsPrograms ? Date.now() : null }),
  setSportsCurrentProgram: (sportsCurrentProgram) => set({ sportsCurrentProgram }),
  invalidateSportsCache: () => set({ sportsProgramsLastFetch: null }),
  clearSportsState: () => set(initialSportsData()),
});
