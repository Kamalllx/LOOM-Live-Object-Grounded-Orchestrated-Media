# 05 — Data contracts v2

Source of truth: Pydantic v2 models in `loom/core/contracts/`. `loom contracts export` writes JSON Schema to
`contracts/*.schema.json` and TypeScript types to `packages/contracts-ts/`. Every contract carries
`schema_version: "2.x"`. Breaking changes bump the major version and are logged in `contracts/CHANGELOG.md`.

Conventions: times in seconds (float, 2 decimals) from the start of the normalized video; boxes are normalized
`[x, y, w, h]` (top-left origin, 0..1) **relative to the picture** (`content_rect` removed); ids are stable,
prefixed strings (`s_001` sentence, `x_001` OCR span, `o_001` object, `c_01` concept, `t1` thread, `q_…`
question, `sh_01` shot).

Mask encoding: `"rle:<height>x<width>:<COCO compressed counts>"` (pycocotools string form). Every contract forbids
unknown fields (`extra="forbid"`), so a forged or misspelled field is a validation error.

Changes from v1 (old `contracts/`): ids instead of float matching; pixel masks; per-object safety record; quiz
bank; evidence ids everywhere; `degraded` flags; content hashes; no quiz answers in the player view.

## 1. Concept graph (Contract A) — `concept-graph`

```jsonc
{
  "schema_version": "2.0",
  "video_id": "acid_base_neutralization_3fa1c2",
  "title": "Acid-Base Neutralization",
  "source": {"kind": "upload|path|youtube", "ref": "…", "youtube_id": null},
  "video_url": "/media/videos/acid_base_neutralization_3fa1c2.mp4",
  "duration_seconds": 74.57,
  "frame": {"width": 1920, "height": 1080, "fps": 30.0, "content_rect": [0, 0, 1, 1]},
  "shots": [{"shot_id": "sh_01", "start": 0.0, "end": 7.8, "keyframes": [0.5, 4.0]}],
  "transcript": [
    {"seg_id": "s_001", "start": 0.0, "end": 7.84, "text": "Welcome, in this short lesson…",
     "words": [{"w": "Welcome", "start": 0.12, "end": 0.55}], "speaker": null}
  ],
  "on_screen_text": [
    {"text_id": "x_001", "start": 0.4, "end": 7.6, "text": "Acid-Base Neutralization",
     "bbox": [0.18, 0.08, 0.64, 0.10], "confidence": 0.97, "reader": "rapidocr|glm-ocr"}
  ],
  "objects": [
    {
      "object_id": "o_006", "label": "broken glass", "phrase_source": "hazard_class|vlm|transcript",
      "is_hazard_class": true,
      "instances": [{
        "instance_id": "o_006_0", "shot_id": "sh_07", "start": 58.0, "end": 63.0,
        "score": 0.71,
        "track": [{"t": 58.0, "bbox": [0.30, 0.31, 0.35, 0.52], "mask": "rle:…"}],
        "verification": {"siglip_margin": 0.22, "vlm": "confirmed|rejected|not_run|failed",
                         "status": "verified|unverified"}
      }],
      "safety": {"status": "reviewed|partial|unreviewed", "tags": ["sharp_object", "injury_risk"],
                 "severity": 0.8, "child_unsafe": true, "disagreement": false,
                 "reasons": {"guardian": "…", "vlm": "…"},
                 "models": {"safety": "granite4.1-guardian:8b-q4_K_M@<digest>", "vlm": "qwen3.5:9b@<digest>"}}
    }
  ],
  "concept_nodes": [
    {"node_id": "c_04", "label": "Neutralization Reaction",
     "summary": "An acid and a base react to form a salt and water.",
     "evidence": {"segment_ids": ["s_006", "s_007"], "text_ids": ["x_002"], "object_ids": ["o_004"]},
     "prerequisites": ["c_02", "c_03"], "difficulty": "intermediate",
     "canonical_key": "concept:neutralization"}
  ],
  "thread_roles": [{"segment_ids": ["s_001"], "role": "intro", "gist": "Lesson overview"}],
  "quiz_bank": [
    {"question_id": "q_c04_b_1", "concept_node_id": "c_04", "level": "beginner",
     "stem": "What two products form when an acid neutralizes a base?",
     "options": ["Salt and water", "Gas and heat", "Acid and oxygen", "Only water"],
     "answer_index": 0, "rationale": "…", "evidence_segment_ids": ["s_007"],
     "verified_by": "gemma4:e4b@<digest>"}
  ],
  "perception_meta": {
    "pipeline_version": "2.0.0", "segmentation_tier": "sam2",
    "models": {"asr": "faster-whisper large-v3-turbo", "detector": "grounding-dino-base", "…": "…"},
    "timings_s": {"asr": 9.1, "ocr": 12.0, "segment": 61.0, "…": 0},
    "degraded": [], "stage_hashes": {"asr": "sha256:…"}
  },
  "graph_sha": "sha256:…"
}
```

