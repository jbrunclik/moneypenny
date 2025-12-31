// Constants
export const DEFAULT_CONVERSATION_TITLE = 'New Conversation';

// User types
export interface User {
  id: string;
  email: string;
  name: string;
  picture: string | null;
}

// Conversation types
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

// Source types (for web search results)
export interface Source {
  title: string;
  url: string;
}

// Generated image metadata
export interface GeneratedImage {
  prompt: string;
  image_index?: number; // Optional - not currently set by backend, but reserved for future use
  message_id?: string; // Optional - message ID for fetching cost
}

// Message types
export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  files?: FileMetadata[];
  sources?: Source[];
  generated_images?: GeneratedImage[];
  created_at: string;
}

// File types
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

// Model types
export interface Model {
  id: string;
  name: string;
}

// Upload config
export interface UploadConfig {
  maxFileSize: number;
  maxFilesPerMessage: number;
  allowedFileTypes: string[];
}

// Streaming response events
export type StreamEvent =
  | { type: 'token'; text: string }
  | { type: 'thinking'; text: string }
  | { type: 'tool_start'; tool: string; detail?: string }
  | { type: 'tool_end'; tool: string }
  | {
      type: 'done';
      id: string;
      created_at: string;
      sources?: Source[];
      generated_images?: GeneratedImage[];
      files?: FileMetadata[];
      title?: string; // Auto-generated conversation title (only present for first message)
    }
  | { type: 'error'; message: string; code?: string; retryable?: boolean };

// Single event in the thinking/tool trace
export interface ThinkingTraceItem {
  type: 'thinking' | 'tool';
  label: string;
  detail?: string;
  completed: boolean;
}

// Thinking indicator state for streaming messages
export interface ThinkingState {
  isThinking: boolean;
  thinkingText: string;
  activeTool: string | null;
  activeToolDetail?: string;
  completedTools: string[];
  /** Full trace of all thinking/tool events with details */
  trace: ThinkingTraceItem[];
}

// API response types
export interface AuthResponse {
  token: string;
  user: User;
}

export interface ConversationsResponse {
  conversations: Conversation[];
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
  title?: string; // Auto-generated conversation title (only present for first message)
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

// Cost tracking types
export interface ConversationCostResponse {
  conversation_id: string;
  cost_usd: number;
  cost: number;
  currency: string;
  formatted: string;
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

export interface MessageCostResponse {
  message_id: string;
  cost_usd: number;
  cost: number; // Cost in display currency
  currency: string;
  formatted: string;
  input_tokens: number;
  output_tokens: number;
  model: string;
  image_generation_cost_usd?: number;
  image_generation_cost?: number; // Image generation cost in display currency
  image_generation_cost_formatted?: string;
}

// Sync types
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

// Memory types
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