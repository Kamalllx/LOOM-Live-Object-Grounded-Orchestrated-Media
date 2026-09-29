# LOOM evaluation results

## perception
```json
{
 "asr": {
  "wer": 0.0155,
  "ref_words": 193,
  "segments": 12
 },
 "ocr": {
  "items": [
   {
    "truth": "Acid-Base Neutralization",
    "read": "Acid-Base Neutralization",
    "char_similarity": 1.0,
    "temporal_iou": 0.975
   },
   {
    "truth": "NaOH + HCl -> NaCl + H2O",
    "read": "NaOH + HCl \u2192 NaCl + H2O",
    "char_similarity": 1.0,
    "temporal_iou": 0.942
   },
   {
    "truth": "pH 7 = neutral",
    "read": "pH 7 = neutral",
    "char_similarity": 1.0,
    "temporal_iou": 0.87
   },
   {
    "truth": "Acid + Base -> Salt + Water",
    "read": "Acid + Base -> Salt + Water",
    "char_similarity": 1.0,
    "temporal_iou": 0.915
   }
  ],
  "recall_at_0.8": 1.0,
  "mean_temporal_iou": 0.925,
  "extra_items": 2
 },
 "grounding": {
  "hazard_truth_window": [
   [
    56.25,
    64.58
   ]
  ],
  "ablation": {
   "detector_only": {
    "tracks": 53,
    "hazard_tracks": 12,
    "hazard_labels": [
     "broken glass",
     "knife",
     "open flame"
    ],
    "precision": 0.128,
    "recall": 0.723,
    "f1": 0.217,
    "false_block_s": 41.0,
    "missed_s": 2.3,
    "source": "recomputed from cached detections with the pipeline's tracking code"
   },
   "+clip_verify_generic": {
    "tracks": 22,
    "hazard_tracks": 4,
    "hazard_labels": [
     "broken glass",
     "knife",
     "open flame"
    ],
    "precision": 0.273,
    "recall": 0.723,
    "f1": 0.396,
    "false_block_s": 16.0,
    "missed_s": 2.3,
    "source": "development run 2026-09-29 on the same cached detections (hazard intervals after merging)"
   },
   "+clip_verify_hazard_lookalikes (LOOM)": {
    "tracks": 19,
    "hazard_tracks": 1,
    "hazard_labels": [
     "broken glass"
    ],
    "precision": 1.0,
    "recall": 0.602,
    "f1": 0.752,
    "false_block_s": 0.0,
    "missed_s": 3.3,
    "source": "development run 2026-09-29 on the same cached detections; equals the shipped concept graph"
   }
  },
  "meta": {
   "asr": "whisper-large-v3-turbo (Groq)",
   "grounding": "grounding-dino-tiny + IoU tracking + CLIP verification",
   "grounding_stats": {
    "tracks_raw": 53,
    "tracks_verified": 19
   },
   "ocr": "tesseract",
   "object_phrases": [
    "lab coat",
    "gloves",
    "safety goggles",
    "beaker",
    "brush",
    "dust pan",
    "broken glass",
    "knife",
    "open flame"
   ],
   "timings_s": {
    "ingest": 0.0,
    "asr": 1.0,
    "ocr": 13.4,
    "grounding": 15.4,
    "fusion": 3.6
   }
  },
  "note": "mask padding is applied later by the Guardian; these are raw grounding intervals"
 }
}
```

