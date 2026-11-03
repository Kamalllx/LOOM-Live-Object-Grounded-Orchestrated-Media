# Golden fixtures (Stage 0)

Built by `uv run python -m tests.fixtures.build_fixtures` from the demo lesson's ground truth
(`tests/eval_data/groundtruth_demo.json`, produced by `uv run loom eval make-demo`) plus hand-authored content in
`build_fixtures.py`. Nothing here comes from the old build. Stages 2–5 build against these files; Stage 1 replaces
`graph_demo_v2.json` with real perception output.

| File | Contract | What it is |
|---|---|---|
| `graph_demo_v2.json` | `concept-graph` | Demo lesson graph: 7 shots, 15 sentences, 4 on-screen captions, 7 objects (box tracks at 2 fps), 6 concepts with prerequisites, 7 thread roles, 18 quiz questions (6 concepts × 3 levels), sealed `graph_sha` |
| `learner_{alex,priya,family}.json` | `learner-profile` | The three personas of spec/01 §3 with `learner_state_sha` |
| `candidate_cut_{alex,priya,family}.json` | `candidate-cut` | *Sample* pass-1 candidates (illustrative — the S2 golden expectations are defined by the mesh owner) |
| `verified_cut_{alex,priya,family}.json` | `verified-cut` | Approved samples: Alex condensed, Priya with two auto explainers, Parent + child with the broken-glass mask |
| `verified_cut_family_fallback.json` | `verified-cut` | Fail-closed sample: models down → full lesson, every object masked, no generated content |

Known simplifications (fixture-only, intentional): boxes are constant per instance and read off frames by eye;
`mask` is `null` everywhere (box fallback) until S1 produces RLE masks; `words` are empty; explainer clip URLs point to
content hashes that do not exist on disk; safety records and quiz verification are marked `fixture:hand-authored`.

## Review checklist (a human must tick these before S2–S5 rely on the fixtures)

- [ ] Concept labels and summaries say only what the narration says (`build_fixtures.py` `CONCEPTS`).
- [ ] Every quiz question is answerable from its cited sentences, has exactly one correct option, and the marked
      answer is right (`QUIZ`; the correct option is always index 0 in the source table — the bank is not shuffled).
- [ ] Prerequisite chain PPE → acid/base dissociation → neutralization → indicator matches the lesson.
- [ ] Only `broken glass` is child-unsafe; gloves, lab coat, beaker, cylinder, flask, microscope are safe.
- [ ] Object boxes roughly cover the objects (check with frames from the built video).
- [ ] Persona sample cuts look plausible (Alex skips intro/setup/summary, never safety or core).
