/**
 * API types for the AI Chatbot frontend.
 *
 * This file defines types for API communication. While we have auto-generated
 * types from the OpenAPI spec (in generated-api.ts), we keep manual types here
 * for frontend flexibility (e.g., adding frontend-only fields like previewUrl).
 *
 * The generated types are available for reference and can be used for strict
 * validation in tests. To regenerate:
 *   npm run types:generate
 */

// Re-export generated types for reference and test validation
export type { components, paths } from './generated-api';

// Constants
export const DEFAULT_CONVERSATION_TITLE = 'New Conversation';

// Enums (as const objects for TypeScript - mirrors Python enums in src/api/schemas.py)
export const PaginationDirection = {
  OLDER: 'older',
  NEWER: 'newer',
} as const;
export type PaginationDirection = (typeof PaginationDirection)[keyof typeof PaginationDirection];

// =============================================================================
// User types
// =============================================================================

export interface User {
  id: string;
  email: string;
  name: string;
  picture: string | null;
}

// =============================================================================
// Conversation types
// =============================================================================

export interface Conversation {
  id: string;
  title: string;
  model: string;
  created_at: string;
  updated_at: string;
  messages?: Message[];
  cost?: number; // Cost in display currency (optional, fetched separately)
  cost_usd?: number; // Cost in USD (optional)
  cost_formatted?: string; // Formatted cost string (optional)
  // Sync-related fields
  unreadCount?: number; // Number of unread messages from other devices
  hasExternalUpdate?: boolean; // True if conversation was updated externally while viewing
  messageCount?: number; // Total message count from server (for sync calculations)
}

// =============================================================================
// Message types
// =============================================================================

export interface Source {
  title: string;
  url: string;
}

export interface GeneratedImage {
  prompt: string;
  image_index?: number;
  message_id?: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  files?: FileMetadata[];
  sources?: Source[];
  generated_images?: GeneratedImage[];
  language?: string; // ISO 639-1 language code for TTS (e.g., 'en', 'cs')
  created_at: string;
}

// =============================================================================
// File types
// =============================================================================

export interface FileMetadata {
  name: string;
  type: string;
  messageId?: string;
  fileIndex?: number;
  previewUrl?: string; // blob URL for immediate display (local uploads only)
}

export interface FileUpload {
  name: string;
  type: string;
  data: string; // base64
  previewUrl?: string; // blob URL for local preview
}

// =============================================================================
// Model types
// =============================================================================

export interface Model {
  id: string;
  name: string;
}

// =============================================================================
// Upload config
// =============================================================================

export interface UploadConfig {
  maxFileSize: number;
  maxFilesPerMessage: number;
  allowedFileTypes: string[];
}

// =============================================================================
// Streaming types (SSE events - frontend only)
// =============================================================================

// Tool metadata provided by backend for display
export interface ToolMetadata {
  label: string; // Present tense label (e.g., "Searching the web")
  label_past: string; // Past tense label (e.g., "Searched")
  icon: string; // Icon key (search, link, sparkles, code, checklist)
}

export type StreamEvent =
  | { type: 'token'; text: string }
  | { type: 'thinking'; text: string }
  | { type: 'tool_start'; tool: string; detail?: string; metadata?: ToolMetadata }
  | { type: 'tool_detail'; tool: string; detail: string }
  | { type: 'tool_end'; tool: string }
  | { type: 'user_message_saved'; user_message_id: string } // Sent early so lightbox works during streaming
  | {
      type: 'done';
      id: string;
      created_at: string;
      sources?: Source[];
      generated_images?: GeneratedImage[];
      files?: FileMetadata[];
      language?: string; // ISO 639-1 language code for TTS
      title?: string;
      user_message_id?: string; // Real ID of the user message (kept for backwards compatibility)
    }
  | { type: 'error'; message: string; code?: string; retryable?: boolean };

// =============================================================================
// UI State types (frontend-only)
// =============================================================================

export interface ThinkingTraceItem {
  type: 'thinking' | 'tool';
  label: string;
  detail?: string;
  completed: boolean;
  metadata?: ToolMetadata; // Backend-provided display metadata (label, icon)
}

export interface ThinkingState {
  isThinking: boolean;
  thinkingText: string;
  activeTool: string | null;
  activeToolDetail?: string;
  completedTools: string[];
  trace: ThinkingTraceItem[];
}

