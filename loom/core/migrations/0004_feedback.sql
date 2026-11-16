-- The learner feedback loop: ratings of answers, explainers and labels, and label corrections that LOOM applies.
CREATE TABLE feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    learner_id TEXT,
    target_kind TEXT NOT NULL,      -- answer | explainer | label | part
    target_id TEXT NOT NULL,
    rating INTEGER NOT NULL,        -- 1 helpful, -1 not helpful
    reason TEXT,                    -- too_basic | too_advanced | wrong | unclear | wrong_label | other
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX feedback_video ON feedback (video_id, target_kind);
CREATE TABLE label_overrides (
    video_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    part_id TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL,
    learner_id TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (video_id, object_id, part_id)
);
