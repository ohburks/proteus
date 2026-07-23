-- Dual-RAG Rubric Grading System — relational schema (source of truth for excerpt content)
-- See dual-rag-grading-design.md for the design this implements.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin','instructor')),
  instructor_id TEXT,
  theme_preference TEXT NOT NULL DEFAULT 'system' CHECK (theme_preference IN ('system','light','dark')),
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rubrics (
  rubric_id TEXT NOT NULL,
  version TEXT NOT NULL,
  genre TEXT,
  notes TEXT,
  assignment_guidance TEXT,
  raw_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (rubric_id, version)
);

CREATE TABLE IF NOT EXISTS criteria (
  rubric_id TEXT NOT NULL,
  rubric_version TEXT NOT NULL,
  criterion_id TEXT NOT NULL,
  standard TEXT,
  dimension TEXT,
  statement TEXT NOT NULL,
  scale TEXT,
  referenceability TEXT,
  source TEXT,
  anchors_json TEXT NOT NULL,
  PRIMARY KEY (rubric_id, rubric_version, criterion_id),
  FOREIGN KEY (rubric_id, rubric_version) REFERENCES rubrics(rubric_id, version)
);

-- Full text of the source essays exemplar excerpts are quoted from, kept so
-- ingestion-time evidence verification (§3.5) has something to check against.
CREATE TABLE IF NOT EXISTS exemplar_source_essays (
  source_essay_id TEXT PRIMARY KEY,
  text TEXT NOT NULL
);

-- Exemplar corpus (source of truth; mirrors into exemplar_excerpts Chroma collection)
CREATE TABLE IF NOT EXISTS exemplar_excerpts_src (
  id TEXT PRIMARY KEY,
  rubric_id TEXT NOT NULL,
  rubric_version TEXT NOT NULL,
  criterion_id TEXT NOT NULL,
  excerpt_text TEXT NOT NULL,
  score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 5),
  anchor_matched INTEGER NOT NULL CHECK (anchor_matched BETWEEN 0 AND 5),
  rationale TEXT NOT NULL,
  source_essay_id TEXT NOT NULL,
  is_preseeded INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_exemplar_excerpts_lookup
  ON exemplar_excerpts_src (rubric_id, rubric_version, criterion_id);

-- Personalized corpus (source of truth; mirrors into personalized_excerpts Chroma collection)
CREATE TABLE IF NOT EXISTS personalized_excerpts_src (
  id TEXT PRIMARY KEY,
  rubric_id TEXT NOT NULL,
  criterion_id TEXT NOT NULL,
  instructor_id TEXT NOT NULL,
  course_id TEXT,
  assignment_id TEXT,
  excerpt_text TEXT NOT NULL,
  score INTEGER NOT NULL CHECK (score BETWEEN 0 AND 5),
  anchor_matched INTEGER NOT NULL CHECK (anchor_matched BETWEEN 0 AND 5),
  rationale TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('imported','manual','review_writeback')),
  added_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_personalized_excerpts_scope
  ON personalized_excerpts_src (instructor_id, rubric_id, criterion_id, course_id, assignment_id);

CREATE TABLE IF NOT EXISTS divergence_thresholds (
  instructor_id TEXT NOT NULL,
  rubric_id TEXT NOT NULL,
  criterion_id TEXT NOT NULL,
  threshold INTEGER NOT NULL CHECK (threshold BETWEEN 0 AND 5),
  updated_at TEXT NOT NULL,
  PRIMARY KEY (instructor_id, rubric_id, criterion_id)
);

-- Threshold for flagging a path's OWN multi-pass spread as high (i.e. the
-- model was inconsistent with itself across its N sampling passes). Distinct
-- from divergence_thresholds above, which gates disagreement BETWEEN the two
-- paths — these two signals are never allowed to merge.
CREATE TABLE IF NOT EXISTS spread_thresholds (
  instructor_id TEXT NOT NULL,
  rubric_id TEXT NOT NULL,
  criterion_id TEXT NOT NULL,
  threshold REAL NOT NULL CHECK (threshold BETWEEN 0 AND 5),
  updated_at TEXT NOT NULL,
  PRIMARY KEY (instructor_id, rubric_id, criterion_id)
);

CREATE TABLE IF NOT EXISTS pool_thresholds (
  instructor_id TEXT NOT NULL,
  rubric_id TEXT NOT NULL,
  criterion_id TEXT,  -- NULL = default applies to all criteria
  min_scoped_pool_size INTEGER NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (instructor_id, rubric_id, criterion_id)
);

