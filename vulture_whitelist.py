# ruff: noqa
# type: ignore
"""Names vulture (C2, `make lint`) can't see being used. Only parsed, never run.

A new finding is either dead (delete it) or belongs to one of these sections,
each with its reason. There is no baseline: dead code is deleted.
"""

# --- API wire format: Pydantic fields and StrEnum members, read by the client
# and by (de)serialization, never as Python attributes --------------------------
# src/api/schemas/admin.py
month_chats
month_turns
over_threshold
daily
by_feature
by_model
runs_7d
failed_7d
recent_failures
providers
turns_7d
median_ms
p95_ms
tool_error_rate
database_bytes
files_bytes
last_backup_at
latest_migration
last_seen
generated_at
spend
browser_errors
layout_checks
standalone_count
threshold_usd
# src/api/schemas/agents.py
RUNNING
COMPLETED
WAITING_APPROVAL
SCHEDULED
MANUAL
AGENT_TRIGGER
APPROVED
REJECTED
effective_system_prompt
completed
total_cost_display
recent_executions
enhanced_prompt
# src/api/schemas/auth.py
client_id
# src/api/schemas/base.py (Pydantic reads it)
model_config
# src/api/schemas/chat.py
accuracy_m
timestamp_ms
source_message_id
claim_index
model_fallback  # also a LangGraph state key (src/agent/graph_state.py)
# src/api/schemas/client_errors.py
ERROR
UNHANDLED_REJECTION
LOGGED
COMPOSER_GAP
STRANDED_PAN
INSET_MISMATCH
ANCHOR_DRIFT
SCROLL_BOTTOM_MISS
# src/api/schemas/conversations.py
read_count
purge_at
trashed_ids
restored_ids
removed_ids
pinned_conversations
message_pagination
lost_reply
message_snippet
# src/api/schemas/costs.py
active
boundary_message_id
image_generation_cost_formatted
# src/api/schemas/files.py
messageId
fileIndex
image_index
# src/api/schemas/integrations.py
mfa_required
access_role
background_color
# src/api/schemas/kv_store.py
key_count
# src/api/schemas/programs.py
has_conversation
# src/api/schemas/system.py
short_name
maxFileSize
maxVideoFileSize
maxFilesPerMessage
allowedFileTypes
# src/enums.py: parsed from the `direction` query parameter
NEWER

# --- Serialized dataclass fields and TypedDict keys (asdict / JSON caches /
# dict access) ---------------------------------------------------------------
session_gap  # src/agent/history.py MessageMetadata
created_by_message_id  # src/db/models/dataclasses.py: rows mirror their table
last_viewed_at
last_used_at
hrv_status  # src/services/planner/models.py PlannerHealthSummary
_.hrv_status
# Never set, but cached dashboards carry the key and PlannerHealthSummary(**data)
# would reject them without the field
training_status
wind_speed  # src/utils/weather.py WeatherPeriod / WeatherForecast
wind_direction
cloud_coverage
fetched_at

# --- Framework interfaces -----------------------------------------------------
_.row_factory  # sqlite3.Connection
raise_error  # langchain BaseCallbackHandler (src/agent/cancellation.py)
_.on_llm_new_token
_.base_exceptions  # limits Storage (src/utils/rate_limit_storage.py)
_.incr
_.get_expiry
_.ignore_links  # html2text.HTML2Text options (src/agent/tools/web.py)
_.ignore_images
_.ignore_emphasis
_.body_width
# src/agent/tools/browser_worker.py: dispatched as getattr(self, f"_do_{name}")
_._do_navigate
_._do_click
_._do_type
_._do_screenshot
_._do_extract
_._do_scroll
_._do_back
_._do_close
_._do_cleanup_stale
# Env vars read by the systemd unit / gunicorn command line, declared in
# Config like every other setting
GUNICORN_WORKERS
GUNICORN_THREADS
GUNICORN_TIMEOUT
GUNICORN_MAX_REQUESTS
GUNICORN_MAX_REQUESTS_JITTER
# tests/e2e_server: signal handler signature, Mock configuration
signum
_.__enter__
_.__exit__
_.return_value
_.side_effect

# --- Test seams: reset or inspect module state from tests ---------------------
reset_slots  # src/agent/deep_research/orchestrator.py
clear_cached_clients  # src/agent/gemini_clients.py
clear_graph_cache  # src/agent/graph_cache.py
clear_sessions  # src/agent/tools/garmin_session.py
stop_malloc_trimmer  # src/utils/malloc_trim.py
_.connection_count  # src/utils/connection_pool.py
_.peek  # src/utils/lazy.py (tests/conftest.py)
_._validated_body  # src/api/validation.py: the OpenAPI/query tests find views by it
_._validated_query

# --- Staged rollout: shipped ahead of their callers ---------------------------
# Timezone migration step 2a (docs/superpowers/specs/2026-10-26-timezone-aware-
# datetimes-design.md): step 2b moves the app onto them, then drop these lines
local_today  # src/utils/clock.py
local_day_start
local_month_bounds
planner_cutoff
normalize_cursor  # src/db/models/timestamps.py