## critic
```json
{
 "detection_rate": 1.0,
 "faults": 13,
 "false_rejections": 0,
 "controls": 6,
 "by_family": {
  "F1": "2/2",
  "F2": "3/3",
  "F3": "5/5",
  "F4": "1/1",
  "F5": "1/1",
  "F6": "1/1"
 },
 "cases": [
  {
   "case": "control: clean parent+child cut",
   "expected": "approve",
   "caught": true,
   "approved": true,
   "codes": [],
   "scores": {
    "factuality": 1.0,
    "coherence": 1.0,
    "safety": 1.0
   },
   "latency_ms": 0
  },
  {
   "case": "control: true explainer claim 1",
   "expected": "approve",
   "caught": true,
   "approved": true,
   "codes": [],
   "scores": {
    "factuality": 1.0,
    "coherence": 1.0,
    "safety": 1.0
   },
   "latency_ms": 0
  },
  {
   "case": "control: true explainer claim 2",
   "expected": "approve",
   "caught": true,
   "approved": true,
   "codes": [],
   "scores": {
    "factuality": 1.0,
    "coherence": 1.0,
    "safety": 1.0
   },
   "latency_ms": 0
  },
  {
   "case": "control: true explainer claim 3",
   "expected": "approve",
   "caught": true,
   "approved": true,
   "codes": [],
   "scores": {
    "factuality": 1.0,
    "coherence": 1.0,
    "safety": 1.0
   },
   "latency_ms": 0
  },
  {
   "case": "control: true explainer claim 4",
   "expected": "approve",
   "caught": true,
   "approved": true,
   "codes": [],
   "scores": {
    "factuality": 1.0,
    "coherence": 1.0,
    "safety": 1.0
   },
   "latency_ms": 0
  },
  {
   "case": "control: true explainer claim 5",
   "expected": "approve",
   "caught": true,
   "approved": true,
   "codes": [],
   "scores": {
    "factuality": 1.0,
    "coherence": 1.0,
    "safety": 1.0
   },
   "latency_ms": 0
  },
  {
   "case": "F1 hazard mask removed",
   "expected": "unmasked_hazard",
   "caught": true,
   "approved": false,
   "codes": [
    "unmasked_hazard"
   ],
   "scores": {
    "factuality": 1.0,
    "coherence": 1.0,
    "safety": 0.0
   },
   "latency_ms": 0
  },
  {
   "case": "F1b hazard mask cut short",
   "expected": "unmasked_hazard",
   "caught": true,
   "approved": false,
   "codes": [
    "unmasked_hazard"
   ],
   "scores": {
    "factuality": 1.0,
    "coherence": 1.0,
    "safety": 0.5
   },
   "latency_ms": 0
  },
  {
   "case": "F2 wrong quiz answer (q1)",
   "expected": "quiz_unsupported",
   "caught": true,
   "approved": false,
   "codes": [
    "quiz_unsupported"
   ],
   "scores": {
    "factuality": 0.667,
    "coherence": 1.0,
    "safety": 1.0
   },
   "latency_ms": 0
  },
  {
   "case": "F2 wrong quiz answer (q2)",
   "expected": "quiz_unsupported",
   "caught": true,
   "approved": false,
   "codes": [
    "quiz_unsupported"
   ],
   "scores": {
    "factuality": 0.667,
    "coherence": 1.0,
    "safety": 1.0
   },
   "latency_ms": 0
  },
  {
   "case": "F2 wrong quiz answer (q3)",
   "expected": "quiz_unsupported",
   "caught": true,
   "approved": false,
   "codes": [
    "quiz_unsupported"
   ],
   "scores": {
    "factuality": 0.667,
    "coherence": 1.0,
    "safety": 1.0
   },
   "latency_ms": 0
  },
  {
   "case": "F3 false explainer claim 1",
   "expected": "explainer_unfaithful",
   "caught": true,
   "approved": false,
   "codes": [
    "explainer_unfaithful"
   ],
   "scores": {
    "factuality": 0.833,
    "coherence": 1.0,
    "safety": 1.0
   },
   "latency_ms": 0
  },
  {
   "case": "F3 false explainer claim 2",
   "expected": "explainer_unfaithful",
   "caught": true,
   "approved": false,
   "codes": [
    "explainer_unfaithful"
   ],
   "scores": {
    "factuality": 0.833,
    "coherence": 1.0,
    "safety": 1.0
   },
   "latency_ms": 0
  },
  {
   "case": "F3 false explainer claim 3",
   "expected": "explainer_unfaithful",
   "caught": true,
   "approved": false,
   "codes": [
    "explainer_unfaithful"
   ],
   "scores": {
    "factuality": 0.833,
    "coherence": 1.0,
    "safety": 1.0
   },
   "latency_ms": 0
  },
  {
   "case": "F3 false explainer claim 4",
   "expected": "explainer_unfaithful",
   "caught": true,
   "approved": false,
   "codes": [
    "explainer_unfaithful"
   ],
   "scores": {
    "factuality": 0.833,
    "coherence": 1.0,
    "safety": 1.0
   },
   "latency_ms": 0
  },
  {
   "case": "F3 false explainer claim 5",
   "expected": "explainer_unfaithful",
   "caught": true,
   "approved": false,
   "codes": [
    "explainer_unfaithful"
   ],
   "scores": {
    "factuality": 0.833,
    "coherence": 1.0,
    "safety": 1.0
   },
   "latency_ms": 0
  },
  {
   "case": "F4 thread ends mid-sentence",
   "expected": "cut_mid_sentence",
   "caught": true,
   "approved": false,
   "codes": [
    "cut_mid_sentence"
   ],
   "scores": {
    "factuality": 1.0,
    "coherence": 0.85,
    "safety": 1.0
   },
   "latency_ms": 0
  },
  {
   "case": "F5 prerequisite dropped for beginner",
   "expected": "missing_prerequisite",
   "caught": true,
   "approved": false,
   "codes": [
    "missing_prerequisite"
   ],
   "scores": {
    "factuality": 1.0,
    "coherence": 0.7,
    "safety": 1.0
   },
   "latency_ms": 0
  },
  {
   "case": "F6 overlapping threads",
   "expected": "overlapping_threads",
   "caught": true,
   "approved": false,
   "codes": [
    "overlapping_threads"
   ],
   "scores": {
    "factuality": 1.0,
    "coherence": 0.75,
    "safety": 1.0
   },
   "latency_ms": 0
  }
 ]
}
```

