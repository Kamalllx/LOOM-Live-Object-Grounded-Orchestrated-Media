"""LOOM evaluation. Every number in the paper comes from this script.

    .venv/bin/python scripts/evaluate.py perception     # ASR WER, OCR recall, hazard grounding, ablation
    .venv/bin/python scripts/evaluate.py critic         # fault injection: does the Critic catch planted errors?
    .venv/bin/python scripts/evaluate.py animator       # fresh explainers: compile/render rate, latency, Critic pass
    .venv/bin/python scripts/evaluate.py sessions       # 3 personas end to end (needs the backend running)
    .venv/bin/python scripts/evaluate.py report         # merge results into data/eval/results.md

Results are written to data/eval/<name>.json.
"""
import copy
import difflib
import json
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
for p in ["packages/shared-types", "services/perception/sam", "services/perception/graph-fusion",
          "services/verification/critic", "services/verification/animator", "services/verification/guardian",
          "services/agent-mesh/agents/curator", "services/agent-mesh/agents/pedagogy",
          "services/agent-mesh/agents/personalizer", "services/delivery/memory"]:
    sys.path.insert(0, str(ROOT / p))

EVAL = ROOT / "data" / "eval"
VIDEO_ID = "vid_demo_neutralization"
GRAPH = json.loads((ROOT / "data" / "graphs" / f"{VIDEO_ID}.json").read_text())
GT = json.loads((EVAL / f"groundtruth_{VIDEO_ID}.json").read_text())
SHARDS_LAND_S = 0.8   # the jar hits the table ~0.8 s into the hazard segment (read off the source clip)


def save(name, doc):
    (EVAL / f"{name}.json").write_text(json.dumps(doc, indent=2))
    print(json.dumps(doc, indent=2)[:3000])


# ---------------------------------------------------------------- perception

def _words(s):
    s = s.lower().replace("p h", "ph")
    return re.findall(r"[a-z0-9]+", s)


def wer(ref, hyp):
    r, h = _words(ref), _words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(1, len(r))


def _norm(s):
    return re.sub(r"[^a-z0-9+=]", "", s.lower().replace("→", "->").replace("->", ""))


def interval_pr(pred, truth, step=0.1, horizon=None):
    """Time-level precision/recall of predicted intervals against ground-truth intervals."""
    horizon = horizon or GT["duration_seconds"]
    tp = fp = fn = 0
    t = 0.0
    while t < horizon:
        p = any(a <= t < b for a, b in pred)
        g = any(a <= t < b for a, b in truth)
        tp += p and g
        fp += p and not g
        fn += g and not p
        t = round(t + step, 2)
    prec = tp / (tp + fp) if tp + fp else 1.0
    rec = tp / (tp + fn) if tp + fn else 1.0
    return {"precision": round(prec, 3), "recall": round(rec, 3),
            "f1": round(2 * prec * rec / (prec + rec), 3) if prec + rec else 0.0,
            "false_block_s": round(fp * step, 1), "missed_s": round(fn * step, 1)}