CREATE TABLE IF NOT EXISTS courses (
  id TEXT PRIMARY KEY,
  instructor_id TEXT NOT NULL,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assignments (
  id TEXT PRIMARY KEY,
  course_id TEXT NOT NULL REFERENCES courses(id),
  name TEXT NOT NULL,
  rubric_id TEXT NOT NULL,
  rubric_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS students (
  id TEXT PRIMARY KEY,
  instructor_id TEXT NOT NULL,
  course_id TEXT REFERENCES courses(id),
  display_name TEXT NOT NULL,
  external_ref TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS essays (
  id TEXT PRIMARY KEY,
  assignment_id TEXT NOT NULL REFERENCES assignments(id),
  student_id TEXT REFERENCES students(id),
  text TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assessments (
  id TEXT PRIMARY KEY,
  essay_id TEXT NOT NULL REFERENCES essays(id),
  instructor_id TEXT NOT NULL,
  student_id TEXT REFERENCES students(id),
  rubric_id TEXT NOT NULL,
  rubric_version TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','complete','failed','cancelled')),
  created_at TEXT NOT NULL
);

-- Every raw multi-pass sampling result (both paths persisted, always, one row
-- per pass per path per criterion) — kept in full for auditability. The
-- median/spread/confidence summary over these lives in score_aggregates below;
-- this table is never queried for "the" score, only for inspecting how each
-- individual pass landed.
CREATE TABLE IF NOT EXISTS score_records_v2 (
  id TEXT PRIMARY KEY,
  assessment_id TEXT NOT NULL REFERENCES assessments(id),
  criterion_id TEXT NOT NULL,
  path TEXT NOT NULL CHECK (path IN ('exemplar','personalized')),
  pass_index INTEGER NOT NULL DEFAULT 0,  -- 0..N-1, this pass's position among the N sampling passes
  score INTEGER,           -- NULL when score = 'no-evidence'
  is_no_evidence INTEGER NOT NULL DEFAULT 0,
  anchor_matched INTEGER,
  evidence_json TEXT NOT NULL,      -- [{quote, reasoning}]
  precedent_ids_json TEXT NOT NULL, -- [excerpt ids used]
  confidence REAL,                  -- this pass's own raw selfConfidence, not the aggregate's
  rationale TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (assessment_id, criterion_id, path, pass_index)
);

-- Multi-pass aggregate per path per criterion: median score across N raw
-- passes (score_records_v2) plus a spread/confidence summary over them.
-- `spread` = disagreement WITHIN this path's own repeated passes; never to be
-- confused with divergence_records below, which is disagreement BETWEEN the
-- exemplar and personalized paths — the two concepts intentionally do not
-- share a column, table, or name anywhere in this schema.
CREATE TABLE IF NOT EXISTS score_aggregates (
  assessment_id TEXT NOT NULL REFERENCES assessments(id),
  criterion_id TEXT NOT NULL,
  path TEXT NOT NULL CHECK (path IN ('exemplar','personalized')),
  score REAL,              -- median across evidence-bearing passes; NULL when score = 'no-evidence'
  is_no_evidence INTEGER NOT NULL DEFAULT 0,
  anchor_matched INTEGER,
  evidence_json TEXT NOT NULL,      -- representative pass's evidence (closest to the median)
  precedent_ids_json TEXT NOT NULL,
  rationale TEXT NOT NULL,          -- representative pass's rationale
  spread REAL,              -- max - min across evidence-bearing passes' scores; NULL when no-evidence
  confidence REAL NOT NULL, -- spread-derived heuristic (lower spread -> higher confidence)
  high_spread INTEGER NOT NULL DEFAULT 0,  -- spread >= this criterion's spread_thresholds row
  n_passes INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (assessment_id, criterion_id, path)
);

-- Computed divergence per criterion per assessment — disagreement BETWEEN the
-- exemplar and personalized paths' aggregates. See score_aggregates.spread for
-- the separate within-path concept.
CREATE TABLE IF NOT EXISTS divergence_records (
  assessment_id TEXT NOT NULL REFERENCES assessments(id),
  criterion_id TEXT NOT NULL,
  score_diff REAL,
  anchor_mismatch INTEGER NOT NULL,
  no_evidence_asymmetry INTEGER NOT NULL,
  exceeds_threshold INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (assessment_id, criterion_id)
);

-- Manual instructor overrides (the only thing that changes the output grade)
CREATE TABLE IF NOT EXISTS score_overrides (
  assessment_id TEXT NOT NULL REFERENCES assessments(id),
  criterion_id TEXT NOT NULL,
  new_score INTEGER NOT NULL CHECK (new_score BETWEEN 0 AND 5),
  new_rationale TEXT NOT NULL,
  overridden_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (assessment_id, criterion_id)
);

CREATE TABLE IF NOT EXISTS instructor_profile (
  instructor_id TEXT PRIMARY KEY,
  grading_philosophy TEXT,
  deprioritized_criteria_json TEXT,  -- [criterion_id]
  rationale_tone TEXT CHECK (rationale_tone IS NULL OR rationale_tone IN ('terse','detailed','encouraging','blunt')),
  default_llm_provider TEXT,
  default_llm_model TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS course_profile (
  course_id TEXT PRIMARY KEY REFERENCES courses(id),
  instructor_id TEXT NOT NULL,
  cohort_level TEXT,
  curriculum_texts_json TEXT,  -- [str]
  rubric_version_pin TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assignment_profile (
  assignment_id TEXT PRIMARY KEY REFERENCES assignments(id),
  course_id TEXT NOT NULL,
  prompt_text TEXT,
  format_expectations TEXT,
  criterion_emphasis_notes TEXT,
  common_pitfalls TEXT,
  updated_at TEXT NOT NULL
);
