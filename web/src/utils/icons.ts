// SVG icons used throughout the app

/**
 * AI assistant avatar (robot image)
 */
export const AI_AVATAR = `<img src="/static/avatar.png" alt="AI" class="ai-avatar-img">`;

/**
 * Get SVG icon for file type
 */
export function getFileIcon(mimeType: string): string {
  if (mimeType.startsWith('image/')) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
      <circle cx="8.5" cy="8.5" r="1.5"/>
      <polyline points="21,15 16,10 5,21"/>
    </svg>`;
  }
  if (mimeType === 'application/pdf') {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
      <polyline points="14,2 14,8 20,8"/>
      <path d="M9 15h6"/>
      <path d="M9 11h6"/>
    </svg>`;
  }
  if (mimeType.startsWith('text/')) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
      <polyline points="14,2 14,8 20,8"/>
      <line x1="16" y1="13" x2="8" y2="13"/>
      <line x1="16" y1="17" x2="8" y2="17"/>
    </svg>`;
  }
  // Generic file icon
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
    <polyline points="14,2 14,8 20,8"/>
  </svg>`;
}

/**
 * Close icon (X)
 */
export const CLOSE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <line x1="18" y1="6" x2="6" y2="18"/>
  <line x1="6" y1="6" x2="18" y2="18"/>
</svg>`;

/**
 * Trash/delete icon
 */
export const DELETE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
  <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
</svg>`;

/**
 * Edit/pencil icon (for rename)
 */
export const EDIT_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
</svg>`;

/**
 * Download icon
 */
export const DOWNLOAD_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
  <polyline points="7,10 12,15 17,10"/>
  <line x1="12" y1="15" x2="12" y2="3"/>
</svg>`;

/**
 * Logout icon
 */
export const LOGOUT_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
  <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/>
  <polyline points="16,17 21,12 16,7"/>
  <line x1="21" y1="12" x2="9" y2="12"/>
</svg>`;

/**
 * Send icon (paper plane)
 */
export const SEND_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <line x1="22" y1="2" x2="11" y2="13"/>
  <polygon points="22 2 15 22 11 13 2 9 22 2"/>
</svg>`;

/**
 * Attach/paperclip icon
 */
export const ATTACH_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
</svg>`;

/**
 * Copy icon (clipboard)
 */
export const COPY_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
  <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
</svg>`;

/**
 * Check/success icon
 */
export const CHECK_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="20 6 9 17 4 12"/>
</svg>`;

/**
 * Checklist/tasks icon (for Todoist)
 */
export const CHECKLIST_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <line x1="10" y1="6" x2="21" y2="6"/>
  <line x1="10" y1="12" x2="21" y2="12"/>
  <line x1="10" y1="18" x2="21" y2="18"/>
  <polyline points="3 6 4 7 6 5"/>
  <polyline points="3 12 4 13 6 11"/>
  <polyline points="3 18 4 19 6 17"/>
</svg>`;

export const CALENDAR_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
  <line x1="16" y1="2" x2="16" y2="6"/>
  <line x1="8" y1="2" x2="8" y2="6"/>
  <line x1="3" y1="10" x2="21" y2="10"/>
</svg>`;

/**
 * Map pin/location icon
 */
export const MAP_PIN_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>
  <circle cx="12" cy="10" r="3"/>
</svg>`;

/**
 * Clock icon
 */
export const CLOCK_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="10"/>
  <polyline points="12 6 12 12 16 14"/>
</svg>`;

/**
 * History icon (clock with rotate arrow)
 */
export const HISTORY_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
  <path d="M3 3v5h5"/>
  <path d="M12 7v5l4 2"/>
</svg>`;

/**
 * Sunrise icon (for tomorrow/new day)
 */
export const SUNRISE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 2v8"/>
  <path d="m4.93 10.93 1.41 1.41"/>
  <path d="M2 18h2"/>
  <path d="M20 18h2"/>
  <path d="m19.07 10.93-1.41 1.41"/>
  <path d="M22 22H2"/>
  <path d="m8 6 4-4 4 4"/>
  <path d="M16 18a4 4 0 0 0-8 0"/>
