-- Learner questions, on-demand quizzes and custom explainers (interactive layer).
CREATE TABLE asks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id    TEXT NOT NULL,
    learner_id  TEXT NOT NULL,
    object_id   TEXT,
    kind        TEXT NOT NULL,              -- ask | explain | quiz
    query       TEXT NOT NULL,
    answer      TEXT,
    citations   TEXT NOT NULL DEFAULT '[]', -- JSON
    created_at  TEXT NOT NULL
);
CREATE INDEX asks_learner ON asks(learner_id, video_id);

CREATE TABLE adhoc_questions (
    question_id   TEXT PRIMARY KEY,
    video_id      TEXT NOT NULL,
    topic         TEXT NOT NULL,
    stem          TEXT NOT NULL,
    options       TEXT NOT NULL,            -- JSON list of 4
    answer_index  INTEGER NOT NULL,
    rationale     TEXT NOT NULL,
    evidence      TEXT NOT NULL,            -- JSON [{id, t, text}]
    verified_by   TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE adhoc_attempts (
    question_id   TEXT NOT NULL,
    learner_id    TEXT NOT NULL,
    option_index  INTEGER NOT NULL,
    correct       INTEGER NOT NULL,
    ts            TEXT NOT NULL
);

CREATE TABLE custom_explainers (
    key           TEXT PRIMARY KEY,         -- sha of video + normalized question + level
    video_id      TEXT NOT NULL,
    question      TEXT NOT NULL,
    object_id     TEXT,
    title         TEXT NOT NULL,
    clip_ref      TEXT NOT NULL,
    storyboard    TEXT NOT NULL,            -- JSON {lines, duration}
    evidence      TEXT NOT NULL,            -- JSON [{id, t}]
    judge_model   TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
