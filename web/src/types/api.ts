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
}

// Detail event types (thinking + tools, interleaved in order)
export type DetailEvent =
  | { type: 'thinking'; content: string }
  | { type: 'tool_call'; id: string; name: string; args: Record<string, unknown> }
  | { type: 'tool_result'; tool_call_id: string; content: string };

// Message types
export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  files?: FileMetadata[];
  hasDetails?: boolean; // Flag for lazy loading (from API)
  details?: DetailEvent[]; // Actual data (from streaming or lazy load)
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
  | { type: 'thinking'; content: string } // Phase 2
  | { type: 'tool_call'; id: string; name: string; args: Record<string, unknown> }
  | { type: 'tool_result'; tool_call_id: string; content: string }
  | { type: 'done'; id: string; created_at: string; details?: DetailEvent[] }
  | { type: 'error'; message: string };

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
  created_at: string;
}

export interface ErrorResponse {
  error: string;
}