def eval_perception():
    import detect
    from fuse import HAZARD_PHRASES

    ref = " ".join(n["text"] for n in GT["narration"])
    hyp = " ".join(s["text"] for s in GRAPH["transcript"])
    asr = {"wer": round(wer(ref, hyp), 4), "ref_words": len(_words(ref)), "segments": len(GRAPH["transcript"])}

    found = []
    for g in GT["on_screen_text"]:
        best = max(GRAPH["on_screen_text"], key=lambda o: difflib.SequenceMatcher(None, _norm(o["text"]), _norm(g["text"])).ratio())
        sim = difflib.SequenceMatcher(None, _norm(best["text"]), _norm(g["text"])).ratio()
        inter = max(0, min(best["end"], g["end"]) - max(best["start"], g["start"]))
        union = max(best["end"], g["end"]) - min(best["start"], g["start"])
        found.append({"truth": g["text"], "read": best["text"], "char_similarity": round(sim, 3),
                      "temporal_iou": round(inter / union, 3)})
    ocr = {"items": found, "recall_at_0.8": round(sum(f["char_similarity"] >= 0.8 for f in found) / len(found), 3),
           "mean_temporal_iou": round(sum(f["temporal_iou"] for f in found) / len(found), 3),
           "extra_items": len(GRAPH["on_screen_text"]) - len(found)}

    hz = GT["hazards"][0]
    truth = [(hz["start"] + SHARDS_LAND_S, hz["end"])]
    phrases = GRAPH["perception_meta"]["object_phrases"]
    raw = detect._sample(ROOT / "media" / "videos" / f"{VIDEO_ID}.mp4", phrases, None)
    tracks = detect._track(raw["samples"], detect.SAMPLE_EVERY)
    video = ROOT / "media" / "videos" / f"{VIDEO_ID}.mp4"

    def hazard_intervals(tr_list):
        return [(tr["points"][0]["t"], tr["points"][-1]["t"] + detect.SAMPLE_EVERY) for tr in tr_list
                if tr["label"] in HAZARD_PHRASES]

    configs = {
        "detector_only": tracks,
        "+clip_verify_generic": detect._verify_tracks(video, tracks, phrases, hazards=()),
        "+clip_verify_hazard_lookalikes (LOOM)": detect._verify_tracks(video, tracks, phrases, hazards=set(HAZARD_PHRASES)),
    }
    ablation = {}
    for name, trs in configs.items():
        hazard_tracks = [tr for tr in trs if tr["label"] in HAZARD_PHRASES]
        ablation[name] = {"tracks": len(trs), "hazard_tracks": len(hazard_tracks),
                          "hazard_labels": sorted({tr["label"] for tr in hazard_tracks}),
                          **interval_pr(hazard_intervals(trs), truth)}
    grounding = {"hazard_truth_window": truth, "ablation": ablation,
                 "meta": GRAPH["perception_meta"]}
    save("perception", {"asr": asr, "ocr": ocr, "grounding": grounding})


# ---------------------------------------------------------------- critic fault injection

FALSE_CLAIMS = [
    "Neutralization always produces a solid precipitate of salt.",
    "Sodium hydroxide is a strong acid.",
    "At the neutral point the pH is 1.",
    "Hydrogen ions and hydroxide ions combine to form hydrogen gas.",
    "Hydrochloric acid releases hydroxide ions in water.",
]
TRUE_CLAIMS = [
    "An acid and a base react to form a salt and water.",
    "Hydrochloric acid releases hydrogen ions in water.",
    "Sodium hydroxide releases hydroxide ions in water.",
    "A neutral solution has a pH of 7.",
    "Hydrogen ions and hydroxide ions combine to form water.",
]


def _session_with(learner):
    for d in sorted((ROOT / "data" / "sessions").glob("sess_*"), key=lambda p: p.stat().st_mtime, reverse=True):
        v = d / "verified_cut.json"
        c = d / "candidate_pass1.json"
        if v.exists() and c.exists() and json.loads(v.read_text())["learner_id"] == learner:
            return json.loads(c.read_text()), json.loads(v.read_text())
    raise SystemExit(f"run a {learner} session first (evaluate.py sessions)")