// =============================================================================
// API Response types
// =============================================================================

export interface AuthResponse {
  token: string;
  user: User;
}

// =============================================================================
// Pagination types
// =============================================================================

export interface ConversationsPagination {
  next_cursor: string | null;
  has_more: boolean;
  total_count: number;
}

export interface MessagesPagination {
  older_cursor: string | null;
  newer_cursor: string | null;
  has_older: boolean;
  has_newer: boolean;
  total_count: number;
}

export interface ConversationsResponse {
  conversations: Conversation[];
  pagination: ConversationsPagination;
}

export interface ConversationDetailResponse {
  id: string;
  title: string;
  model: string;
  created_at: string;
  updated_at: string;
  messages: Message[];
  message_pagination: MessagesPagination;
}

export interface MessagesResponse {
  messages: Message[];
  pagination: MessagesPagination;
}

export interface ModelsResponse {
  models: Model[];
  default: string;
}

export interface ChatResponse {
  id: string;
  role: 'assistant';
  content: string;
  files?: FileMetadata[];
  sources?: Source[];
  generated_images?: GeneratedImage[];
  created_at: string;
  title?: string;
  user_message_id?: string; // Real ID of the user message (for updating temp IDs)
}

export interface ErrorResponse {
  error: string | {
    code: string;
    message: string;
    retryable?: boolean;
    details?: Record<string, unknown>;
  };
}

export interface VersionResponse {
  version: string | null;
}

// =============================================================================
// Cost tracking types
// =============================================================================

export interface ConversationCostResponse {
  conversation_id: string;
  cost_usd: number;
  cost: number;
  currency: string;
  formatted: string;
}

export interface MessageCostResponse {
  message_id: string;
  cost_usd: number;
  cost: number;
  currency: string;
  formatted: string;
  input_tokens: number;
  output_tokens: number;
  model: string;
  image_generation_cost_usd?: number;
  image_generation_cost?: number;
  image_generation_cost_formatted?: string;
}

export interface MonthlyCostResponse {
  user_id: string;
  year: number;
  month: number;
  total_usd: number;
  total: number;
  currency: string;
  formatted: string;
  message_count: number;
  breakdown: Record<string, {
    total: number;
    total_usd: number;
    message_count: number;
    formatted: string;
  }>;
}

export interface CostHistoryResponse {
  user_id: string;
  history: Array<{
    year: number;
    month: number;
    total_usd: number;
    total: number;
    currency: string;
    formatted: string;
    message_count: number;
  }>;
}

// =============================================================================
// Sync types
// =============================================================================

export interface ConversationSummary {
  id: string;
  title: string;
  model: string;
  updated_at: string;
  message_count: number;
}

export interface SyncResponse {
  conversations: ConversationSummary[];
  server_time: string;
  is_full_sync: boolean;
}

// =============================================================================
// Memory types
// =============================================================================

export interface Memory {
  id: string;
  content: string;
  category: string | null;
  created_at: string;
  updated_at: string;
}

export interface MemoriesResponse {
  memories: Memory[];
}

// =============================================================================
// Settings types
// =============================================================================

export interface UserSettings {
  custom_instructions: string;
}

// =============================================================================
// Todoist types
// =============================================================================

export interface TodoistAuthUrl {
  auth_url: string;
  state: string;
}

export interface TodoistConnectResponse {
  connected: boolean;
  todoist_email: string | null;
}

export interface TodoistStatus {
  connected: boolean;
  todoist_email: string | null;
  connected_at: string | null;
  needs_reconnect: boolean;
}

// =============================================================================
// Google Calendar types
// =============================================================================

export interface CalendarAuthUrl {
  auth_url: string;
  state: string;
}

export interface CalendarConnectResponse {
  connected: boolean;
  calendar_email: string | null;
}

export interface CalendarStatus {
  connected: boolean;
  calendar_email: string | null;
  connected_at: string | null;
  needs_reconnect: boolean;
}

// =============================================================================
// Search types
// =============================================================================

export interface SearchResult {
  conversation_id: string;
  conversation_title: string;
  message_id: string | null;
  message_snippet: string | null;
  match_type: 'conversation' | 'message';
  created_at: string | null;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
  query: string;
}