</svg>`;

/**
 * Microphone icon (for voice input)
 */
export const MICROPHONE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z"/>
  <path d="M19 10v2a7 7 0 01-14 0v-2"/>
  <line x1="12" y1="19" x2="12" y2="23"/>
  <line x1="8" y1="23" x2="16" y2="23"/>
</svg>`;

/**
 * Speaker icon (for text-to-speech)
 */
export const SPEAKER_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
  <path d="M15.54 8.46a5 5 0 010 7.07"/>
  <path d="M19.07 4.93a10 10 0 010 14.14"/>
</svg>`;

/**
 * Stop icon (square, for stopping recording)
 */
export const STOP_ICON = `<svg viewBox="0 0 24 24" fill="currentColor">
  <rect x="6" y="6" width="12" height="12" rx="1"/>
</svg>`;

/**
 * Search/magnifying glass icon (for web search)
 */
export const SEARCH_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="11" cy="11" r="8"/>
  <line x1="21" y1="21" x2="16.65" y2="16.65"/>
</svg>`;

/**
 * Stream icon (for streaming toggle - signal/broadcast)
 */
export const STREAM_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9"/>
  <path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5"/>
  <circle cx="12" cy="12" r="2" fill="currentColor"/>
  <path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5"/>
  <path d="M19.1 4.9C23 8.8 23 15.2 19.1 19.1"/>
</svg>`;

/**
 * Stream off icon (streaming disabled)
 */
export const STREAM_OFF_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="2" fill="currentColor"/>
  <line x1="4" y1="4" x2="20" y2="20"/>
</svg>`;

/**
 * Plus icon in circle (for new chat button)
 */
export const PLUS_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="10"/>
  <line x1="12" y1="8" x2="12" y2="16"/>
  <line x1="8" y1="12" x2="16" y2="12"/>
</svg>`;

/**
 * Chevron down icon (for scroll to bottom)
 */
export const CHEVRON_DOWN_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="6 9 12 15 18 9"/>
</svg>`;

/**
 * Refresh icon (for version update banner)
 */
export const REFRESH_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M21 2v6h-6"/>
  <path d="M3 12a9 9 0 0 1 15-6.7L21 8"/>
  <path d="M3 22v-6h6"/>
  <path d="M21 12a9 9 0 0 1-15 6.7L3 16"/>
</svg>`;

/**
 * Globe/link icon (for web sources)
 */
export const SOURCES_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="10"/>
  <line x1="2" y1="12" x2="22" y2="12"/>
  <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
</svg>`;

/**
 * Sparkles icon (for image generation)
 */
export const SPARKLES_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 3L13.5 8.5L19 10L13.5 11.5L12 17L10.5 11.5L5 10L10.5 8.5L12 3Z"/>
  <path d="M19 14L19.75 16.25L22 17L19.75 17.75L19 20L18.25 17.75L16 17L18.25 16.25L19 14Z"/>
  <path d="M6 18L6.5 19.5L8 20L6.5 20.5L6 22L5.5 20.5L4 20L5.5 19.5L6 18Z"/>
</svg>`;

/**
 * Dollar/cost icon (for message cost)
 */
export const COST_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <line x1="12" y1="1" x2="12" y2="23"/>
  <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>
</svg>`;

/**
 * Warning/alert triangle icon (for warnings)
 */
export const WARNING_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
  <line x1="12" y1="9" x2="12" y2="13"/>
  <line x1="12" y1="17" x2="12.01" y2="17"/>
</svg>`;

/**
 * Info circle icon (for informational messages)
 */
export const INFO_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="10"/>
  <line x1="12" y1="16" x2="12" y2="12"/>
  <line x1="12" y1="8" x2="12.01" y2="8"/>
</svg>`;

/**
 * Phone icon (for WhatsApp/phone settings)
 */
export const PHONE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/>
</svg>`;

/**
 * Link/chain icon (for URL fetching)
 */
export const LINK_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
  <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
</svg>`;

/**
 * Chevron right icon (for expandable sections)
 */
export const CHEVRON_RIGHT_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="9 18 15 12 9 6"/>
</svg>`;

/**
 * Brain icon (for AI thinking indicator)
 */
export const BRAIN_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2Z"/>
  <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2Z"/>
</svg>`;

/**
 * @deprecated Use BRAIN_ICON instead
 */
export const THINKING_ICON = BRAIN_ICON;

