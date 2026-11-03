-- Cinematic in-browser explainer scenes (JSON + per-beat narration); the MP4 export renders afterwards.
ALTER TABLE custom_explainers ADD COLUMN scene_ref TEXT;
