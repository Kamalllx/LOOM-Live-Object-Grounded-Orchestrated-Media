"""Concept graph v2 — Contract A (spec/05 §1) and its consumer views."""

from __future__ import annotations

from itertools import pairwise
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from loom.core.contracts.common import (
    SCHEMA_VERSION,
    TIME_EPS,
    BBox,
    ConceptId,
    Contract,
    Degraded,
    InstanceId,
    Level,
    ObjectId,
    QuestionId,
    SafetyTag,
    SchemaVersion,
    Seconds,
    SentenceId,
    Sha256,
    ShotId,
    TextId,
    ThreadRole,
    Unit,
    VideoId,
    check_span,
    find_duplicates,
    sha256_of,
)

# Mask encoding: "rle:<height>x<width>:<COCO compressed counts>" (pycocotools string form).
MaskRle = Annotated[str, StringConstraints(pattern=r"^rle:\d+x\d+:\S+$")]


class SourceInfo(Contract):
    kind: Literal["upload", "path", "youtube"]
    ref: str
    youtube_id: str | None = None


class FrameInfo(Contract):
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    content_rect: BBox = (0.0, 0.0, 1.0, 1.0)


class Shot(Contract):
    shot_id: ShotId
    start: Seconds
    end: Seconds
    keyframes: list[Seconds] = []


class Word(Contract):
    w: str
    start: Seconds
    end: Seconds


class Sentence(Contract):
    seg_id: SentenceId
    start: Seconds
    end: Seconds
    text: str = Field(min_length=1)
    words: list[Word] = []
    speaker: str | None = None


class TextSpan(Contract):
    text_id: TextId
    start: Seconds
    end: Seconds
    text: str = Field(min_length=1)
    bbox: BBox
    confidence: Unit
    reader: Literal["rapidocr", "glm-ocr"]


class TrackSample(Contract):
    t: Seconds
    bbox: BBox
    mask: MaskRle | None = None


class Verification(Contract):
    siglip_margin: float | None = None
    vlm: Literal["confirmed", "rejected", "not_run", "failed"] = "not_run"
    status: Literal["verified", "unverified"]


class ObjectInstance(Contract):
    instance_id: InstanceId
    shot_id: ShotId
    start: Seconds
    end: Seconds
    score: Unit
    track: list[TrackSample] = Field(min_length=1)
    verification: Verification

    @model_validator(mode="after")
    def _track_inside(self) -> Self:
        check_span(self.start, self.end, self.instance_id)
        ts = [s.t for s in self.track]
        if ts != sorted(ts):
            raise ValueError(f"{self.instance_id}: track samples must be sorted by t")
        if ts[0] < self.start - TIME_EPS or ts[-1] > self.end + TIME_EPS:
            raise ValueError(f"{self.instance_id}: track samples outside [{self.start}, {self.end}]")
        return self


SafetyStatus = Literal["reviewed", "partial", "unreviewed"]


class SafetyRecord(Contract):
    """Per-object ingest-time safety review (FR-PER-09). Anything not `reviewed` is treated as unsafe downstream."""

    status: SafetyStatus
    tags: list[SafetyTag] = []
    severity: Unit = 0.0
    child_unsafe: bool = False
    disagreement: bool = False
    reasons: dict[str, str] = {}
    models: dict[str, str] = {}

    @model_validator(mode="after")
    def _unreviewed_has_no_verdict(self) -> Self:
        if self.status == "unreviewed" and (self.tags or self.severity or self.child_unsafe):
            raise ValueError("an unreviewed object cannot carry tags/severity: nothing reviewed it")
        return self


BOARD_ONLY_FIELDS = ("element_kind", "content", "description")


class GraphObject(Contract):
    object_id: ObjectId
    label: str = Field(min_length=1)
    phrase_source: Literal["hazard_class", "vlm", "transcript", "board"]
    is_hazard_class: bool = False
    instances: list[ObjectInstance] = Field(min_length=1)
    safety: SafetyRecord
    # Board / animation elements (phrase_source "board"): what was written or drawn, read by the VLM.
    element_kind: Literal["text", "equation", "diagram", "table", "code", "chart", "illustration"] | None = None
    content: str | None = Field(default=None, max_length=600)
    description: str | None = Field(default=None, max_length=400)