/**
 * Code/terminal icon (for code execution)
 */
export const CODE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="16 18 22 12 16 6"/>
  <polyline points="8 6 2 12 8 18"/>
</svg>`;

/**
 * Settings/gear icon
 */
export const SETTINGS_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="3"/>
  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
</svg>`;

/**
 * Sun icon (for light mode)
 */
export const SUN_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="5"/>
  <line x1="12" y1="1" x2="12" y2="3"/>
  <line x1="12" y1="21" x2="12" y2="23"/>
  <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
  <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
  <line x1="1" y1="12" x2="3" y2="12"/>
  <line x1="21" y1="12" x2="23" y2="12"/>
  <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
  <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
</svg>`;

/**
 * Moon icon (for dark mode)
 */
export const MOON_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
</svg>`;

/**
 * Monitor/desktop icon (for system color scheme)
 */
export const MONITOR_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>
  <line x1="8" y1="21" x2="16" y2="21"/>
  <line x1="12" y1="17" x2="12" y2="21"/>
</svg>`;

/**
 * Incognito icon (detective/spy style - hat and glasses silhouette for anonymous mode)
 */
export const INCOGNITO_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M2 12h20"/>
  <path d="M5 12c0-4 3-8 7-8s7 4 7 8"/>
  <circle cx="8" cy="17" r="3"/>
  <circle cx="16" cy="17" r="3"/>
  <path d="M11 17h2"/>
</svg>`;

/**
 * Planner icon (calendar with checkmark - represents daily planning)
 */
export const PLANNER_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
  <line x1="16" y1="2" x2="16" y2="6"/>
  <line x1="8" y1="2" x2="8" y2="6"/>
  <line x1="3" y1="10" x2="21" y2="10"/>
  <polyline points="9 16 11 18 15 14"/>
</svg>`;

/**
 * Clear/reset icon (for clearing planner conversation)
 */
export const STAR_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
</svg>`;

export const CLEAR_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M3 6h18"/>
  <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
  <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
</svg>`;

/**
 * Robot icon (for autonomous agents)
 */
export const ROBOT_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="11" width="18" height="10" rx="2"/>
  <circle cx="12" cy="5" r="2"/>
  <path d="M12 7v4"/>
  <line x1="8" y1="16" x2="8" y2="16"/>
  <line x1="16" y1="16" x2="16" y2="16"/>
</svg>`;

/**
 * Menu/hamburger icon
 */
export const MENU_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <line x1="3" y1="12" x2="21" y2="12"/>
  <line x1="3" y1="6" x2="21" y2="6"/>
  <line x1="3" y1="18" x2="21" y2="18"/>
</svg>`;

/**
 * Command center icon (dashboard/grid)
 */
export const COMMAND_CENTER_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="3" width="7" height="7"/>
  <rect x="14" y="3" width="7" height="7"/>
  <rect x="14" y="14" width="7" height="7"/>
  <rect x="3" y="14" width="7" height="7"/>
</svg>`;

/**
 * Play icon (for manual trigger)
 */
export const PLAY_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <polygon points="5 3 19 12 5 21 5 3"/>
</svg>`;

/**
 * Chain link icon (for agent chain triggers)
 */
export const CHAIN_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
  <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
</svg>`;

/**
 * Image icon (for image generation)
 */
export const IMAGE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
  <circle cx="8.5" cy="8.5" r="1.5"/>
  <path d="M21 15l-5-5L5 21"/>
</svg>`;

/**
 * Database icon (for K/V storage)
 */
export const DATABASE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <ellipse cx="12" cy="5" rx="9" ry="3"/>
  <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
  <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
</svg>`;

/**
 * Activity icon (heart with pulse line - for Garmin Connect health tracking)
 */
export const ACTIVITY_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M20.42 4.58a5.4 5.4 0 0 0-7.65 0L12 5.34l-.77-.76a5.4 5.4 0 0 0-7.65 0 5.4 5.4 0 0 0 0 7.65L12 20.65l8.42-8.42a5.4 5.4 0 0 0 0-7.65z"/>
  <path d="M3.5 12h4l1.5-3 2 6 1.5-3h8"/>