## animator
```json
{
 "explainers": 12,
 "render_success_rate": 1.0,
 "first_attempt_compile_rate": 1.0,
 "mean_attempts": 1.0,
 "median_render_s": 14.1,
 "critic_pass_rate_first_draft": 0.583,
 "runs": [
  {
   "concept": "Personal Protective Equipment (PPE)",
   "level": "beginner",
   "ok": true,
   "attempts": 1,
   "render_s": 14.1,
   "factuality": 1.0,
   "critic_pass": true,
   "issues": []
  },
  {
   "concept": "Personal Protective Equipment (PPE)",
   "level": "expert",
   "ok": true,
   "attempts": 1,
   "render_s": 12.5,
   "factuality": 1.0,
   "critic_pass": true,
   "issues": []
  },
  {
   "concept": "Acid Dissociation",
   "level": "beginner",
   "ok": true,
   "attempts": 1,
   "render_s": 9.9,
   "factuality": 1.0,
   "critic_pass": true,
   "issues": []
  },
  {
   "concept": "Acid Dissociation",
   "level": "expert",
   "ok": true,
   "attempts": 1,
   "render_s": 15.7,
   "factuality": 0.75,
   "critic_pass": false,
   "issues": [
    "explainer c_02: 'A beaker filled with water (H\u2082O) is shown.': Source does not state the beaker contains only water"
   ]
  },
  {
   "concept": "Base Dissociation",
   "level": "beginner",
   "ok": true,
   "attempts": 1,
   "render_s": 10.1,
   "factuality": 1.0,
   "critic_pass": true,
   "issues": []
  },
  {
   "concept": "Base Dissociation",
   "level": "expert",
   "ok": true,
   "attempts": 1,
   "render_s": 13.3,
   "factuality": 1.0,
   "critic_pass": true,
   "issues": []
  },
  {
   "concept": "Neutralization Reaction",
   "level": "beginner",
   "ok": true,
   "attempts": 1,
   "render_s": 14.5,
   "factuality": 0.8,
   "critic_pass": false,
   "issues": [
    "explainer c_04: 'Neutralization turns acid and base into harmless salt and water.': Source does not claim the products are harmless; 'harmless' overstates"
   ]
  },
  {
   "concept": "Neutralization Reaction",
   "level": "expert",
   "ok": true,
   "attempts": 1,
   "render_s": 17.5,
   "factuality": 1.0,
   "critic_pass": true,
   "issues": []
  },
  {
   "concept": "Indicator and pH Neutral Point",
   "level": "beginner",
   "ok": true,
   "attempts": 1,
   "render_s": 9.1,
   "factuality": 0.333,
   "critic_pass": false,
   "issues": [
    "explainer c_05: 'An indicator is red in acidic solution and turns green when the pH reaches\u202f7.': Source does not mention indicator colors; claim adds unsupported detail; 'Adding base (OH\u207b) raises the pH until the ind"
   ]
  },
  {
   "concept": "Indicator and pH Neutral Point",
   "level": "expert",
   "ok": true,
   "attempts": 1,
   "render_s": 14.7,
   "factuality": 0.75,
   "critic_pass": false,
   "issues": [
    "explainer c_05: 'An indicator is added to an acidic solution.': Source does not state the indicator is added to an acidic solution"
   ]
  },
  {
   "concept": "Safe Handling of Broken Glass",
   "level": "beginner",
   "ok": true,
   "attempts": 1,
   "render_s": 9.7,
   "factuality": 1.0,
   "critic_pass": true,
   "issues": []
  },
  {
   "concept": "Safe Handling of Broken Glass",
   "level": "expert",
   "ok": true,
   "attempts": 1,
   "render_s": 17.8,
   "factuality": 0.667,
   "critic_pass": false,
   "issues": [
    "explainer c_06: 'Always inform your teacher immediately after the incident.': Adds 'Always' and 'immediately' which overstates the source wording"
   ],
   "note": "judge re-run: first attempt hit an LLM rate limit (judge unavailable), not an explainer defect"
  }
 ]
}
```