class ConceptEvidence(Contract):
    segment_ids: list[SentenceId] = []
    text_ids: list[TextId] = []
    object_ids: list[ObjectId] = []


class ConceptNode(Contract):
    node_id: ConceptId
    label: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    evidence: ConceptEvidence
    prerequisites: list[ConceptId] = []
    difficulty: Level
    canonical_key: Annotated[str, StringConstraints(pattern=r"^concept:[a-z0-9_]+$")] | None = None


class ThreadRoleAssignment(Contract):
    segment_ids: list[SentenceId] = Field(min_length=1)
    role: ThreadRole
    gist: str


class QuizQuestion(Contract):
    question_id: QuestionId
    concept_node_id: ConceptId
    level: Level
    stem: str = Field(min_length=1)
    options: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    rationale: str
    evidence_segment_ids: list[SentenceId] = Field(min_length=1)
    verified_by: str

    @model_validator(mode="after")
    def _distinct_options(self) -> Self:
        normalized = [o.strip().lower() for o in self.options]
        if len(set(normalized)) != len(normalized) or any(not o for o in normalized):
            raise ValueError(f"{self.question_id}: options must be non-empty and distinct")
        return self


class PerceptionMeta(Contract):
    pipeline_version: str
    segmentation_tier: Literal["boxes", "sam2", "sam3", "fixture"]
    models: dict[str, str] = {}
    timings_s: dict[str, float] = {}
    degraded: Degraded = []
    stage_hashes: dict[str, str] = {}


