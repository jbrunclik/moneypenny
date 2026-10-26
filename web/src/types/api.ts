/**
 * API types for the Moneypenny frontend.
 *
 * API types are aliases of the schemas generated from the OpenAPI spec
 * (generated-api.ts, `make types`), extended only for frontend-only fields
 * such as previewUrl (F6). Hand-written types remain for client state
 * (Conversation), SSE event shapes and what the spec types as an open dict
 * (the deep-research data, the planner's Garmin blocks). A test catches a
 * hand-written copy of a schema (web/tests/unit/api-types.test.ts).
 */

// Re-export generated types for reference and test validation
export type { components } from './generated-api';

type Schemas = import('./generated-api').components['schemas'];

/** Keys of T whose value may be null */
type NullableKeys<T> = { [K in keyof T]-?: null extends T[K] ? K : never }[keyof T];

/**
 * A response schema as the client holds it: a field the server may send as
 * null may also be missing - the SSE done event (not in the spec) leaves out
 * what it lacks, and so do the messages the client builds itself.
 */
type MaybeAbsent<T> = Omit<T, NullableKeys<T>> & Partial<Pick<T, NullableKeys<T>>>;

// Admin page and spend status (S12)
export type AdminOverview = Schemas['AdminOverviewResponse'];
export type SpendStatus = Schemas['SpendStatusResponse'];
// Device check runner (admin page)
export type DeviceCheckRun = Schemas['DeviceCheckRun'];
export type DeviceCheckRunRequest = Schemas['DeviceCheckRunRequest'];
export type DeviceCheckScenarioResult = Schemas['DeviceCheckRunRequest.DeviceCheckScenarioResult'];
export type DeviceCheckStatus = Schemas['DeviceCheckRun.DeviceCheckStatus'];
export type DeviceCheckMeasurements = Schemas['DeviceCheckRunRequest.Measurements'];
export type DeviceCheckFixture = Schemas['DeviceCheckFixtureResponse'];

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

export type GeneratedImage = MaybeAbsent<Schemas['MessageResponse.GeneratedImageResponse']> & {
  message_id?: string; // client-only: the message the image info popup is for
};

/** The message fields whose schema the client narrows (the spec types research as an open dict) */
type MessagePartKeys = 'files' | 'generated_images' | 'annotations' | 'grounding' | 'research';

interface MessageParts {
  files?: FileMetadata[] | null;
  generated_images?: GeneratedImage[] | null;
  /** Grounding-check claims (src/agent/grounding_annotations.py) */
  annotations?: ClaimAnnotation[] | null;
  grounding?: GroundingSummary | null;
  /** Deep-research offer or run (src/agent/deep_research/) */
  research?: MessageResearch | null;
}

/**
 * A message in the store: the server's MessageResponse (sent with nulls; the
 * SSE done event and the client's own messages leave fields out instead).
 */
export type Message = Omit<MaybeAbsent<Schemas['MessageResponse']>, MessagePartKeys> &
  MessageParts & {
    /** Client-only send state; never sent by the server (absent = delivered) */
    status?: 'pending' | 'failed' | undefined; // patched to undefined (updateMessage) to clear it
  };

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

/** What a user message sent on the user's behalf was (rendered as an action row) */
export type MessageAction = NonNullable<Schemas['MessageResponse']['action']>;

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

/**
 * One claim of an answer and how the turn's sources bear on it. `quote` is a
 * literal phrase of the message's markdown, `prefix` the text right before it
 * (picks among repeats), `source` a 1-based index into the message's sources.
 * The SSE done event leaves out the fields a claim lacks.
 */
export type ClaimAnnotation = MaybeAbsent<Schemas['MessageResponse.ClaimAnnotationResponse']>;

export type ClaimVerdict = ClaimAnnotation['verdict'];

/** `legacy`: converted from the pre-Oct-3-2026 inline markers (no reasons or total) */
export type GroundingSummary = MaybeAbsent<Schemas['MessageResponse.GroundingSummaryResponse']>;

// =============================================================================
// File types
// =============================================================================

export type FileMetadata = MaybeAbsent<Schemas['MessageResponse.FileMetadataResponse']> & {
  previewUrl?: string; // blob URL for immediate display (local uploads only)
};

/** `data` is base64 */
export type FileUpload = Schemas['ChatRequest.FileAttachment'] & {
  previewUrl?: string; // blob URL for local preview
};

/**
 * Device GPS fix attached to chat requests when location sharing is enabled.
 * The request lets timestamp_ms be omitted; the client always sets it and
 * reads it back to age its cached fix.
 */
export type ClientLocation = Schemas['ChatRequest.ClientLocation'] & {
  accuracy_m: number | null;
  timestamp_ms: number;
};

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
  | ({ type: 'done' } & StreamDoneEvent)
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

/** conversations.list() turns each raw summary into a Conversation */
export type ConversationsResponse = Schemas['ConversationsListPaginatedResponse'];

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

/** The batch reply (the spec types research as an open dict) */
export type ChatResponse = Omit<Schemas['ChatBatchResponse'], 'research'> & {
  research: MessageResearch | null;
};

/**
 * Payload of the stream's terminal `done` event: the batch reply's fields,
 * left out instead of null, plus the approval marker. `content` is missing
 * on an approval request.
 */
export type StreamDoneEvent = Omit<
  MaybeAbsent<ChatResponse>,
  'role' | 'content' | 'model_fallback' | MessagePartKeys
> &
  MessageParts & {
  content?: string;
  approval_required?: boolean;
  approval_id?: string;
};

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

// The server sends every sync field, but SyncManager still has fallbacks for
// a missing read_count, pinned, anonymous_mode or cursor (the pre-shared-read
// unread tracking and the legacy timestamp sync) and its tests drive them, so
// those keys stay optional until the fallbacks go (TODO.md, F6).
type SyncFallbackKeys = 'created_at' | 'read_count' | 'last_message_preview' | 'last_message_id' | 'archived' | 'trashed' | 'pinned' | 'anonymous_mode';

/** `read_count`: messages shown on any of the user's devices; `last_message_id` detects edits/deletes */
export type ConversationSummary = Omit<Schemas['SyncResponse.SyncConversationResponse'], SyncFallbackKeys> &
  Partial<Pick<Schemas['SyncResponse.SyncConversationResponse'], SyncFallbackKeys>>;

/** `cursor`: change-log position for the next ?cursor= sync; `has_more`: sync again */
export type SyncResponse = Omit<Schemas['SyncResponse'], 'conversations' | 'cursor' | 'removed_ids' | 'has_more'> &
  Partial<Pick<Schemas['SyncResponse'], 'cursor' | 'removed_ids' | 'has_more'>> & {
    conversations: ConversationSummary[];
  };

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
// Rouvy types
// =============================================================================

export type RouvyConnectResponse = Schemas['RouvyConnectResponse'];

export type RouvyStatus = Schemas['RouvyStatusResponse'];

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
 */
export type QuickAction = Schemas['SportsProgramsResponse.QuickActionResponse'];

export type SportsProgram = Schemas['SportsProgramsResponse.SportsProgramItem'];

export type SportsProgramsResponse = Schemas['SportsProgramsResponse'];

export type SportsConversation = Omit<Schemas['SportsConversationResponse'], 'messages'> & {
  messages: Message[];
};

export type SportsResetResponse = Schemas['SportsResetResponse'];

// =============================================================================
// Language Learning types
// =============================================================================

export type LanguageProgram = Schemas['LanguageProgramsResponse.LanguageProgramItem'];

export type LanguageProgramsResponse = Schemas['LanguageProgramsResponse'];

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
