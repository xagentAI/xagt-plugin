PRAGMA foreign_keys = ON;

CREATE TABLE api_keys (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  scopes TEXT NOT NULL,
  daily_limit INTEGER NOT NULL DEFAULT 50 CHECK (daily_limit > 0),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE api_key_usage (
  api_key_id TEXT NOT NULL,
  usage_day TEXT NOT NULL,
  call_count INTEGER NOT NULL DEFAULT 0 CHECK (call_count >= 0),
  PRIMARY KEY (api_key_id, usage_day),
  FOREIGN KEY (api_key_id) REFERENCES api_keys(id) ON DELETE CASCADE
);

CREATE TABLE idempotency_records (
  api_key_id TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  response_status INTEGER,
  response_body TEXT,
  state TEXT NOT NULL CHECK (state IN ('processing', 'complete')),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  PRIMARY KEY (api_key_id, endpoint, idempotency_key),
  FOREIGN KEY (api_key_id) REFERENCES api_keys(id) ON DELETE CASCADE
);

CREATE TABLE missions (
  id TEXT PRIMARY KEY,
  api_key_id TEXT NOT NULL,
  source_url TEXT NOT NULL,
  destination_url TEXT NOT NULL,
  source_digest TEXT NOT NULL,
  objective TEXT NOT NULL,
  platform TEXT NOT NULL,
  locale TEXT NOT NULL,
  target_value REAL NOT NULL CHECK (target_value > 0),
  measurement_window_days INTEGER NOT NULL CHECK (measurement_window_days > 0),
  measurement_started_at TEXT NOT NULL,
  measurement_due_at TEXT NOT NULL,
  result_json TEXT NOT NULL,
  tracking_code TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  FOREIGN KEY (api_key_id) REFERENCES api_keys(id) ON DELETE CASCADE
);

CREATE INDEX missions_api_key_created_idx ON missions(api_key_id, created_at DESC);
CREATE INDEX missions_expires_idx ON missions(expires_at);

CREATE TABLE outcome_events (
  id TEXT PRIMARY KEY,
  mission_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  outcome_type TEXT NOT NULL CHECK (outcome_type IN ('click', 'lead', 'signup', 'purchase', 'revenue')),
  quantity REAL NOT NULL CHECK (quantity > 0),
  value REAL,
  currency TEXT,
  occurred_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (mission_id, event_id),
  FOREIGN KEY (mission_id) REFERENCES missions(id) ON DELETE CASCADE
);

CREATE INDEX outcome_events_mission_idx ON outcome_events(mission_id, occurred_at);

CREATE TABLE tracking_daily (
  mission_id TEXT NOT NULL,
  event_day TEXT NOT NULL,
  clicks INTEGER NOT NULL DEFAULT 0 CHECK (clicks >= 0),
  PRIMARY KEY (mission_id, event_day),
  FOREIGN KEY (mission_id) REFERENCES missions(id) ON DELETE CASCADE
);
