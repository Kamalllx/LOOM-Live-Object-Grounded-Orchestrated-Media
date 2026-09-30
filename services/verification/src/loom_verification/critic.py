"""Critic agent: scores a candidate cut and gates delivery.

Three scores in [0, 1], each from checks a reviewer can audit:
  safety     (deterministic) share of flagged-object screen time inside the cut covered by a mask, sampled at
             0.1 s. Must be exactly 1.0.
  coherence  (deterministic) threads ordered, non-overlapping, inside the video, never ending mid-sentence,
             referencing real concepts, prerequisites present when the learner lacks them, explainers available.
  factuality (judge)         every quiz question with its marked answer and every explainer storyboard sentence
             must be supported by the lesson (transcript + on-screen text). The judge is the LLM, or without one
             a lexical-support check.
A cut is approved only if the thresholds hold AND no individual check raised an issue: averages hide
individual failures. Every issue is structured ({code, message, ...}) so the loop can act on it.
"""

from __future__ import annotations

import json
import re
import threading

from .config import Config
from .llm import LLM, LLMError

JUDGE_SYSTEM = """You are a strict fact-checker for an educational video system. You get the lesson SOURCE (transcript
and on-screen text) and numbered CLAIMS written by other AI agents (quiz questions with their marked answer, and
narration lines of generated explainer animations). A claim is "supported" if it is correct AND consistent with the
source (general facts that agree with the source are fine). It is "unsupported" if it is wrong, contradicts the
source, or overstates it (e.g. "always", invented details such as colours or numbers the source never gives).
Return JSON: {"verdicts": [{"id": int, "supported": bool, "reason": short string}]}"""

STOP = set("a an the and or of to in on at for with by from is are was were be been it its this that these those as "
           "into than then so we you they he she them our your their what which who how when where why can will do "
           "does did not no yes if also each".split())
PREREQ_MASTERY = 0.35
_memo_lock = threading.Lock()


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2 and w not in STOP}