class ConceptGraph(Contract):
    schema_version: SchemaVersion = SCHEMA_VERSION
    video_id: VideoId
    title: str
    source: SourceInfo
    video_url: str
    duration_seconds: float = Field(gt=0)
    frame: FrameInfo
    shots: list[Shot] = []
    transcript: list[Sentence] = []
    on_screen_text: list[TextSpan] = []
    objects: list[GraphObject] = []
    concept_nodes: list[ConceptNode] = []
    thread_roles: list[ThreadRoleAssignment] = []
    quiz_bank: list[QuizQuestion] = []
    perception_meta: PerceptionMeta
    graph_sha: Sha256 | None = None

    def compute_sha(self) -> str:
        d = self.model_dump(mode="json", exclude={"graph_sha"})
        for o in d.get("objects", []):  # board-only fields are hashed only when set: graphs sealed before them still verify
            for k in BOARD_ONLY_FIELDS:
                if o.get(k) is None:
                    o.pop(k, None)
        return sha256_of(d)

    def sealed(self) -> ConceptGraph:
        """Return a copy carrying its content hash (graphs are immutable once committed)."""
        return self.model_copy(update={"graph_sha": self.compute_sha()})

    @model_validator(mode="after")
    def _validate_graph(self) -> Self:
        d = self.duration_seconds
        for kind, ids in (
            ("shot", [s.shot_id for s in self.shots]),
            ("sentence", [s.seg_id for s in self.transcript]),
            ("text span", [t.text_id for t in self.on_screen_text]),
            ("object", [o.object_id for o in self.objects]),
            ("instance", [i.instance_id for o in self.objects for i in o.instances]),
            ("concept", [c.node_id for c in self.concept_nodes]),
            ("question", [q.question_id for q in self.quiz_bank]),
        ):
            if dups := find_duplicates(ids):
                raise ValueError(f"duplicate {kind} ids: {dups}")

        for s in self.shots:
            check_span(s.start, s.end, s.shot_id, d)
        for sent in self.transcript:
            check_span(sent.start, sent.end, sent.seg_id, d)
            for w in sent.words:
                if w.start < sent.start - TIME_EPS or w.end > sent.end + TIME_EPS or w.start > w.end:
                    raise ValueError(f"{sent.seg_id}: word {w.w!r} outside its sentence")
        for span in self.on_screen_text:
            check_span(span.start, span.end, span.text_id, d)

        shot_ids = {s.shot_id for s in self.shots}
        for obj in self.objects:
            if not all(i.instance_id.startswith(obj.object_id + "_") for i in obj.instances):
                raise ValueError(f"{obj.object_id}: instance ids must start with the object id")
            by_shot: dict[str, list[tuple[float, float]]] = {}
            for inst in obj.instances:
                check_span(inst.start, inst.end, inst.instance_id, d)
                if shot_ids and inst.shot_id not in shot_ids:
                    raise ValueError(f"{inst.instance_id}: unknown shot {inst.shot_id}")
                by_shot.setdefault(inst.shot_id, []).append((inst.start, inst.end))
            for shot, spans in by_shot.items():
                spans.sort()
                for (_, e1), (s2, _) in pairwise(spans):
                    if s2 < e1 - TIME_EPS:
                        raise ValueError(f"{obj.object_id}: instances overlap in time within {shot}")

        sentence_ids = {s.seg_id for s in self.transcript}
        text_ids = {t.text_id for t in self.on_screen_text}
        object_ids = {o.object_id for o in self.objects}
        position = {c.node_id: i for i, c in enumerate(self.concept_nodes)}
        for c in self.concept_nodes:
            ev = c.evidence
            if not ev.segment_ids and not ev.text_ids:
                raise ValueError(f"{c.node_id}: a concept must cite >= 1 sentence or on-screen text")
            for ref_kind, refs, known in (
                ("sentence", ev.segment_ids, sentence_ids),
                ("text span", ev.text_ids, text_ids),
                ("object", ev.object_ids, object_ids),
            ):
                if missing := sorted(set(refs) - known):
                    raise ValueError(f"{c.node_id}: unknown {ref_kind} ids {missing}")
            for p in c.prerequisites:
                if p not in position:
                    raise ValueError(f"{c.node_id}: unknown prerequisite {p}")
                if position[p] >= position[c.node_id]:
                    raise ValueError(f"{c.node_id}: prerequisite {p} must be an earlier concept")

        for tr in self.thread_roles:
            if missing := sorted(set(tr.segment_ids) - sentence_ids):
                raise ValueError(f"thread role cites unknown sentences {missing}")

        for q in self.quiz_bank:
            if q.concept_node_id not in position:
                raise ValueError(f"{q.question_id}: unknown concept {q.concept_node_id}")
            if missing := sorted(set(q.evidence_segment_ids) - sentence_ids):
                raise ValueError(f"{q.question_id}: unknown evidence sentences {missing}")

        if self.graph_sha is not None and self.graph_sha != self.compute_sha():
            raise ValueError("graph_sha does not match the graph content")
        return self


# ---------------------------------------------------------------- views (spec/05 §1 "Views")

GraphViewName = Literal["full", "mesh", "safety", "player"]


class SentenceView(Contract):
    seg_id: SentenceId
    start: Seconds
    end: Seconds
    text: str


class SafetySummary(Contract):
    status: SafetyStatus
    tags: list[SafetyTag] = []
    severity: Unit = 0.0
    child_unsafe: bool = False


class InstanceTimes(Contract):
    instance_id: InstanceId
    shot_id: ShotId
    start: Seconds
    end: Seconds


class ObjectSummary(Contract):
    object_id: ObjectId
    label: str
    is_hazard_class: bool
    instances: list[InstanceTimes]
    safety: SafetySummary


class QuizQuestionView(Contract):
    """A bank question without its answer — the only form that ever leaves the server."""

    question_id: QuestionId
    concept_node_id: ConceptId
    level: Level
    stem: str
    options: list[str]
    evidence_segment_ids: list[SentenceId]


class MeshGraphView(Contract):
    schema_version: SchemaVersion = SCHEMA_VERSION
    view: Literal["mesh"] = "mesh"
    video_id: VideoId
    graph_sha: Sha256 | None
    duration_seconds: float
    transcript: list[SentenceView]
    on_screen_text: list[TextSpan]
    objects: list[ObjectSummary]
    concept_nodes: list[ConceptNode]
    thread_roles: list[ThreadRoleAssignment]
    quiz_bank: list[QuizQuestionView]


