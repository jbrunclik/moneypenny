/**
 * API types for the Moneypenny frontend.
 *
 * API types are aliases of the schemas generated from the OpenAPI spec
 * (generated-api.ts, `make types`), extended only for frontend-only fields
 * such as previewUrl (F6). Hand-written types remain for client state
 * (Message, Conversation), SSE event shapes and the few places noted below
 * where the client still relies on a shape the spec does not promise.
 */

// Re-export generated types for reference and test validation
export type { components } from './generated-api';

type Schemas = import('./generated-api').components['schemas'];

// Admin page and spend status (S12)
export type AdminOverview = Schemas['AdminOverviewResponse'];
export type SpendStatus = Schemas['SpendStatusResponse'];

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

export type User = Schemas['UserContainerResponse.UserResponse'] & {
  // Integration status - populated client-side after fetching status endpoints
  todoist_connected?: boolean;
  calendar_connected?: boolean;
};

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
  // Archive state
  archived?: boolean; // True if conversation is archived (hidden from main list)
  // Sync merges pass the server's summary value through: a missing one
  // overwrites (clears) the stored value, so undefined is explicit here
  pinned?: boolean | undefined; // Pinned to the top of the sidebar
  streaming_message_id?: string | null; // Reply still being generated (another device) - from the detail response
  lost_reply?: boolean; // The last turn died with nothing saved - from the detail response
  // Trash state (only set on conversations from the trash listing)
  deleted_at?: string | null; // When it was moved to the trash
  purge_at?: string | null; // When the server deletes it for good
  // Sync-related fields
  unreadCount?: number; // Number of unread messages from other devices
  hasExternalUpdate?: boolean; // True if conversation was updated externally while viewing
  messageCount?: number; // Total message count from server (for sync calculations)
  last_message_preview?: string | null | undefined; // One-line snippet of the newest message (sidebar); see pinned
}

// =============================================================================
// Message types
// =============================================================================

export type Source = Schemas['MessageResponse.SourceResponse'];

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
  /** Assistant reply cut off by the tool-round cap (server-set) */
  stopped_early?: boolean;
  /** Why the reply ended early: 'user' = the user pressed Stop (server-set) */
  stop_reason?: 'user';
  /** Grounding-check claims (server-set; src/agent/grounding_annotations.py) */
  annotations?: ClaimAnnotation[];
  /** Grounding-check summary for the footer (server-set) */
  grounding?: GroundingSummary;
  /** Deep-research offer or run (server-set; src/agent/deep_research/) */
  research?: MessageResearch;
  /** A user message the app sent on the user's behalf */
  action?: MessageAction;
  /** Artifact versions shown under the reply (server-set; src/agent/tools/artifacts.py) */
  artifacts?: ArtifactRef[];
  created_at: string;
  /** Client-only send state; never sent by the server (absent = delivered) */
  status?: 'pending' | 'failed' | undefined; // patched to undefined (updateMessage) to clear it
}

/** An artifact version shown under a reply: sandboxed HTML/JS (docs/features/artifacts.md) */
export type ArtifactRef = Schemas['MessageResponse.ArtifactRef'];

/** One artifact version's HTML and the artifact's saved state (GET /api/artifacts/<id>/versions/<v>) */
export type ArtifactVersion = Schemas['ArtifactVersionResponse'];

/** What the client needs to recompute an offer's estimate while it is edited */
export interface ResearchRates {
  base_minutes: number;
  per_wave_minutes: number;
  parallelism: number;
  base_czk: number;
  per_item_czk: number;
}

export type ResearchOfferStatus = 'offered' | 'started' | 'declined' | 'superseded';

/** A deep-research offer (src/agent/deep_research/offer.py build_offer) */
export interface ResearchOffer {
  question: string;
  context: string;
  sub_questions: string[];
  estimate: { minutes: number; cost_czk: number };
  rates: ResearchRates;
  status: ResearchOfferStatus;
  autostart: boolean;
  kind: 'initial' | 'followup';
  round: number;
  created_at?: string;
  decided_at?: string;
}

