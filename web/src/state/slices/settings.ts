import type {
  Calendar,
  CalendarStatus,
  GarminStatus,
  PushState,
  RouvyStatus,
  TodoistStatus,
  UserSettings,
} from '../../types/api';
import type { AppSlice } from '../store';

/** Each integration's connection status; null until the settings popup fetches it. */
interface IntegrationStatuses {
  todoist: TodoistStatus | null;
  calendar: CalendarStatus | null;
  garmin: GarminStatus | null;
  rouvy: RouvyStatus | null;
}

/** The Google calendars to choose from and the chosen ones. */
export interface CalendarChoice {
  calendars: Calendar[] | null;
  selectedIds: string[];
  loading: boolean;
  error: string | null;
}

/**
 * The settings popup's data: the user's server-side settings, the
 * integration statuses, the calendar choice, this device's push state and
 * whether Garmin waits for an MFA code.
 */
export interface SettingsData {
  userSettings: UserSettings | null;
  integrationStatuses: IntegrationStatuses;
  calendarChoice: CalendarChoice;
  pushState: PushState;
  garminMfaRequired: boolean;
}

export interface SettingsSlice extends SettingsData {
  setUserSettings: (settings: UserSettings) => void;
  /** Adopt a saved change (no-op before the first fetch). */
  patchUserSettings: (changes: Partial<UserSettings>) => void;
  setIntegrationStatus: <K extends keyof IntegrationStatuses>(name: K, status: IntegrationStatuses[K]) => void;
  updateCalendarChoice: (changes: Partial<CalendarChoice>) => void;
  setPushState: (pushState: PushState) => void;
  setGarminMfaRequired: (required: boolean) => void;
}

export function initialCalendarChoice(): CalendarChoice {
  return { calendars: null, selectedIds: ['primary'], loading: false, error: null };
}

/** Initial settings state; also what logout resets to. */
export function initialSettingsData(): SettingsData {
  return {
    userSettings: null,
    integrationStatuses: { todoist: null, calendar: null, garmin: null, rouvy: null },
    calendarChoice: initialCalendarChoice(),
    pushState: 'unsupported',
    garminMfaRequired: false,
  };
}

export const createSettingsSlice: AppSlice<SettingsSlice> = (set) => ({
  ...initialSettingsData(),

  setUserSettings: (userSettings) => set({ userSettings }),
  patchUserSettings: (changes) =>
    set((state) => (state.userSettings ? { userSettings: { ...state.userSettings, ...changes } } : {})),
  setIntegrationStatus: (name, status) =>
    set((state) => ({ integrationStatuses: { ...state.integrationStatuses, [name]: status } })),
  updateCalendarChoice: (changes) => set((state) => ({ calendarChoice: { ...state.calendarChoice, ...changes } })),
  setPushState: (pushState) => set({ pushState }),
  setGarminMfaRequired: (garminMfaRequired) => set({ garminMfaRequired }),
});