class SafetyGraphView(Contract):
    schema_version: SchemaVersion = SCHEMA_VERSION
    view: Literal["safety"] = "safety"
    video_id: VideoId
    graph_sha: Sha256 | None
    duration_seconds: float
    objects: list[ObjectSummary]


class PlayerTrackSample(Contract):
    t: Seconds
    bbox: BBox


class PlayerInstance(Contract):
    instance_id: InstanceId
    start: Seconds
    end: Seconds
    track: list[PlayerTrackSample]


class PlayerObject(Contract):
    object_id: ObjectId
    label: str
    instances: list[PlayerInstance]


class PlayerConcept(Contract):
    node_id: ConceptId
    label: str
    summary: str


class PlayerGraphView(Contract):
    schema_version: SchemaVersion = SCHEMA_VERSION
    view: Literal["player"] = "player"
    video_id: VideoId
    graph_sha: Sha256 | None
    title: str
    video_url: str
    duration_seconds: float
    frame: FrameInfo
    transcript: list[SentenceView]
    on_screen_text: list[TextSpan]
    objects: list[PlayerObject]
    concept_nodes: list[PlayerConcept]


def _safety_summary(o: GraphObject) -> SafetySummary:
    s = o.safety
    return SafetySummary(status=s.status, tags=s.tags, severity=s.severity, child_unsafe=s.child_unsafe)


def _object_summary(o: GraphObject) -> ObjectSummary:
    return ObjectSummary(
        object_id=o.object_id,
        label=o.label,
        is_hazard_class=o.is_hazard_class,
        instances=[
            InstanceTimes(instance_id=i.instance_id, shot_id=i.shot_id, start=i.start, end=i.end) for i in o.instances
        ],
        safety=_safety_summary(o),
    )


def _sentences(g: ConceptGraph) -> list[SentenceView]:
    return [SentenceView(seg_id=s.seg_id, start=s.start, end=s.end, text=s.text) for s in g.transcript]


def mesh_view(g: ConceptGraph) -> MeshGraphView:
    return MeshGraphView(
        video_id=g.video_id,
        graph_sha=g.graph_sha,
        duration_seconds=g.duration_seconds,
        transcript=_sentences(g),
        on_screen_text=g.on_screen_text,
        objects=[_object_summary(o) for o in g.objects],
        concept_nodes=g.concept_nodes,
        thread_roles=g.thread_roles,
        quiz_bank=[
            QuizQuestionView(
                question_id=q.question_id,
                concept_node_id=q.concept_node_id,
                level=q.level,
                stem=q.stem,
                options=q.options,
                evidence_segment_ids=q.evidence_segment_ids,
            )
            for q in g.quiz_bank
        ],
    )


def safety_view(g: ConceptGraph) -> SafetyGraphView:
    return SafetyGraphView(
        video_id=g.video_id,
        graph_sha=g.graph_sha,
        duration_seconds=g.duration_seconds,
        objects=[_object_summary(o) for o in g.objects],
    )


def player_view(g: ConceptGraph) -> PlayerGraphView:
    return PlayerGraphView(
        video_id=g.video_id,
        graph_sha=g.graph_sha,
        title=g.title,
        video_url=g.video_url,
        duration_seconds=g.duration_seconds,
        frame=g.frame,
        transcript=_sentences(g),
        on_screen_text=g.on_screen_text,
        objects=[
            PlayerObject(
                object_id=o.object_id,
                label=o.label,
                instances=[
                    PlayerInstance(
                        instance_id=i.instance_id,
                        start=i.start,
                        end=i.end,
                        track=[PlayerTrackSample(t=s.t, bbox=s.bbox) for s in i.track],
                    )
                    for i in o.instances
                ],
            )
            for o in g.objects
        ],
        concept_nodes=[PlayerConcept(node_id=c.node_id, label=c.label, summary=c.summary) for c in g.concept_nodes],
    )


def graph_view(g: ConceptGraph, view: GraphViewName) -> Contract:
    match view:
        case "full":
            return g
        case "mesh":
            return mesh_view(g)
        case "safety":
            return safety_view(g)
        case "player":
            return player_view(g)
