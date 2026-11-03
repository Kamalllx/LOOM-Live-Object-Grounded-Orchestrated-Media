"""Critic issue codes and their routing (spec/05 §7)."""

from __future__ import annotations

from typing import Literal

from loom.core.contracts.common import ConceptId, Contract, EffectSource, ObjectId, QuestionId, ThreadId

IssueCode = Literal[
    "unmasked_hazard",
    "explainer_unfaithful",
    "layout_failed",
    "judge_unavailable",
    "quiz_unsupported",
    "quiz_missing",
    "explainer_missing",
    "explainer_unavailable",
    "plugin_unavailable",
    "cut_mid_sentence",
    "missing_prerequisite",
    "overlapping_threads",
    "out_of_order",
    "empty_cut",
    "too_short",
    "anchor_outside_cut",
    "quiz_concept_not_in_cut",
]

IssueRoute = Literal["local", "mesh", "block"]

ISSUE_ROUTES: dict[str, IssueRoute] = {
    "unmasked_hazard": "local",
    "explainer_unfaithful": "local",
    "layout_failed": "local",
    "judge_unavailable": "local",
    "quiz_unsupported": "mesh",
    "quiz_missing": "mesh",
    "explainer_missing": "mesh",
    "explainer_unavailable": "mesh",
    "plugin_unavailable": "block",
    "cut_mid_sentence": "mesh",
    "missing_prerequisite": "mesh",
    "overlapping_threads": "mesh",
    "out_of_order": "mesh",
    "empty_cut": "mesh",
    "too_short": "mesh",
    "anchor_outside_cut": "mesh",
    "quiz_concept_not_in_cut": "mesh",
}


class CriticIssue(Contract):
    code: IssueCode
    detail: str = ""
    thread_id: ThreadId | None = None
    object_id: ObjectId | None = None
    concept_node_id: ConceptId | None = None
    question_id: QuestionId | None = None
    source: EffectSource | None = None
    feedback: str | None = None  # passed to a re-render / revise call


class LoopAction(Contract):
    issue_code: IssueCode
    action: Literal[
        "force_mask", "rerender", "redraft", "drop_artifact", "revise_cut", "reselect_quiz", "drop_request", "block"
    ]
    target: str | None = None
    result: Literal["applied", "failed", "skipped"] = "applied"