</svg>`;

// ============================================
// Weather Icons (mapped from Yr.no symbol_code)
// ============================================

/**
 * Weather: clear sky / sun
 */
export const WEATHER_SUN_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="5"/>
  <line x1="12" y1="1" x2="12" y2="3"/>
  <line x1="12" y1="21" x2="12" y2="23"/>
  <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
  <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
  <line x1="1" y1="12" x2="3" y2="12"/>
  <line x1="21" y1="12" x2="23" y2="12"/>
  <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
  <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
</svg>`;

/**
 * Weather: cloud
 */
export const WEATHER_CLOUD_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>
</svg>`;

/**
 * Weather: partly cloudy (sun + cloud)
 */
export const WEATHER_PARTLY_CLOUDY_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M12 2v2"/>
  <path d="M4.93 4.93l1.41 1.41"/>
  <path d="M20 12h2"/>
  <path d="M19.07 4.93l-1.41 1.41"/>
  <path d="M15.947 12.65a4 4 0 0 0-5.925-4.128"/>
  <path d="M13 22H7a5 5 0 1 1 4.9-6H13a3 3 0 0 1 0 6Z"/>
</svg>`;

/**
 * Weather: rain (cloud with drops)
 */
export const WEATHER_RAIN_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/>
  <path d="M16 14v6"/>
  <path d="M8 14v6"/>
  <path d="M12 16v6"/>
</svg>`;

/**
 * Weather: snow (cloud with snowflakes)
 */
export const WEATHER_SNOW_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/>
  <path d="M8 15h.01"/>
  <path d="M8 19h.01"/>
  <path d="M12 17h.01"/>
  <path d="M12 21h.01"/>
  <path d="M16 15h.01"/>
  <path d="M16 19h.01"/>
</svg>`;

/**
 * Weather: fog
 */
export const WEATHER_FOG_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/>
  <path d="M16 17H7"/>
  <path d="M17 21H9"/>
</svg>`;

/**
 * Get weather icon SVG based on Yr.no symbol_code.
 */
export function getWeatherIcon(symbolCode: string | null | undefined): string {
  if (!symbolCode) return WEATHER_CLOUD_ICON;
  const code = symbolCode.toLowerCase();
  if (code.includes('clearsky') || code.includes('fair')) return WEATHER_SUN_ICON;
  if (code.includes('partlycloudy')) return WEATHER_PARTLY_CLOUDY_ICON;
  if (code.includes('snow') || code.includes('sleet')) return WEATHER_SNOW_ICON;
  if (code.includes('rain') || code.includes('drizzle') || code.includes('shower')) return WEATHER_RAIN_ICON;
  if (code.includes('fog')) return WEATHER_FOG_ICON;
  return WEATHER_CLOUD_ICON;
}

// ============================================
// Health Icons (for Garmin dashboard strip)
// ============================================

/**
 * Heart icon (for resting heart rate)
 */
export const HEART_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/>
</svg>`;

/**
 * Battery icon (for body battery - simple bold outline with charge level)
 */
export const BATTERY_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <rect x="2" y="6" width="18" height="12" rx="2"/>
  <line x1="22" y1="10" x2="22" y2="14"/>
  <rect x="5" y="9" width="8" height="6" rx="1" fill="currentColor"/>
</svg>`;

/**
 * Stress icon (single pulse/heartbeat line - clean at small sizes)
 */
export const STRESS_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="2 12 6 12 9 4 12 20 15 12 18 12 22 12"/>
</svg>`;

/**
 * Zap/lightning icon (for training readiness - energy to train)
 */
export const READINESS_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M13 2L4 13h7l-1 9 9-11h-7l1-9z"/>
</svg>`;

/**
 * Footprints icon (for step count - two simple shoe prints, offset diagonally)
 */
export const STEPS_ICON = `<svg viewBox="0 0 24 24" fill="currentColor" stroke="none">
  <ellipse cx="8" cy="5" rx="2.5" ry="4" transform="rotate(10 8 5)"/>
  <ellipse cx="8" cy="12" rx="1.8" ry="1.2" transform="rotate(10 8 12)"/>
  <ellipse cx="16" cy="12" rx="2.5" ry="4" transform="rotate(-10 16 12)"/>
  <ellipse cx="16" cy="19" rx="1.8" ry="1.2" transform="rotate(-10 16 19)"/>
</svg>`;