Validation rules (beyond types): ids unique and referenced ids exist; `start < end` and within duration;
instances of one object do not overlap in time within a shot; prerequisites acyclic and point to earlier
concepts; every concept has ≥ 1 segment or text id; quiz `answer_index` within options; options distinct.

**Views** served to consumers:

| View | Contains | Consumers |
|---|---|---|
| `full` | everything | perception inspector, Guardian (server-side), eval |
| `mesh` | transcript (no words), OCR, concepts, thread_roles, objects without tracks/masks, safety summary, quiz bank **without** answers | Curator, Pedagogy, Personalizer, plug-ins that declare it |
| `safety` | objects (id, label, times, safety summary), duration | plug-ins `policy_review` |
| `player` | video_url, frame, transcript, OCR, objects with tracks (masks loaded separately), concepts (label, summary) | web player, extension |

## 2. Learner profile — `learner-profile`

```jsonc
{
  "schema_version": "2.0", "learner_id": "learner_priya", "display_name": "Priya",
  "persona": "Beginner - new to this topic",
  "preferences": {"pace": "condensed|standard|detailed", "language": "en", "prior_knowledge": 0.2,
                  "explainers": "auto|tap_only|off", "never_skip": false},
  "safety_profile": {"redaction_level": "off|standard|strict", "blocked_tags": [], "allowed_tags": [],
                     "parent_lock": false},
  "mastery": [{"concept_key": "acid_base_neutralization_3fa1c2/c_04", "level": 0.42,
               "last_seen": "2026-10-28T10:00:00Z", "evidence_count": 3}],
  "learner_state_sha": "sha256:…"
}
```

## 3. Candidate cut (Contract B) — `candidate-cut`

```jsonc
{
  "schema_version": "2.0", "session_id": "sess_…", "video_id": "…", "graph_sha": "…",
  "learner_id": "…", "learner_state_sha": "…", "pass_number": 1,
  "threads": [{"thread_id": "t2", "concept_node_ids": ["c_01"], "role": "core",
               "action": "keep|condense|expand", "start": 7.84, "end": 17.74,
               "source_end": 17.74, "rationale": "mastery 0.40 (prior): standard pacing",
               "source": "pedagogy|plugin:<name>"}],
  "skipped": [{"thread_id": "t1", "start": 0.0, "end": 7.84, "rationale": "…", "source": "pedagogy"}],
  "explainer_requests": [{"concept_node_id": "c_04", "trigger": "auto|tap", "level": "beginner",
                          "anchor_time": 46.34}],
  "redaction_requests": [{"object_id": "o_006", "reason": "…", "source": "personalizer|plugin:<name>"}],
  "quiz": [{"question_id": "q_c04_b_1"}],
  "agent_trace": [{"agent": "loom-curator", "version": "2.0", "skill": "build_threads",
                   "latency_ms": 12, "status": "ok|degraded|failed", "degraded": []}],
  "degraded": []
}
```

## 4. Verified cut (Contract C) — `verified-cut`

```jsonc
{
  "schema_version": "2.0", "session_id": "…", "video_id": "…", "learner_id": "…",
  "status": "approved|fallback", "fallback_reason": null, "pass_count": 1, "cache_hit": false,
  "critic_score": {"safety": 1.0, "coherence": 1.0, "factuality": 1.0, "completeness": 1.0},
  "final_threads": [{"thread_id": "t2", "start": 7.84, "end": 17.74, "action": "keep",
                     "label": "Personal Protective Equipment", "rationale": "…", "source": "pedagogy"}],
  "skipped": [{"start": 0.0, "end": 7.84, "rationale": "…"}],
  "redaction_masks": [{"mask_id": "m_o_006_0", "object_id": "o_006", "label": "broken glass",
                       "start": 57.5, "end": 63.5, "track_url": "/media/masks/<video>/o_006_0.json",
                       "fallback_bbox": [0.26, 0.27, 0.43, 0.60], "style": "blur",
                       "reason": "blocked tag sharp_object", "source": "guardian|critic|plugin:<name>",
                       "enforced": true}],
  "explainer_clips": [{"concept_node_id": "c_04", "trigger": "auto", "anchor_seconds": 46.34,
                       "clip_url": "/media/clips/<content_hash>.mp4", "content_hash": "…",
                       "title": "Neutralization Reaction", "duration_seconds": 16.2,
                       "storyboard": ["…"], "verified_by": "gemma4:e4b@<digest>"}],
  "tap_targets": [{"object_id": "o_004", "concept_node_id": "c_04"}],
  "quiz": [{"question_id": "q_c04_b_1", "stem": "…", "options": ["…", "…", "…", "…"]}],
  "loop_trace": [{"pass_number": 1, "approved": true, "scores": {"…": 1.0}, "issues": [],
                  "actions": [], "latency_ms": 820}],
  "degraded": [],
  "created_at": "…"
}
```