/** A finished run's data on the report message (src/agent/deep_research/pipeline.py _run_data) */
export interface ResearchRun {
  round: number;
  question: string;
  context: string;
  offered_sub_questions: string[];
  sub_questions: string[];
  items: { status: 'done' | 'failed' | 'skipped' | 'timed_out'; pages: number }[];
  pages_read: number;
  board: { agent: number; kind: 'finding' | 'lead'; text: string; urls: string[] }[];
  cache_hits: number;
  duration_ms: number;
  estimate: { minutes: number; cost_czk: number };
  finished_early: boolean;
  /** Offer of a next round, extracted from the report */
  followup?: ResearchOffer;
}

export interface MessageResearch {
  offer?: ResearchOffer;
  run?: ResearchRun;
}

/** The chat request's deep_research field: start an offer with the edited plan */
export type DeepResearchStart = Schemas['ChatRequest.DeepResearchStart'];

// The action types stay hand-written: the spec reuses the request models in
// MessageResponse, so items/minutes/source_message_id come out optional,
// while every stored action has them and the action row reads them.

/** Look it up on a claim card (source_message_id/claim_index null for converted old messages) */
interface VerifyClaimAction {
  type: 'verify_claim';
  source_message_id: string | null;
  claim_index: number | null;
  quote: string;
}

/** Start on a deep-research offer */
interface DeepResearchAction {
  type: 'deep_research';
  offer_message_id: string;
  items: number;
  minutes: number;
}

/** What a user message sent on the user's behalf was (rendered as an action row) */
export type MessageAction = VerifyClaimAction | DeepResearchAction;

/** This device's Web Push state, as the settings show it (core/push) */
export type PushState =
  | 'unsupported'
  | 'ios-needs-install'
  | 'server-disabled'
  | 'denied'
  | 'subscribed'
  | 'not-subscribed';

/** What a send carries besides the text */
export interface SendExtras {
  deepResearch?: DeepResearchStart;
  action?: MessageAction;
}

// ClaimAnnotation and GroundingSummary stay hand-written: they also arrive on
// the SSE done event (not in the spec) and are read back from the DOM, where
// the optional fields can be missing.

export type ClaimVerdict = 'supported' | 'partial' | 'not_found' | 'contradicted';

/** One claim of an answer and how the turn's sources bear on it */
export interface ClaimAnnotation {
  type: 'claim';
  verdict: ClaimVerdict;
  /** Literal phrase of the message's markdown */
  quote: string;
  /** Text right before the quote (picks among repeats) */
  prefix?: string | null;
  reason?: string | null;
  /** 1-based index into the message's sources */
  source?: number | null;
  /** Literal passage of that source */
  source_quote?: string | null;
}

export interface GroundingSummary {
  checked: boolean;
  source_count?: number | null;
  /** Converted from the pre-Oct-3-2026 inline markers (no reasons or total) */
  legacy?: boolean | null;
}

// =============================================================================
// File types
// =============================================================================

// FileMetadata and GeneratedImage are Message state (local uploads, SSE done
// events) with client-only fields, so they stay hand-written like Message.

export interface FileMetadata {
  name: string;
  type: string;
  messageId?: string;
  fileIndex?: number;
  previewUrl?: string; // blob URL for immediate display (local uploads only)
}

/** `data` is base64 */
export type FileUpload = Schemas['ChatRequest.FileAttachment'] & {
  previewUrl?: string; // blob URL for local preview
};

/**
 * Device GPS fix attached to chat requests when location sharing is enabled.
 * Hand-written: the request schema lets timestamp_ms be omitted, but the
 * client always sets it and reads it back to age its cached fix.
 */
export interface ClientLocation {
  lat: number;
  lon: number;
  accuracy_m: number | null;
  timestamp_ms: number;
}

// =============================================================================
// Model types
// =============================================================================

export type Model = Schemas['ModelsListResponse.ModelResponse'] & {
  // One-line description shown in the model dropdown. The /api/models route
  // builds it, but ModelResponse does not declare it, so the output schema
  // drops it (Oct 25 2026).
  description?: string;
};

// =============================================================================
// Upload config
// =============================================================================

export type UploadConfig = Schemas['UploadConfigResponse'];

// =============================================================================
// Streaming types (SSE events - frontend only)
// =============================================================================

// Tool metadata provided by backend for display
export interface ToolMetadata {
  label: string; // Present tense label (e.g., "Searching the web")
  label_past: string; // Past tense label (e.g., "Searched")
  icon: string; // Icon key (search, link, sparkles, code, checklist)
}

