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
  // Integration status - populated client-side after fetching status endpoints
  todoist_connected?: boolean;
  calendar_connected?: boolean;
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
  // Agent-related fields
  is_agent?: boolean; // True if this is an agent's dedicated conversation
  agent_id?: string | null; // ID of the agent if is_agent is true
  has_pending_approval?: boolean; // True if agent has pending approval request (from server)
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
  short_name: string; // Short display name for compact UI (e.g., 'Fast', 'Advanced')
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
  is_agent?: boolean;
  agent_id?: string | null;
  has_pending_approval?: boolean; // True if agent has pending approval request
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

export interface Calendar {
  id: string;
  summary: string;
  primary: boolean;
  access_role: string;
  background_color?: string;
}

export interface CalendarListResponse {
  calendars: Calendar[];
  error?: string;
}

export interface SelectedCalendarsResponse {
  calendar_ids: string[];
}

export interface UpdateSelectedCalendarsRequest {
  calendar_ids: string[];
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

// =============================================================================
// Planner types
// =============================================================================

export interface PlannerTask {
  id: string;
  content: string;
  description?: string;
  due_date?: string | null;
  due_string?: string | null;
  priority: number;
  project_name?: string | null;
  section_name?: string | null;
  labels?: string[];
  is_recurring?: boolean;
  url?: string | null;
}

export interface PlannerEvent {
  id: string;
  summary: string;
  description?: string | null;
  start?: string | null;
  end?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  location?: string | null;
  html_link?: string | null;
  is_all_day: boolean;
  attendees?: Array<{
    email?: string;
    response_status?: string;
    self?: boolean;
  }>;
  organizer?: {
    email?: string;
    display_name?: string;
    self?: boolean;
  } | null;
  calendar_id?: string | null;
  calendar_summary?: string | null;
}

export interface PlannerDay {
  date: string;
  day_name: string;
  events: PlannerEvent[];
  tasks: PlannerTask[];
}

export interface PlannerDashboard {
  days: PlannerDay[];
  overdue_tasks: PlannerTask[];
  todoist_connected: boolean;
  calendar_connected: boolean;
  todoist_error?: string | null;
  calendar_error?: string | null;
  server_time: string;
}

export interface PlannerConversation {
  id: string;
  title: string;
  model: string;
  created_at: string;
  updated_at: string;
  messages: Message[];
  was_reset: boolean;
}

export interface PlannerResetResponse {
  success: boolean;
  message: string;
}

export interface PlannerConversationSyncData {
  id: string;
  updated_at: string;
  message_count: number;
  last_reset: string | null;
}

export interface PlannerSyncResponse {
  conversation: PlannerConversationSyncData | null;
  server_time: string;
}

// =============================================================================
// Autonomous Agent types
// =============================================================================

export const AgentStatus = {
  RUNNING: 'running',
  COMPLETED: 'completed',
  FAILED: 'failed',
  WAITING_APPROVAL: 'waiting_approval',
} as const;
export type AgentStatus = (typeof AgentStatus)[keyof typeof AgentStatus];

export const AgentTriggerType = {
  SCHEDULED: 'scheduled',
  MANUAL: 'manual',
  AGENT_TRIGGER: 'agent_trigger',
} as const;
export type AgentTriggerType = (typeof AgentTriggerType)[keyof typeof AgentTriggerType];

export const ApprovalStatus = {
  PENDING: 'pending',
  APPROVED: 'approved',
  REJECTED: 'rejected',
} as const;
export type ApprovalStatus = (typeof ApprovalStatus)[keyof typeof ApprovalStatus];

export interface Agent {
  id: string;
  name: string;
  description?: string | null;
  system_prompt?: string | null;
  schedule?: string | null;
  timezone: string;
  enabled: boolean;
  tool_permissions?: string[] | null;
  model: string;
  conversation_id?: string | null;
  last_run_at?: string | null;
  next_run_at?: string | null;
  created_at: string;
  updated_at: string;
  budget_limit?: number | null; // Daily budget limit in USD (null = unlimited)
  daily_spending: number; // Today's spending in USD
  has_pending_approval: boolean;
  has_error: boolean;
  unread_count: number;
  last_execution_status?: string | null;
}

export interface CreateAgentRequest {
  name: string;
  description?: string;
  system_prompt?: string;
  schedule?: string;
  timezone?: string;
  tool_permissions?: string[];
  enabled?: boolean;
  model?: string;
  budget_limit?: number; // Daily budget limit in USD (null = unlimited)
}

export interface UpdateAgentRequest {
  name?: string;
  description?: string;
  system_prompt?: string;
  schedule?: string;
  timezone?: string;
  tool_permissions?: string[];
  enabled?: boolean;
  model?: string;
  budget_limit?: number; // Daily budget limit in USD (null = unlimited)
}

export interface AgentExecution {
  id: string;
  agent_id: string;
  status: AgentStatus;
  trigger_type: AgentTriggerType;
  triggered_by_agent_id?: string | null;
  started_at: string;
  completed_at?: string | null;
  error_message?: string | null;
}

export interface ApprovalRequest {
  id: string;
  agent_id: string;
  agent_name: string;
  tool_name: string;
  tool_args?: Record<string, unknown> | null;
  description: string;
  status: ApprovalStatus;
  created_at: string;
  resolved_at?: string | null;
}

export interface AgentsListResponse {
  agents: Agent[];
}

export interface AgentExecutionsListResponse {
  executions: AgentExecution[];
}

export interface CommandCenterResponse {
  agents: Agent[];
  pending_approvals: ApprovalRequest[];
  recent_executions: AgentExecution[];
  total_unread: number;
  agents_waiting: number;
  agents_with_errors: number;
}

export interface TriggerAgentResponse {
  execution: AgentExecution;
  message: string;
}

export interface AgentConversationSyncData {
  message_count: number;
  updated_at: string;
}

export interface AgentConversationSyncResponse {
  conversation: AgentConversationSyncData | null;
  server_time: string;
}

// =============================================================================
// AI Assist types
// =============================================================================

export interface ParseScheduleRequest {
  natural_language: string;
  timezone?: string;
}

export interface ParseScheduleResponse {
  cron?: string | null;
  explanation?: string | null;
  error?: string | null;
}

export interface EnhancePromptRequest {
  prompt: string;
  agent_name: string;
}

export interface EnhancePromptResponse {
  enhanced_prompt?: string | null;
  error?: string | null;
}