def eval_critic():
    import critic
    import guardian
    import store

    critic.VERIFIED_CLIPS = EVAL / "_critic_eval_cache.json"   # never reuse verdicts during the experiment
    if critic.VERIFIED_CLIPS.exists():
        critic.VERIFIED_CLIPS.unlink()
    fam_cand, fam_cut = _session_with("learner_family")
    pri_cand, pri_cut = _session_with("learner_priya")
    fam_prof, pri_prof = store.get_learner("learner_family"), store.get_learner("learner_priya")
    tags = guardian.tag_objects(GRAPH)
    flagged = set(guardian.decide(GRAPH, fam_prof, [], tags))
    masks = fam_cut["redaction_masks"]
    graph = GRAPH
    results = []

    def run(name, expect, cand, prof, flg, msk, expl, want_approved=False):
        t0 = time.time()
        v = critic.score(cand, graph, prof, flg, msk, expl, {})
        codes = sorted({i["code"] for i in v["issues"]})
        caught = (expect in codes and not v["approved"]) if expect else v["approved"] == want_approved
        results.append({"case": name, "expected": expect or ("approve" if want_approved else "reject"),
                        "caught": caught, "approved": v["approved"], "codes": codes, "scores": v["scores"],
                        "latency_ms": round((time.time() - t0) * 1000)})
        print(f"{'OK ' if caught else 'MISS'} {name:48s} codes={codes} approved={v['approved']}")

    # controls: clean cuts must pass
    run("control: clean parent+child cut", None, fam_cand, fam_prof, flagged, masks, {}, want_approved=True)
    for i, c in enumerate(TRUE_CLAIMS):
        run(f"control: true explainer claim {i + 1}", None, pri_cand, pri_prof, set(), [],
            {"c_03": {"clip_url": f"/eval/true{i}", "storyboard": [c]}}, want_approved=True)
    # F1 safety: Guardian's masks lost
    run("F1 hazard mask removed", "unmasked_hazard", fam_cand, fam_prof, flagged, [], {})
    # F1b: mask shortened so the hazard is uncovered for 2 s
    short = [dict(m, end=m["start"] + (m["end"] - m["start"]) / 2) for m in masks]
    run("F1b hazard mask cut short", "unmasked_hazard", fam_cand, fam_prof, flagged, short, {})
    # F2 factual: quiz marked with a wrong answer
    for qi in range(len(pri_cand["quiz"])):
        bad = copy.deepcopy(pri_cand)
        q = bad["quiz"][qi]
        q["answer_index"] = (q["answer_index"] + 1) % len(q["options"])
        run(f"F2 wrong quiz answer (q{qi + 1})", "quiz_unsupported", bad, pri_prof, set(), [], {})
    # F3 factual: false sentence planted in an explainer storyboard
    for i, c in enumerate(FALSE_CLAIMS):
        run(f"F3 false explainer claim {i + 1}", "explainer_unfaithful", pri_cand, pri_prof, set(), [],
            {"c_03": {"clip_url": f"/eval/false{i}", "storyboard": TRUE_CLAIMS[:2] + [c]}})
    # F4 coherence: thread cut mid-sentence
    bad = copy.deepcopy(fam_cand)
    t = next(t for t in bad["threads"] if t["end"] - t["start"] > 6)
    t["end"] = round(t["end"] - 3.0, 2)
    run("F4 thread ends mid-sentence", "cut_mid_sentence", bad, fam_prof, flagged, masks, {})
    # F5 coherence: prerequisite removed for a beginner
    bad = copy.deepcopy(pri_cand)
    prereq_of = {n["node_id"]: n["prerequisites"] for n in graph["concept_nodes"]}
    target = next(c for t in bad["threads"] for c in t["concept_node_ids"] if prereq_of.get(c))
    drop = prereq_of[target][0]
    bad["threads"] = [t for t in bad["threads"] if drop not in t["concept_node_ids"]]
    run("F5 prerequisite dropped for beginner", "missing_prerequisite", bad, pri_prof, set(), [], {})
    # F6 coherence: overlapping threads
    bad = copy.deepcopy(fam_cand)
    bad["threads"][1]["start"] = bad["threads"][0]["start"] + 1.0
    run("F6 overlapping threads", "overlapping_threads", bad, fam_prof, flagged, masks, {})

    faults = [r for r in results if not r["case"].startswith("control")]
    controls = [r for r in results if r["case"].startswith("control")]
    by_family = {}
    for r in faults:
        fam = r["case"].split()[0].rstrip("b")
        by_family.setdefault(fam, []).append(r["caught"])
    save("critic", {"detection_rate": round(sum(r["caught"] for r in faults) / len(faults), 3),
                    "faults": len(faults), "false_rejections": sum(not r["caught"] for r in controls),
                    "controls": len(controls),
                    "by_family": {k: f"{sum(v)}/{len(v)}" for k, v in by_family.items()}, "cases": results})


# ---------------------------------------------------------------- animator