export type StreamEvent = (
  | { type: 'token'; text: string }
  | { type: 'thinking'; text: string }
  | { type: 'tool_start'; tool: string; detail?: string; metadata?: ToolMetadata }
  | { type: 'tool_detail'; tool: string; detail: string }
  | { type: 'tool_end'; tool: string }
  | { type: 'retry'; attempt: number; max_retries?: number } // Transient model error being retried
  | { type: 'stopping' } // Server-side Stop acknowledged; done follows at the next checkpoint
  | { type: 'user_message_saved'; user_message_id: string } // Sent early so lightbox works during streaming
  // Another device's turn was running: the send steered it (follow that reply)
  | { type: 'interjected'; message_id: string; message_count: number }
  | { type: 'timeout'; message?: string } // Server-side CHAT_TIMEOUT hit; partial content saved
  | {
      type: 'done';
      id: string;
      created_at: string;
      content?: string; // Full content (resume path / recovery if token events were lost)
      sources?: Source[];
      generated_images?: GeneratedImage[];
      files?: FileMetadata[];
      language?: string; // ISO 639-1 language code for TTS
      title?: string;
      user_message_id?: string; // Real ID of the user message (kept for backwards compatibility)
      stopped_early?: boolean; // Reply cut off by the tool-round cap
      stop_reason?: 'user'; // The user pressed Stop (partial reply kept)
      unanswered_steering_id?: string; // Steering the turn never read (now after the reply)
    }
  | { type: 'error'; message: string; code?: string; retryable?: boolean }
) & {
  /** Journal sequence number for resumable streams (resume with after_seq) */
  seq?: number;
};

// =============================================================================
// UI State types (frontend-only)
// =============================================================================

export interface ThinkingTraceItem {
  type: 'thinking' | 'tool';
  label: string;
  detail?: string | undefined; // reassigned in place as tool args stream in; undefined clears it
  completed: boolean;
  metadata?: ToolMetadata; // Backend-provided display metadata (label, icon)
}

export interface ThinkingState {
  isThinking: boolean;
  thinkingText: string;
  activeTool: string | null;
  activeToolDetail?: string | undefined; // set to undefined when the active tool ends
  completedTools: string[];
  trace: ThinkingTraceItem[];
}

// =============================================================================
// API Response types
// =============================================================================

export type AuthResponse = Schemas['AuthResponse'];

// =============================================================================
// Pagination types
// =============================================================================

export type ConversationsPagination =
  Schemas['ConversationsListPaginatedResponse.ConversationsPaginationResponse'];

export type MessagesPagination = Schemas['MessagesListResponse.MessagesPaginationResponse'];

/** Hand-written: conversations.list() normalizes each raw summary into a Conversation */
export interface ConversationsResponse {
  conversations: Conversation[];
  pinned_conversations?: Conversation[];
  pagination: ConversationsPagination;
}

/** The spec types messages loosely (research is an open dict); the client reads them as Message */
export type ConversationDetailResponse = Omit<
  Schemas['ConversationDetailPaginatedResponse'],
  'messages'
> & {
  messages: Message[];
};

export type MessagesResponse = Omit<Schemas['MessagesListResponse'], 'messages'> & {
  messages: Message[];
};

export type ModelsResponse = Omit<Schemas['ModelsListResponse'], 'models'> & {
  models: Model[];
};

/** Hand-written: the batch reply's fields go straight into a Message (optional, not null) */
export interface ChatResponse {
  id: string;
  role: 'assistant';
  content: string;
  files?: FileMetadata[];
  sources?: Source[];
  generated_images?: GeneratedImage[];
  language?: string; // ISO 639-1 language code for TTS
  created_at: string;
  title?: string;
  user_message_id?: string; // Real ID of the user message (for updating temp IDs)
  stopped_early?: boolean; // Reply cut off by the tool-round cap
  annotations?: ClaimAnnotation[]; // Grounding-check claims
  grounding?: GroundingSummary; // Grounding-check footer summary
  stop_reason?: 'user'; // The user pressed Stop (partial reply kept)
  model_fallback?: string; // Model that answered when the conversation's model was down
  research?: MessageResearch; // Deep-research offer or run
  artifacts?: ArtifactRef[]; // Artifact versions shown under the reply
  message_count?: number; // The conversation's message count after this turn (sync baseline)
  unanswered_steering_id?: string | null; // Steering the turn never read (now after the reply)
}

