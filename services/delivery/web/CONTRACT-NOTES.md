# Additive fields the delivery client uses

Per the contract rule in `/docs/work-split.md`, a field can be **added** without a
`schema_version` bump. These are all optional — the player works without them, it
just degrades. Post this list in the Contract C channel so Person 3 knows what to fill.

| Contract | Field | Why delivery needs it | If missing |
|---|---|---|---|
| C — `final_threads[]` | `concept_node_ids: string[]` | Links a thread on the timeline to the concept it teaches, so an explainer can be anchored to it | Thread renders with no concept link |
| C — `final_threads[]` | `label: string` | Human-readable name on the timeline | Falls back to `thread_id` |
| C — `redaction_masks[]` | `fallback_bbox: [x, y, w, h]` (normalized 0–1) | Lets the client blur the region with CSS when the matte video isn't reachable | Mask is listed but not drawn |
| C — `redaction_masks[]` | `reason: string` | Shown in the safety panel so the redaction is explainable | Generic reason text |
| C — `explainer_clips[]` | `anchor_seconds: number` | Where in the main video the "tap for an explainer" affordance appears | Explainer only reachable from the concept list |
| C — `explainer_clips[]` | `title`, `duration_seconds` | Card label and expected length | Falls back to the concept id |
| C — `quiz[]` | `options: string[]`, `answer_index: number` | Makes the quiz answerable and gradeable in the client, which is what produces `quiz_answered` events and mastery updates | Question shown read-only, no mastery update possible |

`mask_url` / `clip_url` use `s3://bucket/key`. Until real S3 exists, the client maps
`s3://<bucket>/<key>` to `/media/<key>` in `public/media/`. See `src/lib/media.ts`.
