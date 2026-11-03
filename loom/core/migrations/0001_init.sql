-- LOOM v2 initial schema (spec/02 §6). One writer (the gateway), WAL mode.

CREATE TABLE videos (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    source        TEXT NOT NULL,              -- JSON SourceInfo
    duration      REAL,
    status        TEXT NOT NULL,              -- ingesting | ready | failed
    graph_ref     TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE artifacts (
    ref           TEXT PRIMARY KEY,           -- loom://<kind>/<id>@sha256:...
    kind          TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    path          TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    model_ids     TEXT NOT NULL DEFAULT '{}', -- JSON
    stage_version TEXT
);
CREATE INDEX artifacts_sha ON artifacts(sha256);

CREATE TABLE jobs (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,              -- ingest | render | prerender
    status        TEXT NOT NULL,              -- queued | running | completed | failed | canceled
    stage         TEXT,
    progress      REAL NOT NULL DEFAULT 0,
    error         TEXT,
    payload       TEXT NOT NULL DEFAULT '{}', -- JSON
    attempts      INTEGER NOT NULL DEFAULT 0,
    dedupe_key    TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX jobs_status ON jobs(status, kind);
CREATE UNIQUE INDEX jobs_dedupe_active ON jobs(dedupe_key) WHERE dedupe_key IS NOT NULL
    AND status IN ('queued', 'running', 'completed');

CREATE TABLE events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,   -- monotonic; backs SSE Last-Event-ID
    channel       TEXT NOT NULL,
    kind          TEXT NOT NULL,
    payload       TEXT NOT NULL,                       -- JSON
    ts            TEXT NOT NULL
);
CREATE INDEX events_channel ON events(channel, id);

CREATE TABLE learners (
    id              TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    persona         TEXT NOT NULL DEFAULT '',
    preferences     TEXT NOT NULL,                     -- JSON
    safety_profile  TEXT NOT NULL,                     -- JSON
    parent_pin_hash TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE mastery (
    learner_id      TEXT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    concept_key     TEXT NOT NULL,
    level           REAL NOT NULL,
    last_seen       TEXT NOT NULL,
    evidence_count  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (learner_id, concept_key)
);

CREATE TABLE sessions (
    id                TEXT PRIMARY KEY,
    video_id          TEXT NOT NULL,
    learner_id        TEXT NOT NULL,
    status            TEXT NOT NULL,
    verified_cut_ref  TEXT,
    pass_count        INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    finished_at       TEXT
);

CREATE TABLE session_events (
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    type        TEXT NOT NULL,
    payload     TEXT NOT NULL DEFAULT '{}',
    client_ts   REAL,
    server_ts   TEXT NOT NULL,
    PRIMARY KEY (session_id, seq)
);

CREATE TABLE quiz_attempts (
    session_id    TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    question_id   TEXT NOT NULL,
    option_index  INTEGER NOT NULL,
    correct       INTEGER NOT NULL,
    ts            TEXT NOT NULL
);
CREATE INDEX quiz_attempts_session ON quiz_attempts(session_id);

CREATE TABLE explainers (
    concept_key   TEXT NOT NULL,                       -- graph_sha/concept_id
    level         TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    clip_ref      TEXT NOT NULL,
    storyboard    TEXT NOT NULL,                       -- JSON list
    code          TEXT NOT NULL,
    verified      INTEGER NOT NULL DEFAULT 0,
    judge_model   TEXT,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (concept_key, level, content_hash)
);

CREATE TABLE safety_reviews (
    video_id      TEXT NOT NULL,
    object_id     TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('reviewed', 'partial', 'unreviewed')),
    tags          TEXT NOT NULL DEFAULT '[]',
    severity      REAL NOT NULL DEFAULT 0,
    child_unsafe  INTEGER NOT NULL DEFAULT 0,
    reasons       TEXT NOT NULL DEFAULT '{}',
    models        TEXT NOT NULL DEFAULT '{}',
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (video_id, object_id)
);

CREATE TABLE agents (
    name        TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    card        TEXT NOT NULL,                         -- JSON AgentCard
    trust       TEXT NOT NULL CHECK (trust IN ('first_party', 'plugin')),
    enabled     INTEGER NOT NULL DEFAULT 1,
    required    INTEGER NOT NULL DEFAULT 0,
    last_seen   TEXT,
    failures    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE cut_cache (
    graph_sha          TEXT NOT NULL,
    learner_state_sha  TEXT NOT NULL,
    agent_set_sha      TEXT NOT NULL,
    policy_version     TEXT NOT NULL,
    verified_cut_ref   TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    PRIMARY KEY (graph_sha, learner_state_sha, agent_set_sha, policy_version)
);

-- Successful, validated LLM results only (spec/03 §4.7, NFR-REL-03). Failures are never written here.
CREATE TABLE llm_cache (
    key         TEXT PRIMARY KEY,                      -- sha256(digest, prompt@version, data, images, options, schema)
    role        TEXT NOT NULL,
    model       TEXT NOT NULL,
    digest      TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    value       TEXT NOT NULL,                         -- validated JSON
    created_at  TEXT NOT NULL
);
CREATE INDEX llm_cache_digest ON llm_cache(role, digest);