/** The server's error envelope; the spec's HTTPError (APIFlask's default) does not describe it */
export interface ErrorResponse {
  error: string | {
    code: string;
    message: string;
    retryable?: boolean;
    details?: Record<string, unknown>;
  };
}

export type VersionResponse = Schemas['VersionResponse'];

// =============================================================================
// Cost tracking types
// =============================================================================

export type ConversationCostResponse = Schemas['ConversationCostResponse'];

export type MessageCostResponse = Schemas['MessageCostResponse'];

export type ConversationCompactionResponse = Schemas['ConversationCompactionResponse'];

export type MonthlyCostResponse = Schemas['MonthlyCostResponse'];

export type CostHistoryResponse = Schemas['CostHistoryResponse'];

// =============================================================================
// Sync types
// =============================================================================

// ConversationSummary and SyncResponse stay hand-written: the spec sends every
// field, but SyncManager still branches on missing ones (read_count, pinned,
// anonymous_mode, cursor, ...) and its tests drive those fallbacks.

export interface ConversationSummary {
  id: string;
  title: string;
  model: string;
  created_at?: string | null;
  updated_at: string;
  message_count: number;
  read_count?: number; // Shown on any of the user's devices (shared unread state)
  last_message_preview?: string | null;
  last_message_id?: string | null; // Newest message (detects edits/deletes)
  archived?: boolean;
  trashed?: boolean; // In the trash
  pinned?: boolean;
  anonymous_mode?: boolean; // Memory and integrations off (adopted across devices)
}

export interface SyncResponse {
  conversations: ConversationSummary[];
  server_time: string;
  is_full_sync: boolean;
  cursor?: number; // Change-log position for the next ?cursor= sync
  removed_ids?: string[]; // Permanently deleted since the cursor
  has_more?: boolean; // More changes after cursor - sync again
}

// =============================================================================
// Memory types
// =============================================================================

/** `protected`: only the user can remove it; `source_conversation_id`: where it was learned */
export type Memory = Schemas['MemoriesListResponse.MemoryResponse'];

/** `limit`: server-side cap on stored memories */
export type MemoriesResponse = Schemas['MemoriesListResponse'];

// =============================================================================
// Settings types
// =============================================================================

/** `time`: delivery time as HH:MM (24h) in `timezone` */
export type DailyBriefingSettings = Schemas['UserSettingsResponse.DailyBriefingSettings'];

/** `preferred_language`: English name (e.g. "Czech"); null/"" = auto */
export type UserSettings = Schemas['UserSettingsResponse'];

// =============================================================================
// Todoist types
// =============================================================================

export type TodoistAuthUrl = Schemas['TodoistAuthUrlResponse'];

export type TodoistConnectResponse = Schemas['TodoistConnectResponse'];

export type TodoistStatus = Schemas['TodoistStatusResponse'];

// =============================================================================
// Google Calendar types
// =============================================================================

export type CalendarAuthUrl = Schemas['GoogleCalendarAuthUrlResponse'];

export type CalendarConnectResponse = Schemas['GoogleCalendarConnectResponse'];

export type CalendarStatus = Schemas['GoogleCalendarStatusResponse'];

export type Calendar = Schemas['CalendarListResponse.Calendar'];

export type CalendarListResponse = Schemas['CalendarListResponse'];

export type SelectedCalendarsResponse = Schemas['SelectedCalendarsResponse'];

/** POST /api/conversations/bulk-trash: hand-picked ids, or all (minus exclude_ids, plus ids) */
export type BulkTrashRequest = Schemas['BulkTrashRequest'];

// =============================================================================
// Garmin Connect types
// =============================================================================

export type GarminConnectResponse = Schemas['GarminConnectResponse'];

export type GarminStatus = Schemas['GarminStatusResponse'];

// =============================================================================
// Search types
// =============================================================================

export type SearchResult = Schemas['SearchResultsResponse.SearchResultResponse'];

export type SearchResponse = Schemas['SearchResultsResponse'];

// =============================================================================
// Planner types
// =============================================================================

export type PlannerTask = Schemas['PlannerDashboardResponse.PlannerTaskResponse'];

export type PlannerEvent = Schemas['PlannerDashboardResponse.PlannerEventResponse'];

/** The spec types the Garmin blocks as open dicts; these are the keys the planner reads */
export type PlannerHealthSummary = Omit<
  Schemas['PlannerDashboardResponse.PlannerHealthSummaryResponse'],
  'training_readiness' | 'sleep' | 'recent_activities'