def eval_animator():
    import animator
    import critic
    critic.VERIFIED_CLIPS = EVAL / "_critic_eval_cache.json"
    animator.ANIMATOR_VERSION = f"eval-{int(time.time())}"      # force fresh generations
    animator.STATS_FILE = EVAL / "animator_runs.jsonl"
    rows = []
    for node in GRAPH["concept_nodes"]:
        for level in ("beginner", "expert"):
            t0 = time.time()
            row = {"concept": node["label"], "level": level}
            try:
                r = animator.render_explainer(node, animator.excerpt_for(GRAPH, node), level)
                row.update(ok=True, attempts=r["attempts"], render_s=round(time.time() - t0, 1))
                v = critic.factuality({"quiz": []}, GRAPH, {node["node_id"]: r})
                row.update(factuality=v[0], critic_pass=not v[1], issues=[i["message"] for i in v[1]])
            except Exception as e:
                row.update(ok=False, attempts=animator.MAX_REPAIRS + 1, render_s=round(time.time() - t0, 1),
                           error=str(e)[-200:])
            rows.append(row)
            print(row)
    ok = [r for r in rows if r["ok"]]
    save("animator", {
        "explainers": len(rows),
        "render_success_rate": round(len(ok) / len(rows), 3),
        "first_attempt_compile_rate": round(sum(r["attempts"] == 1 for r in ok) / len(rows), 3),
        "mean_attempts": round(sum(r["attempts"] for r in rows) / len(rows), 2),
        "median_render_s": sorted(r["render_s"] for r in ok)[len(ok) // 2] if ok else None,
        "critic_pass_rate_first_draft": round(sum(r.get("critic_pass", False) for r in ok) / max(1, len(ok)), 3),
        "runs": rows})


# ---------------------------------------------------------------- sessions

def eval_sessions():
    sys.path.insert(0, str(ROOT / "scripts"))
    import httpx
    from run_session import run

    httpx.post("http://127.0.0.1:8000/api/learners/reset")
    out = []
    for learner in ("learner_alex", "learner_priya", "learner_family"):
        for attempt in ("first", "repeat"):  # LLM + clip caches already populated by earlier runs
            t0 = time.time()
            cut = run(VIDEO_ID, learner, quiet=True)
            wall = time.time() - t0
            kept = sum(t["end"] - t["start"] for t in cut["final_threads"])
            ex_s = 0.0
            for c in cut["explainer_clips"]:
                meta = ROOT / c["clip_url"].lstrip("/")
                import subprocess
                ex_s += float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                              "csv=p=0", str(meta)], capture_output=True, text=True).stdout or 0)
            row = {"learner": learner, "run": attempt, "status": cut["status"], "pass_count": cut["pass_count"],
                   "scores": cut["critic_score"], "threads": len(cut["final_threads"]),
                   "source_kept_s": round(kept, 1), "source_ratio": round(kept / GRAPH["duration_seconds"], 3),
                   "explainers": len(cut["explainer_clips"]), "explainer_s": round(ex_s, 1),
                   "masks": len(cut["redaction_masks"]), "quiz": len(cut["quiz"]),
                   "time_to_first_frame_s": round(wall, 1),
                   "loop_trace": [{k: p[k] for k in ("pass_number", "approved", "scores", "issues")}
                                  for p in cut.get("loop_trace", [])]}
            masked = [(m["start"], m["end"]) for m in cut["redaction_masks"]]
            hz = GT["hazards"][0]
            if learner == "learner_family":
                row["redaction_vs_truth"] = interval_pr(masked, [(hz["start"] + SHARDS_LAND_S, hz["end"])])
            out.append(row)
            print({k: row[k] for k in ("learner", "run", "status", "pass_count", "source_ratio", "explainers",
                                       "masks", "time_to_first_frame_s")})
    save("sessions", {"runs": out})


# ---------------------------------------------------------------- report

def report():
    lines = ["# LOOM evaluation results", ""]
    for name in ("perception", "critic", "animator", "sessions"):
        p = EVAL / f"{name}.json"
        if p.exists():
            lines += [f"## {name}", "```json", json.dumps(json.loads(p.read_text()), indent=1)[:6000], "```", ""]
    (EVAL / "results.md").write_text("\n".join(lines))
    print(f"wrote {EVAL / 'results.md'}")


if __name__ == "__main__":
    {"perception": eval_perception, "critic": eval_critic, "animator": eval_animator,
     "sessions": eval_sessions, "report": report}[sys.argv[1]]()
