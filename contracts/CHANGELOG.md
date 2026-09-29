# Contract changelog

Log every breaking change here: which schema, what changed, who approved it.

## Format
- YYYY-MM-DD — schema name — what changed — approved by

## Entries
- 2026-09-29 — all schemas — removed UTF-8 BOM from every contract and fixture file (Python `json.load` and JS `JSON.parse` rejected them). No field changes. — pending team review
- 2026-09-29 — all schemas — item shapes added for every array (previously `{"type": "array"}` with no items, so validation checked almost nothing). All existing field names kept; additions below are optional, so `schema_version` stays "1.0" per the additive-change rule. — pending team review
- 2026-09-29 — concept-graph — optional `video_url`, `title`, `objects[].safety_tags`, `instances[].track` (per-second boxes), `on_screen_text[].bbox`, `concept_nodes[].summary`, `concept_nodes[].prerequisites`. — pending team review
- 2026-09-29 — learner-profile — optional `display_name`, `preferences.prior_knowledge`, `family_safety_profile.blocked_tags`; `pace` and `redaction_level` now enumerated. — pending team review
- 2026-09-29 — candidate-cut — optional `explainer_requests[].anchor_time` / `.level`, `quiz[].options` / `.answer_index`, `revision_feedback`; `threads[].action` enumerated (keep/expand/condense/skip). — pending team review
- 2026-09-29 — verified-cut — optional `video_id`, `video_url`, `learner_id`, `redaction_masks[].bbox` / `.style` / `.reason`, `explainer_clips[].trigger` / `.anchor_time`, `loop_trace`. Media URLs are served over HTTP (`/media/...`) instead of `s3://` so browsers can play them. — pending team review
- 2026-09-29 — session-log — optional `video_id`; `events[].type` enumerated. — pending team review
- 2026-09-29 — fixtures — made consistent with each other and with the LOOM film: `obj_004` (broken glass, 40–46 s) now exists in the concept-graph fixture. — pending team review
- 2026-09-30 — verified-cut — optional `final_threads[].label`, `redaction_masks[].fallback_bbox`, `explainer_clips[].anchor_seconds` / `.title` / `.duration_seconds`, as requested in services/delivery/web/CONTRACT-NOTES.md; the verification service now fills them. Additive, no version bump. — pending team review