> & {
  training_readiness: { score?: number; level?: string } | null;
  sleep: { duration_hours?: number; quality?: string } | null;
  recent_activities: Array<{ name?: string; date?: string; distance_km?: number; duration_min?: number }>;
};

export type PlannerDay = Schemas['PlannerDashboardResponse.PlannerDayResponse'];

export type PlannerDashboard = Omit<Schemas['PlannerDashboardResponse'], 'health_summary'> & {
  health_summary: PlannerHealthSummary | null;
};

export type PlannerConversation = Omit<Schemas['PlannerConversationResponse'], 'messages'> & {
  messages: Message[];
};

export type PlannerResetResponse = Schemas['PlannerResetResponse'];

export type PlannerSyncResponse = Schemas['PlannerSyncResponse'];

// =============================================================================
// Autonomous Agent types
// =============================================================================

/**
 * `budget_limit`: daily USD limit (null = unlimited); `system_type`: system-managed
 * agent marker ('daily_briefing', ...); `effective_system_prompt`: the stock default
 * for a system-managed agent with a NULL prompt; `daily_spending`: today's USD
 */
export type Agent = Schemas['AgentResponse'];

export type CreateAgentRequest = Schemas['CreateAgentRequest'];

export type UpdateAgentRequest = Schemas['UpdateAgentRequest'];

export type AgentExecution = Schemas['AgentExecutionsListResponse.AgentExecutionResponse'];

export type ApprovalRequest = Schemas['PendingApprovalsResponse.ApprovalRequestResponse'];

export type AgentsListResponse = Schemas['AgentsListResponse'];

export type AgentExecutionsListResponse = Schemas['AgentExecutionsListResponse'];

/** `cost_display`: cost formatted in the display currency (e.g. "12.40 Kč") */
export type AgentWindowStats = Schemas['CommandCenterResponse.AgentWindowStats'];

export type AgentStatsBlock = Schemas['CommandCenterResponse.AgentStatsBlock'];

export type CommandCenterResponse = Schemas['CommandCenterResponse'];

export type TriggerAgentResponse = Schemas['TriggerAgentResponse'];

export type AgentConversationSyncResponse = Schemas['AgentConversationSyncResponse'];

// =============================================================================
// KV Store types
// =============================================================================

export type KVNamespacesResponse = Schemas['KVNamespacesResponse'];

export type KVKeysResponse = Schemas['KVKeysResponse'];

export type KVValueResponse = Schemas['KVValueResponse'];

// =============================================================================
// Sports types
// =============================================================================

/**
 * A one-tap saved prompt for a program conversation (sports, language).
 * `fields`: ordered labels asked for before sending; answers append as `Label: value`.
 * The server always sends `fields`; the spec marks it optional because the item
 * model is shared with the update request.
 */
export type QuickAction = Required<Schemas['SportsProgramsResponse.QuickActionItem']>;

export type SportsProgram = Omit<Schemas['SportsProgramsResponse.SportsProgramItem'], 'quick_actions'> & {
  quick_actions: QuickAction[];
};

export type SportsProgramsResponse = Omit<Schemas['SportsProgramsResponse'], 'programs'> & {
  programs: SportsProgram[];
};

export type SportsConversation = Omit<Schemas['SportsConversationResponse'], 'messages'> & {
  messages: Message[];
};

export type SportsResetResponse = Schemas['SportsResetResponse'];

// =============================================================================
// Language Learning types
// =============================================================================

export type LanguageProgram = Omit<
  Schemas['LanguageProgramsResponse.LanguageProgramItem'],
  'quick_actions'
> & {
  quick_actions: QuickAction[];
};

export type LanguageProgramsResponse = Omit<Schemas['LanguageProgramsResponse'], 'programs'> & {
  programs: LanguageProgram[];
};

export type LanguageConversation = Omit<Schemas['LanguageConversationResponse'], 'messages'> & {
  messages: Message[];
};

export type LanguageResetResponse = Schemas['LanguageResetResponse'];

// =============================================================================
// AI Assist types
// =============================================================================

export type ParseScheduleResponse = Schemas['ParseScheduleResponse'];

export type EnhancePromptRequest = Schemas['EnhancePromptRequest'];

export type EnhancePromptResponse = Schemas['EnhancePromptResponse'];
