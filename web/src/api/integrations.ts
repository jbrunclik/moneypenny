/**
 * Integration APIs: Todoist, Google Calendar, Garmin Connect, Rouvy.
 */
import {
  type TodoistAuthUrl,
  type TodoistConnectResponse,
  type TodoistStatus,
  type CalendarAuthUrl,
  type CalendarConnectResponse,
  type CalendarListResponse,
  type CalendarStatus,
  type GarminConnectResponse,
  type GarminStatus,
  type SelectedCalendarsResponse,
} from '../types/api';
import { request, requestWithRetry } from './http';

// Todoist integration endpoints
export const todoist = {
  /**
   * Get the Todoist OAuth authorization URL.
   * Returns a URL to redirect the user to and a state token for CSRF protection.
   */
  async getAuthUrl(): Promise<TodoistAuthUrl> {
    return requestWithRetry<TodoistAuthUrl>('/auth/todoist/auth-url');
  },

  /**
   * Exchange Todoist OAuth code for access token and connect the account.
   * @param code - The authorization code from Todoist callback
   * @param state - The state token for CSRF validation (client should verify this)
   */
  async connect(code: string, state: string): Promise<TodoistConnectResponse> {
    return request<TodoistConnectResponse>('/auth/todoist/connect', {
      method: 'POST',
      body: JSON.stringify({ code, state }),
    });
  },

  /**
   * Disconnect the user's Todoist account.
   */
  async disconnect(): Promise<void> {
    await request<{ status: string }>('/auth/todoist/disconnect', {
      method: 'POST',
    });
  },

  /**
   * Get the current Todoist connection status.
   */
  async getStatus(): Promise<TodoistStatus> {
    return requestWithRetry<TodoistStatus>('/auth/todoist/status');
  },
};

// Google Calendar integration endpoints
export const calendar = {
  async getAuthUrl(): Promise<CalendarAuthUrl> {
    return requestWithRetry<CalendarAuthUrl>('/auth/calendar/auth-url');
  },

  async connect(code: string, state: string): Promise<CalendarConnectResponse> {
    return request<CalendarConnectResponse>('/auth/calendar/connect', {
      method: 'POST',
      body: JSON.stringify({ code, state }),
    });
  },

  async disconnect(): Promise<void> {
    await request<{ status: string }>('/auth/calendar/disconnect', {
      method: 'POST',
    });
  },

  async getStatus(): Promise<CalendarStatus> {
    return requestWithRetry<CalendarStatus>('/auth/calendar/status');
  },

  async listCalendars(): Promise<CalendarListResponse> {
    return requestWithRetry<CalendarListResponse>('/auth/calendar/calendars');
  },

  async getSelectedCalendars(): Promise<SelectedCalendarsResponse> {
    return requestWithRetry<SelectedCalendarsResponse>('/auth/calendar/selected-calendars');
  },

  async updateSelectedCalendars(calendarIds: string[]): Promise<SelectedCalendarsResponse> {
    return request<SelectedCalendarsResponse>('/auth/calendar/selected-calendars', {
      method: 'PUT',
      body: JSON.stringify({ calendar_ids: calendarIds }),
    });
  },
};

// Garmin Connect endpoints
export const garmin = {
  async connect(
    email: string,
    password: string,
  ): Promise<GarminConnectResponse> {
    return request<GarminConnectResponse>('/auth/garmin/connect', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  },

  async submitMfa(
    email: string,
    password: string,
    mfaCode: string,
  ): Promise<GarminConnectResponse> {
    return request<GarminConnectResponse>('/auth/garmin/mfa', {
      method: 'POST',
      body: JSON.stringify({ email, password, mfa_code: mfaCode }),
    });
  },

  async disconnect(): Promise<void> {
    await request<{ status: string }>('/auth/garmin/disconnect', {
      method: 'POST',
    });
  },

  async getStatus(): Promise<GarminStatus> {
    return requestWithRetry<GarminStatus>('/auth/garmin/status');
  },
};

// Rouvy endpoints (no MFA — Rouvy's login flow has none)
export interface RouvyStatus {
  connected: boolean;
  connected_at: string | null;
  needs_reconnect: boolean;
}

export const rouvy = {
  async connect(email: string, password: string): Promise<{ connected: boolean }> {
    return request<{ connected: boolean }>('/auth/rouvy/connect', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  },

  async disconnect(): Promise<void> {
    await request<{ status: string }>('/auth/rouvy/disconnect', {
      method: 'POST',
    });
  },

  async getStatus(): Promise<RouvyStatus> {
    return requestWithRetry<RouvyStatus>('/auth/rouvy/status');
  },
};