class Critic:
    def __init__(self, cfg: Config, llm: LLM | None):
        self.cfg, self.llm = cfg, llm
        self.memo_path = cfg.cache_dir / "critic_verified_clips.json"

    # ---------------- safety
    @staticmethod
    def safety(threads: list[dict], graph: dict, flagged: set[str], masks: list[dict]) -> tuple[float, list[dict]]:
        need = covered = 0
        uncovered: set[str] = set()
        for obj in graph.get("objects", []):
            if obj["object_id"] not in flagged:
                continue
            obj_masks = [m for m in masks if m["object_id"] == obj["object_id"]]
            for inst in obj.get("instances", []):
                t = inst["start"]
                while t < inst["end"]:
                    if any(th["start"] <= t < th["end"] for th in threads):
                        need += 1
                        if any(m["start"] <= t < m["end"] for m in obj_masks):
                            covered += 1
                        else:
                            uncovered.add(obj["object_id"])
                    t = round(t + 0.1, 2)
        issues = [{"code": "unmasked_hazard", "object_id": o, "message": f"{o} is visible without a mask"} for o in sorted(uncovered)]
        return (1.0 if need == 0 else round(covered / need, 3)), issues

    # ---------------- coherence
    @staticmethod
    def coherence(threads: list[dict], graph: dict, profile: dict, explainer_failures: dict[str, str]) -> tuple[float, list[dict]]:
        if not threads:
            return 0.0, [{"code": "empty_cut", "message": "the cut contains no threads"}]
        issues, penalty = [], 0.0
        duration = graph.get("duration_seconds") or max([s["end"] for s in graph.get("transcript", [])] + [t["end"] for t in threads])
        starts = [t["start"] for t in threads]
        if starts != sorted(starts) or any(b["start"] < a["end"] - 0.05 for a, b in zip(threads, threads[1:])):
            penalty += 0.25
            issues.append({"code": "overlapping_threads", "message": "threads overlap or are out of order"})
        for t in threads:
            if t["start"] < 0 or t["end"] > duration + 0.5 or t["end"] <= t["start"]:
                penalty += 0.25
                issues.append({"code": "thread_out_of_bounds", "thread_id": t["thread_id"],
                               "message": f"{t['thread_id']} spans {t['start']}-{t['end']}s outside the {duration}s video"})
                continue
            for s in graph.get("transcript", []):
                if s["start"] + 0.3 < t["end"] < s["end"] - 0.3:
                    penalty += 0.15
                    issues.append({"code": "cut_mid_sentence", "thread_id": t["thread_id"], "sentence_end": s["end"],
                                   "message": f"{t['thread_id']} ends mid-sentence at {t['end']}s (sentence ends {s['end']}s)"})
                    break
        nodes = {n["node_id"]: n for n in graph.get("concept_nodes", [])}
        in_cut = {c for t in threads for c in t.get("concept_node_ids", [])}
        for c in sorted(in_cut - set(nodes)):
            penalty += 0.1
            issues.append({"code": "unknown_concept", "concept_node_id": c, "message": f"threads reference unknown concept {c}"})
        mastery = {m["concept_id"].split("/")[-1]: m.get("level", 0) for m in profile.get("mastery_graph", [])}
        for c in in_cut & set(nodes):
            for p in nodes[c].get("prerequisites", []):
                if p not in in_cut and mastery.get(p, 0.0) < PREREQ_MASTERY:
                    penalty += 0.1
                    issues.append({"code": "missing_prerequisite", "concept_node_id": p,
                                   "message": f"{c} needs {p}, which this learner has not mastered"})
        for cid, err in explainer_failures.items():
            penalty += 0.1
            issues.append({"code": "explainer_unavailable", "concept_node_id": cid,
                           "message": f"explainer for {cid} could not be produced: {err[:160]}"})
        return round(max(0.0, 1.0 - penalty), 3), issues

    # ---------------- factuality
    def _memo(self) -> dict:
        return json.loads(self.memo_path.read_text(encoding="utf-8")) if self.memo_path.exists() else {}

    def _remember(self, urls: dict) -> None:
        with _memo_lock:
            m = self._memo()
            m.update(urls)
            self.memo_path.parent.mkdir(parents=True, exist_ok=True)
            self.memo_path.write_text(json.dumps(m, indent=2), encoding="utf-8")

    def _judge(self, source: str, claims: list[dict]) -> tuple[list[dict], str]:
        if self.llm:
            listing = "\n".join(f"[{i}] {c['text']}" for i, c in enumerate(claims))
            try:
                out = self.llm.json(JUDGE_SYSTEM, f"SOURCE:\n{source}\n\nCLAIMS:\n{listing}")
                by_id = {v.get("id"): v for v in out.get("verdicts", []) if isinstance(v, dict)}
                return [by_id.get(i, {"supported": False, "reason": "no verdict returned"}) for i in range(len(claims))], self.llm.name
            except LLMError:
                pass
        vocab = _words(source)
        verdicts = []
        for c in claims:
            w = _words(c.get("check", c["text"]))   # quiz: judge the marked answer, not the question's wording
            share = len(w & vocab) / len(w) if w else 1.0
            verdicts.append({"supported": share >= 0.6, "reason": f"{share:.0%} of its content words appear in the lesson"})
        return verdicts, "lexical"

    def factuality(self, quiz: list[dict], graph: dict, explainers: dict) -> tuple[float, list[dict], list[dict], str]:
        claims = []
        for i, q in enumerate(quiz):
            if q.get("options") and isinstance(q.get("answer_index"), int) and 0 <= q["answer_index"] < len(q["options"]):
                answer = q["options"][q["answer_index"]]
                claims.append({"kind": "quiz", "index": i, "check": answer,
                               "text": f"Q: {q['question']} -> marked answer: {answer}"})
        known, pre = self._memo(), 0
        for cid, ex in explainers.items():
            if ex.url in known:             # clips are immutable: once approved, always approved
                pre += len(ex.storyboard)
                continue
            claims += [{"kind": "explainer", "concept_node_id": cid, "text": s} for s in ex.storyboard]
        if not claims:
            return 1.0, [], [], "none"
        source = "\n".join(s["text"] for s in graph.get("transcript", [])) + "\nON SCREEN: " + \
            " | ".join(t["text"] for t in graph.get("on_screen_text", [])) + "\nCONCEPTS: " + \
            " | ".join(n.get("label", "") for n in graph.get("concept_nodes", []))
        verdicts, judge = self._judge(source, claims)
        issues, details, bad = [], [], {}
        for c, v in zip(claims, verdicts):
            ok = bool(v.get("supported"))
            details.append({**c, "supported": ok, "reason": v.get("reason", "")})
            if ok:
                continue
            if c["kind"] == "quiz":
                issues.append({"code": "quiz_unsupported", "index": c["index"], "message": f"quiz {c['index']}: {v.get('reason', '')}"})
            else:
                bad.setdefault(c["concept_node_id"], []).append(f"'{c['text']}': {v.get('reason', '')}")
        for cid, reasons in bad.items():
            issues.append({"code": "explainer_unfaithful", "concept_node_id": cid, "feedback": reasons,
                           "message": f"explainer {cid}: " + "; ".join(reasons)[:220]})
        passed = {ex.url: cid for cid, ex in explainers.items() if cid not in bad and ex.url not in known}
        if passed:
            self._remember(passed)
        supported = sum(d["supported"] for d in details)
        return round((supported + pre) / (len(claims) + pre), 3), issues, details, judge

    # ---------------- verdict
    def score(self, threads, quiz, graph, profile, flagged, masks, explainers, explainer_failures) -> dict:
        s_saf, i_saf = self.safety(threads, graph, flagged, masks)
        s_coh, i_coh = self.coherence(threads, graph, profile, explainer_failures)
        s_fac, i_fac, claims, judge = self.factuality(quiz, graph, explainers)
        scores = {"factuality": s_fac, "coherence": s_coh, "safety": s_saf}
        issues = i_saf + i_coh + i_fac
        approved = (s_saf == 1.0 and s_coh >= self.cfg.min_coherence and s_fac >= self.cfg.min_factuality and not issues)
        return {"scores": scores, "approved": approved, "issues": issues, "claims": claims, "judge": judge}