Note: **no `answer_index`** in the verified cut sent to clients. Grading uses the bank server-side.

## 5. Session log (Contract D) — `session-log`

```jsonc
{
  "schema_version": "2.0", "session_id": "…", "learner_id": "…", "video_id": "…",
  "events": [{"seq": 12, "type": "play|pause|seek|thread_complete|object_tapped|explainer_shown|explainer_skipped|mask_shown|mask_revealed|quiz_answered|session_end",
              "client_ts": 31.2, "server_ts": "…", "payload": {"concept_node_id": "c_02"}}],
  "quiz_attempts": [{"question_id": "q_c04_b_1", "option_index": 0, "correct": true, "server_ts": "…"}],
  "mastery_updates": [{"concept_key": "…/c_04", "before": 0.40, "after": 0.61, "cause": "quiz_correct"}]
}
```

`quiz_attempts` and `mastery_updates` are written only by the server. API payloads: `client-event-batch` (events
without `server_ts`), `quiz-answer-request` (`{option_index}` only — a `correct` field is rejected) and
`quiz-answer-result` (`{correct, correct_index, rationale, evidence}`).

Ops payloads (also exported): `health`, `readiness` (per-role `{role, tag, required, present, digest, last_ok_at,
last_error}`), `models-report`, `job`.

## 6. Events (SSE) — `event`

```jsonc
{"id": 1834, "channel": "sess_…|ingest_…|tap_…", "ts": "…", "kind": "<kind>", "data": {…}}
```

| Kind | Data |
|---|---|
| `ingest_stage` | `stage, status (started/progress/done/failed/skipped), progress, eta_s, detail, degraded[]` |
| `session_start` | `video_id, learner_id, cache_hit` |
| `agent_call` / `agent_done` | `agent, skill, latency_ms?, status, degraded[]` |
| `candidate_ready` | `pass_number, threads, explainer_requests, redaction_requests` |
| `loop_phase` | `phase (perceive/plan/verify/act), pass_number, scores?, issues?, actions?` |
| `render_progress` | `concept_node_id, step (draft/gate/render/layout/narrate/verify), attempt` |
| `gpu_lease` | `holder, waiting, priority` |
| `delivered` | `status (approved/fallback), pass_count` |
| `degraded` | `component, reason` |
| `error` | `message, where` |

## 7. Critic issue codes

| Code | Raised by | Routed to |
|---|---|---|
| `unmasked_hazard` | safety | local: force mask |
| `explainer_unfaithful` | factuality | local: re-render with feedback (once), then `explainer_unavailable` |
| `layout_failed` | animator/critic | local: re-draft once |
| `judge_unavailable` | factuality | local: drop artifact |
| `quiz_unsupported` | factuality | mesh: Assessment re-select |
| `quiz_missing` | completeness | mesh: Assessment re-select |
| `explainer_missing` / `explainer_unavailable` | completeness / coherence | mesh: Personalizer drops request |
| `plugin_unavailable` | completeness | blocks if plug-in `required`; else note |
| `cut_mid_sentence` · `missing_prerequisite` · `overlapping_threads` · `out_of_order` · `empty_cut` · `too_short` · `anchor_outside_cut` · `quiz_concept_not_in_cut` | coherence | mesh: Personalizer `revise` |

## 8. Error codes (JSON-RPC and REST)

| Code | Meaning |
|---|---|
| `-32001 contract_invalid` | Request or response failed schema validation |
| `-32002 artifact_not_found` | `$ref` could not be resolved |
| `-32003 model_unavailable` | Required local model missing / unreachable |
| `-32004 timeout` | Skill exceeded its timeout |
| `-32005 forbidden_effect` | Plug-in tried an effect outside its trust level |
| REST `409 offline` | Link ingest attempted in offline mode |
| REST `503 not_ready` | Required models missing (with list) |
