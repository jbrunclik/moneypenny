import type { KVNamespacesResponse } from '../../types/api';
import type { AppSlice } from '../store';

export interface StorageData {
  isStorageView: boolean;
  storageData: KVNamespacesResponse | null;
  storageLastFetch: number | null;
}

export interface StorageSlice extends StorageData {
  setStorageData: (data: KVNamespacesResponse | null) => void;
  invalidateStorageCache: () => void;
  clearStorageState: () => void;
}

/** Initial storage (K/V) state; also what logout and clearStorageState reset to. */
export function initialStorageData(): StorageData {
  return {
    isStorageView: false,
    storageData: null,
    storageLastFetch: null,
  };
}

export const createStorageSlice: AppSlice<StorageSlice> = (set) => ({
  ...initialStorageData(),

  setStorageData: (storageData) =>
    set({ storageData, storageLastFetch: storageData ? Date.now() : null }),
  invalidateStorageCache: () => set({ storageLastFetch: null }),
  clearStorageState: () => set(initialStorageData()),
});
