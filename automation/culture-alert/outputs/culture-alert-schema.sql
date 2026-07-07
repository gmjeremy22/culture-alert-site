PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS institutions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  region TEXT NOT NULL,
  city TEXT,
  category TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 3,
  collection_phase TEXT NOT NULL DEFAULT 'phase3',
  exhibition_url TEXT,
  program_url TEXT,
  notes TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cultural_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id INTEGER NOT NULL,
  content_type TEXT NOT NULL DEFAULT '전시',
  title TEXT NOT NULL,
  start_date TEXT,
  end_date TEXT,
  location TEXT,
  region TEXT,
  price TEXT,
  description TEXT,
  keywords TEXT,
  event_nature TEXT NOT NULL DEFAULT 'unknown',
  image_url TEXT,
  source_url TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '확인필요',
  raw_text TEXT,
  collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (institution_id) REFERENCES institutions(id),
  UNIQUE (institution_id, title, start_date, source_url)
);

CREATE TABLE IF NOT EXISTS interests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  person_name TEXT NOT NULL,
  keyword TEXT NOT NULL,
  weight INTEGER NOT NULL DEFAULT 1,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (person_name, keyword)
);

CREATE TABLE IF NOT EXISTS recommendations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL,
  person_name TEXT NOT NULL,
  score REAL NOT NULL DEFAULT 0,
  matched_keywords TEXT,
  reason TEXT,
  generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (event_id) REFERENCES cultural_events(id)
);

CREATE TABLE IF NOT EXISTS event_keywords (
  event_id INTEGER NOT NULL,
  keyword TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'rule',
  weight INTEGER NOT NULL DEFAULT 1,
  evidence TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (event_id) REFERENCES cultural_events(id),
  UNIQUE (event_id, keyword)
);

CREATE TABLE IF NOT EXISTS related_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL,
  link_type TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  source TEXT NOT NULL,
  rank INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (event_id) REFERENCES cultural_events(id),
  UNIQUE (event_id, link_type, url)
);

CREATE TABLE IF NOT EXISTS event_occurrences (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL,
  occurrence_date TEXT NOT NULL,
  start_time TEXT,
  end_time TEXT,
  label TEXT,
  note TEXT,
  source_url TEXT,
  confidence INTEGER NOT NULL DEFAULT 5,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (event_id) REFERENCES cultural_events(id),
  UNIQUE (event_id, occurrence_date, start_time, label)
);

CREATE TABLE IF NOT EXISTS event_candidates (
  candidate_id TEXT PRIMARY KEY,
  institution_name TEXT,
  region TEXT,
  city TEXT,
  category TEXT,
  tier TEXT,
  content_type TEXT,
  title TEXT,
  start_date TEXT,
  end_date TEXT,
  image_url TEXT,
  source_url TEXT,
  page_url TEXT,
  confidence REAL,
  reason TEXT,
  snippet TEXT,
  extracted_at TEXT,
  collection_group TEXT,
  review_status TEXT,
  validation_score REAL,
  validation_reasons TEXT,
  merged_event_id INTEGER,
  merge_note TEXT,
  reviewed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_institutions_phase ON institutions(collection_phase, priority);
CREATE INDEX IF NOT EXISTS idx_events_dates ON cultural_events(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_events_status ON cultural_events(status);
CREATE INDEX IF NOT EXISTS idx_events_institution ON cultural_events(institution_id);
CREATE INDEX IF NOT EXISTS idx_events_nature ON cultural_events(event_nature);
CREATE INDEX IF NOT EXISTS idx_interests_person ON interests(person_name, active);
CREATE INDEX IF NOT EXISTS idx_event_keywords_keyword ON event_keywords(keyword, weight);
CREATE INDEX IF NOT EXISTS idx_event_keywords_event ON event_keywords(event_id);
CREATE INDEX IF NOT EXISTS idx_related_links_event ON related_links(event_id, rank);
CREATE INDEX IF NOT EXISTS idx_event_occurrences_event ON event_occurrences(event_id, occurrence_date);
CREATE INDEX IF NOT EXISTS idx_event_candidates_institution ON event_candidates(institution_name);
CREATE INDEX IF NOT EXISTS idx_event_candidates_dates ON event_candidates(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_event_candidates_review ON event_candidates(review_status, validation_score);