## sessions
```json
{
 "runs": [
  {
   "learner": "learner_alex",
   "run": "first",
   "status": "approved",
   "pass_count": 1,
   "scores": {
    "factuality": 1.0,
    "coherence": 1.0,
    "safety": 1.0
   },
   "threads": 7,
   "source_kept_s": 58.5,
   "source_ratio": 0.784,
   "explainers": 0,
   "explainer_s": 0.0,
   "masks": 0,
   "quiz": 3,
   "time_to_first_frame_s": 0.3,
   "loop_trace": [
    {
     "pass_number": 1,
     "approved": true,
     "scores": {
      "factuality": 1.0,
      "coherence": 1.0,
      "safety": 1.0
     },
     "issues": []
    }
   ]
  },
  {
   "learner": "learner_alex",
   "run": "repeat",
   "status": "approved",
   "pass_count": 1,
   "scores": {
    "factuality": 1.0,
    "coherence": 1.0,
    "safety": 1.0
   },
   "threads": 7,
   "source_kept_s": 58.5,
   "source_ratio": 0.784,
   "explainers": 0,
   "explainer_s": 0.0,
   "masks": 0,
   "quiz": 3,
   "time_to_first_frame_s": 0.1,
   "loop_trace": [
    {
     "pass_number": 1,
     "approved": true,
     "scores": {
      "factuality": 1.0,
      "coherence": 1.0,
      "safety": 1.0
     },
     "issues": []
    }
   ]
  },
  {
   "learner": "learner_priya",
   "run": "first",
   "status": "approved",
   "pass_count": 1,
   "scores": {
    "factuality": 1.0,
    "coherence": 1.0,
    "safety": 1.0
   },
   "threads": 8,
   "source_kept_s": 74.6,
   "source_ratio": 1.0,
   "explainers": 4,
   "explainer_s": 78.2,
   "masks": 0,
   "quiz": 3,
   "time_to_first_frame_s": 0.1,
   "loop_trace": [
    {
     "pass_number": 1,
     "approved": true,
     "scores": {
      "factuality": 1.0,
      "coherence": 1.0,
      "safety": 1.0
     },
     "issues": []
    }
   ]
  },
  {
   "learner": "learner_priya",
   "run": "repeat",
   "status": "approved",
   "pass_count": 1,
   "scores": {
    "factuality": 1.0,
    "coherence": 1.0,
    "safety": 1.0
   },
   "threads": 8,
   "source_kept_s": 74.6,
   "source_ratio": 1.0,
   "explainers": 4,
   "explainer_s": 78.2,
   "masks": 0,
   "quiz": 3,
   "time_to_first_frame_s": 0.1,
   "loop_trace": [
    {
     "pass_number": 1,
     "approved": true,
     "scores": {
      "factuality": 1.0,
      "coherence": 1.0,
      "safety": 1.0
     },
     "issues": []
    }
   ]
  },
  {
   "learner": "learner_family",
   "run": "first",
   "status": "approved",
   "pass_count": 1,
   "scores": {
    "factuality": 1.0,
    "coherence": 1.0,
    "safety": 1.0
   },
   "threads": 8,
   "source_kept_s": 74.6,
   "source_ratio": 1.0,
   "explainers": 0,
   "explainer_s": 0.0,
   "masks": 1,
   "quiz": 3,
   "time_to_first_frame_s": 0.1,
   "loop_trace": [
    {
     "pass_number": 1,
     "approved": true,
     "scores": {
      "factuality": 1.0,
      "coherence": 1.0,
      "safety": 1.0
     },
     "issues": []
    }
   ],
   "redaction_vs_truth": {
    "precision": 1.0,
    "recall": 0.843,
    "f1": 0.915,
    "false_block_s": 0.0,
    "missed_s": 1.3
   }
  },
  {
   "learner": "learner_family",
   "run": "repeat",
   "status": "approved",
   "pass_count": 1,
   "scores": {
    "factuality": 1.0,
    "coherence": 1.0,
    "safety": 1.0
   },
   "threads": 8,
   "source_kept_s": 74.6,
   "source_ratio": 1.0,
   "explainers": 0,
   "explainer_s": 0.0,
   "masks": 1,
   "quiz": 3,
   "time_to_first_frame_s": 0.1,
   "loop_trace": [
    {
     "pass_number": 1,
     "approved": true,
     "scores": {
      "factuality": 1.0,
      "coherence": 1.0,
      "safety": 1.0
     },
     "issues": []
    }
   ],
   "redaction_vs_truth": {
    "precision": 1.0,
    "recall": 0.843,
    "f1": 0.915,
    "false_block_s": 0.0,
    "missed_s": 1.3
   }
  }
 ]
}
```
