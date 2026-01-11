-- Add dashboard cache table and last_reset column
-- depends: 0020_add_planner_support

-- Add last_reset column to conversations table for planner reset tracking
ALTER TABLE conversations ADD COLUMN last_reset TEXT;

-- Dashboard cache for multi-worker support
-- Stores serialized dashboard data with TTL expiration
CREATE TABLE IF NOT EXISTS dashboard_cache (
  user_id TEXT PRIMARY KEY,
  dashboard_data TEXT NOT NULL,  -- JSON serialized PlannerDashboard
  cached_at TEXT NOT NULL,       -- ISO timestamp when cached
  expires_at TEXT NOT NULL       -- ISO timestamp for TTL
);

-- Index for efficient cleanup of expired entries
CREATE INDEX IF NOT EXISTS idx_dashboard_cache_expires
ON dashboard_cache(expires_at);
