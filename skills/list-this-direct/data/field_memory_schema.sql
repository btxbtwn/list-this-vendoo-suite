PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS field_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL,
  context_key TEXT NOT NULL DEFAULT 'global',
  field_slug TEXT NOT NULL,
  field_key TEXT,
  field_label TEXT,
  widget_type TEXT NOT NULL DEFAULT 'unknown',
  source_scope TEXT NOT NULL DEFAULT 'global',
  source TEXT NOT NULL,
  notes TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE(platform, context_key, field_slug)
);

CREATE INDEX IF NOT EXISTS idx_field_entries_platform_context
  ON field_entries(platform, context_key);

CREATE INDEX IF NOT EXISTS idx_field_entries_field_key
  ON field_entries(platform, field_key);

CREATE TABLE IF NOT EXISTS field_options (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id INTEGER NOT NULL REFERENCES field_entries(id) ON DELETE CASCADE,
  option_value TEXT NOT NULL,
  option_normalized TEXT NOT NULL,
  source TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  observed_count INTEGER NOT NULL DEFAULT 0,
  commit_count INTEGER NOT NULL DEFAULT 0,
  reject_count INTEGER NOT NULL DEFAULT 0,
  is_seeded INTEGER NOT NULL DEFAULT 0,
  UNIQUE(entry_id, option_normalized)
);

CREATE INDEX IF NOT EXISTS idx_field_options_entry
  ON field_options(entry_id);

CREATE TABLE IF NOT EXISTS field_patterns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id INTEGER NOT NULL REFERENCES field_entries(id) ON DELETE CASCADE,
  pattern_key TEXT NOT NULL,
  pattern_kind TEXT NOT NULL DEFAULT 'interaction',
  pattern_text TEXT NOT NULL,
  source TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  success_count INTEGER NOT NULL DEFAULT 0,
  failure_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE(entry_id, pattern_key, pattern_kind)
);

CREATE INDEX IF NOT EXISTS idx_field_patterns_entry
  ON field_patterns(entry_id);

CREATE TABLE IF NOT EXISTS field_preferences (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id INTEGER NOT NULL REFERENCES field_entries(id) ON DELETE CASCADE,
  preference_kind TEXT NOT NULL,
  value_text TEXT NOT NULL,
  reason TEXT,
  source TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  success_count INTEGER NOT NULL DEFAULT 0,
  failure_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE(entry_id, preference_kind, value_text)
);

CREATE INDEX IF NOT EXISTS idx_field_preferences_entry
  ON field_preferences(entry_id);

CREATE TABLE IF NOT EXISTS field_runs (
  run_id TEXT PRIMARY KEY,
  observed_at TEXT NOT NULL,
  source TEXT NOT NULL,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS field_observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES field_runs(run_id) ON DELETE CASCADE,
  entry_id INTEGER NOT NULL REFERENCES field_entries(id) ON DELETE CASCADE,
  trace_step_goal TEXT,
  target_ui TEXT,
  visible_options_json TEXT,
  attempted_value TEXT,
  committed_value TEXT,
  interaction_pattern TEXT,
  save_outcome TEXT,
  blockers TEXT,
  confidence TEXT,
  observed_at TEXT NOT NULL,
  source TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_field_observations_run
  ON field_observations(run_id);

CREATE INDEX IF NOT EXISTS idx_field_observations_entry
  ON field_observations(entry_id);
