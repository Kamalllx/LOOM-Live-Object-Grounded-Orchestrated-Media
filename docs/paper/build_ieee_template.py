"""Build the LOOM paper inside the official IEEE A4 conference template (docs/paper/conference-template-a4.docx).

The template file is kept intact - styles, numbering, settings, section layout - and only its content is
replaced, using the template's own paragraph styles (papertitle, Author, Abstract, Keywords, Heading1/2/5,
BodyText, bulletlist, equation, figurecaption, tablehead/tablecolhead/tablecopy, references).
Headings, figure captions, table heads and references are numbered by the template's styles.
Every number is read from data/eval/*.json, like build_paper.js.

    .venv/bin/python docs/paper/build_ieee_template.py   ->  docs/paper/LOOM_IEEE_Conference.docx
"""
import json
import pathlib
import re
import shutil
import struct
import tempfile
import zipfile
from xml.sax.saxutils import escape

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TEMPLATE = HERE / "conference-template-a4.docx"
OUT = HERE / "LOOM_IEEE_Conference.docx"
FIG = ROOT / "docs" / "figures"
EVAL = ROOT / "data" / "eval"

A_NS = "http://purl.oclc.org/ooxml/drawingml/main"
PIC_NS = "http://purl.oclc.org/ooxml/drawingml/picture"
IMG_REL = "http://purl.oclc.org/ooxml/officeDocument/relationships/image"
COL_PT, FULL_PT = 243, 504          # text column / full text width of the template's body section, in points


def load(name):
    p = EVAL / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


perception, critic, animator = load("perception"), load("critic"), load("animator")
sessions, sessions_before = load("sessions"), load("sessions_before_time_padding")
graph = json.loads((ROOT / "data" / "graphs" / "vid_demo_neutralization.json").read_text())
gt = json.loads((EVAL / "groundtruth_vid_demo_neutralization.json").read_text())


def run_of(learner, which="first", src=None):
    src = src or sessions
    return next(r for r in src["runs"] if r["learner"] == learner and r["run"] == which)


alex, priya, fam = run_of("learner_alex"), run_of("learner_priya"), run_of("learner_family")
fam_before = run_of("learner_family", src=sessions_before)
ab = perception["grounding"]["ablation"]
ab_det, ab_gen, ab_loom = ab["detector_only"], ab["+clip_verify_generic"], ab["+clip_verify_hazard_lookalikes (LOOM)"]
f2 = lambda x: f"{x:.2f}"
pct = lambda x: f"{100 * x:.1f}%"
dur = graph["duration_seconds"]
rejected = [r for r in animator["runs"] if not r["critic_pass"]]
caught = critic["faults"] - round(critic["faults"] * (1 - critic["detection_rate"]))

# ---------------------------------------------------------------- XML helpers

def runs(text, base_rpr=""):
    """Inline markup: **bold**, ~~italic~~. Everything else is literal text."""
    out = []
    for tok in re.split(r"(\*\*[^*]+\*\*|~~[^~]+~~)", text):
        if not tok:
            continue
        rpr = base_rpr
        if tok.startswith("**"):
            tok, rpr = tok[2:-2], base_rpr + "<w:b/><w:bCs/>"
        elif tok.startswith("~~"):
            tok, rpr = tok[2:-2], base_rpr + "<w:i/><w:iCs/>"
        out.append(f'<w:r>{"<w:rPr>" + rpr + "</w:rPr>" if rpr else ""}<w:t xml:space="preserve">{escape(tok)}</w:t></w:r>')
    return "".join(out)


def para(style, text="", ppr_extra="", rpr=""):
    return f'<w:p><w:pPr><w:pStyle w:val="{style}"/>{ppr_extra}</w:pPr>{runs(text, rpr)}</w:p>'


body = lambda t: para("BodyText", t)
h1 = lambda t: para("Heading1", t)
h2 = lambda t: para("Heading2", t)
h5 = lambda t: para("Heading5", t)
bullet = lambda t: para("bulletlist", t)
cont = lambda t: para("BodyText", t, '<w:ind w:firstLine="0pt"/>')   # text continuing after an equation


def equation(expr, number):
    tnr = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/>'
    # The template's equation tabs (126/252 pt) are for a 252 pt column; this layout's column is 243 pt.
    tabs = ('<w:tabs><w:tab w:val="clear" w:pos="126pt"/><w:tab w:val="clear" w:pos="252pt"/>'
            f'<w:tab w:val="center" w:pos="{COL_PT / 2}pt"/><w:tab w:val="end" w:pos="{COL_PT}pt"/></w:tabs>')
    return (f'<w:p><w:pPr><w:pStyle w:val="equation"/>{tabs}</w:pPr><w:r><w:tab/></w:r>{runs(expr, tnr + "<w:i/>")}'
            f'<w:r><w:rPr>{tnr}</w:rPr><w:tab/><w:t>({number})</w:t></w:r></w:p>')


def table(caption, header, rows, widths_pt):
    grid = "".join(f'<w:gridCol w:w="{int(w * 20)}"/>' for w in widths_pt)
    borders = "".join(f'<w:{s} w:val="single" w:sz="2" w:space="0" w:color="auto"/>'
                      for s in ("top", "start", "bottom", "end", "insideH", "insideV"))

    def cell(text, style, w, first):
        jc = "" if first else '<w:jc w:val="center"/>'
        return (f'<w:tc><w:tcPr><w:tcW w:w="{w}pt" w:type="dxa"/><w:vAlign w:val="center"/></w:tcPr>'
                f'<w:p><w:pPr><w:pStyle w:val="{style}"/>{jc}</w:pPr>{runs(str(text))}</w:p></w:tc>')

    head = ('<w:tr><w:trPr><w:cantSplit/><w:tblHeader/><w:jc w:val="center"/></w:trPr>'
            + "".join(cell(h, "tablecolhead", w, False) for h, w in zip(header, widths_pt)) + "</w:tr>")
    body_rows = "".join('<w:tr><w:trPr><w:cantSplit/><w:jc w:val="center"/></w:trPr>'
                        + "".join(cell(c, "tablecopy", w, i == 0) for i, (c, w) in enumerate(zip(r, widths_pt)))
                        + "</w:tr>" for r in rows)
    tbl = (f'<w:tbl><w:tblPr><w:tblW w:w="0pt" w:type="auto"/><w:jc w:val="center"/><w:tblBorders>{borders}'
           f'</w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>{grid}</w:tblGrid>{head}{body_rows}</w:tbl>')
    return para("tablehead", caption, "<w:keepNext/>") + tbl + '<w:p><w:pPr><w:spacing w:after="6pt"/></w:pPr></w:p>'


IMAGES = []   # (rel_id, source path, media name)


def figure(file, caption, width_pt):
    src = FIG / file
    with open(src, "rb") as f:
        w_px, h_px = struct.unpack(">II", f.read(24)[16:24])
    n = len(IMAGES) + 1
    rid, name = f"rIdLoomImg{n}", f"loom_fig{n}.png"
    IMAGES.append((rid, src, name))
    cx = int(width_pt * 12700)
    cy = int(cx * h_px / w_px)
    drawing = (
        f'<w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
        f'<wp:docPr id="{100 + n}" name="Figure {n}"/><wp:cNvGraphicFramePr>'
        f'<a:graphicFrameLocks xmlns:a="{A_NS}" noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        f'<a:graphic xmlns:a="{A_NS}"><a:graphicData uri="{PIC_NS}"><pic:pic xmlns:pic="{PIC_NS}">'
        f'<pic:nvPicPr><pic:cNvPr id="{100 + n}" name="{name}"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
        f'</wp:inline></w:drawing>')
    img = (f'<w:p><w:pPr><w:keepNext/><w:spacing w:before="6pt" w:after="0pt"/><w:ind w:firstLine="0pt"/>'
           f'<w:jc w:val="center"/></w:pPr><w:r>{drawing}</w:r></w:p>')
    return img + para("figurecaption", caption)


# ---------------------------------------------------------------- section breaks (template geometry)
PAGE = '<w:pgSz w:w="595.30pt" w:h="841.90pt" w:code="9"/>'
BODY_MAR = '<w:pgMar w:top="54pt" w:right="45.35pt" w:bottom="72pt" w:left="45.35pt" w:header="36pt" w:footer="36pt" w:gutter="0pt"/>'
AUTH_MAR = '<w:pgMar w:top="22.50pt" w:right="44.65pt" w:bottom="72pt" w:left="44.65pt" w:header="36pt" w:footer="36pt" w:gutter="0pt"/>'


def sect(cols, space, mar=BODY_MAR):
    num = f' w:num="{cols}"' if cols > 1 else ""
    return (f'<w:sectPr><w:type w:val="continuous"/>{PAGE}{mar}<w:cols{num} w:space="{space}"/>'
            f'<w:docGrid w:linePitch="360"/></w:sectPr>')


def section_break(cols, space, mar=BODY_MAR):
    return f"<w:p><w:pPr>{sect(cols, space, mar)}</w:pPr></w:p>"


TWO_COL_END = section_break(2, "18pt")      # closes a run of two-column text
FULL_WIDTH_END = section_break(1, "18pt")   # closes a block of full-width figures

# ---------------------------------------------------------------- authors
AUTHORS = [
    ("Manya Ravishankar", "1ms23cs227@msrit.edu"),
    ("Rana Adiba", "1ms23cs228@msrit.edu"),
    ("Kamal Karteek U", "1ms23cs229@msrit.edu"),
    ("Jeevika R", "1ms23cs230@msrit.edu"),
]
AUTHOR_PPR = ('<w:pStyle w:val="Author"/><w:spacing w:before="6pt" w:after="12pt"/>'
              '<w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr>')


def author_block(name, email, column_break_after):
    sz = "<w:sz w:val=\"18\"/><w:szCs w:val=\"18\"/>"
    lines = [(name, ""), ("Dept. of Computer Science and Engineering", "<w:i/>"),
             ("Ramaiah Institute of Technology", "<w:i/>"), ("Bengaluru, India", ""), (email, "")]
    out = ""
    for k, (text, extra) in enumerate(lines):
        br = "<w:br/>" if k else ""
        out += f'<w:r><w:rPr>{extra}{sz}</w:rPr>{br}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'
    # Column break at the END of the left author (as in the template), so both columns start level.
    if column_break_after:
        out += '<w:r><w:br w:type="column"/></w:r>'
    return f"<w:p><w:pPr>{AUTHOR_PPR}</w:pPr>{out}</w:p>"


def author_table():
    """2 x 2 borderless table of author blocks: aligns identically in Word and LibreOffice (column sections do not)."""
    none = "".join(f'<w:{s} w:val="nil"/>' for s in ("top", "start", "bottom", "end", "insideH", "insideV"))
    half = FULL_PT // 2
    rows = ""
    for pair in (AUTHORS[0:2], AUTHORS[2:4]):
        cells = "".join(f'<w:tc><w:tcPr><w:tcW w:w="{half}pt" w:type="dxa"/></w:tcPr>{author_block(n, e, False)}</w:tc>'
                        for n, e in pair)
        rows += f'<w:tr><w:trPr><w:cantSplit/><w:jc w:val="center"/></w:trPr>{cells}</w:tr>'
    return (f'<w:tbl><w:tblPr><w:tblW w:w="{2 * half}pt" w:type="dxa"/><w:jc w:val="center"/>'
            f'<w:tblBorders>{none}</w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr>'
            f'<w:tblGrid><w:gridCol w:w="{half * 20}"/><w:gridCol w:w="{half * 20}"/></w:tblGrid>{rows}</w:tbl>')


authors_xml = (author_table()
               + f'<w:p><w:pPr><w:spacing w:before="0pt" w:after="6pt"/>{sect(1, "36pt", AUTH_MAR)}</w:pPr></w:p>')

# ---------------------------------------------------------------- content
TITLE = "LOOM: A Verified Multi-Agent System for Object-Level Personalization of Instructional Video"

ABSTRACT = (
    "Every platform that plays instructional video can pause, speed up, reorder, or block a video, but none can act on a "
    "single object inside a frame. LOOM (Live, Object-grounded, Orchestrated Media) keeps one set of source material "
    "— footage, transcript, on-screen text and individually tracked objects — and weaves a different, verified cut "
    "for each viewer. A perception pipeline fuses Whisper speech recognition, OCR and text-prompted open-vocabulary "
    "grounding into a spatio-temporal concept graph; a mesh of specialist agents that discover and task each other "
    "through Agent2Agent (A2A) Agent Cards builds a personalized candidate cut; and a bounded Perceive–Plan–Act–"
    "Verify loop, gated by a Critic agent, checks every cut before delivery. A Guardian agent masks only the unsafe object "
    "for a given viewer, and an Animator agent writes, statically checks, renders and caches Manim explainer animations on "
    f"demand. On a narrated chemistry lesson with ground truth, the Critic caught {caught} of {critic['faults']} injected "
    f"faults with {critic['false_rejections']} false rejections, per-object redaction reached a temporal precision of "
    f"{f2(fam['redaction_vs_truth']['precision'])} and recall of {f2(fam['redaction_vs_truth']['recall'])} with no safe "
    f"content blocked, and three viewer profiles received cuts of {pct(alex['source_ratio'])}, {pct(priya['source_ratio'])} "
    f"(+{priya['explainers']} generated explainers) and {pct(fam['source_ratio'])} (+{fam['masks']} object mask) of the same source."
)
KEYWORDS = ("multi-agent systems, Agent2Agent protocol, open-vocabulary grounding, personalized video learning, "
            "content redaction, verification loops, generative animation")

content = []
add = content.append

add(h1("Introduction"))
add(body("Picture one ten-minute instructional video watched by three people. An expert who already knows the basics leaves "
         "before the one new idea at minute eight; a beginner falls behind by minute two because the video assumes background "
         "they lack; and a parent watching with a child closes the whole video because of one unwanted moment. All three "
         "failures have one cause: a video file is a single fixed sequence of pixels, and every tool built on top of it — "
         "hosting, quiz overlays, dubbing, analytics — operates on the asset as a whole."))
add(body("Adaptive-video research personalizes at the level of whole clips or chapters [1], [2]; multi-agent tutors personalize "
         "the learning path around a video but never the video itself [3], [4]; and moderation systems return one label per "
         "video, forcing a block-or-allow decision [5]–[7]. None of them can reach inside the frame. LOOM moves the unit of "
         "personalization from “which video plays” to “which object, in which frame, for this viewer”, and does "
         "so without shipping anything unchecked. This paper makes five contributions:"))
add(bullet("**Object-grounded perception with safety-first vocabulary.** The transcript and on-screen text decide which objects "
           "to ground, while a fixed hazard vocabulary is always searched; hazard detections must additionally beat visual "
           "look-alikes under CLIP verification (Section IV-A)."))
add(bullet("**An open agent mesh.** Curator, Pedagogy, Personalizer and Assessment agents, plus any third-party agent, are "
           "discovered and tasked only through A2A Agent Cards and JSON-RPC, over versioned JSON contracts (Section IV-B)."))
add(bullet("**A bounded, Critic-gated verification loop** with structured issues, local repair, mesh revision, a fixed budget and "
           "a fallback to the last verified cut (Section IV-C)."))
add(bullet("**Per-object, per-viewer redaction** and **agent-authored Manim explainers** that pass an AST safety gate, a repair "
           "loop and a fact-check before any viewer sees them."))
add(bullet("**An evaluation with ground truth and fault injection**, including the failure modes found while building the "
           "system and how each was fixed (Sections V–VII)."))

add(h1("Related Work"))
add(h2("Adaptive and Interactive Instructional Video"))
add(body("Hypervideo models add navigation and interaction around a fixed video [8]. Sanal Kumar and Thandeeswaran deliver "
         "pre-segmented instructional videos according to a learner’s style [1]; reviews of AI-based personalized learning "
         "[2], [9] describe the same granularity: content is selected, sequenced or paced, but never altered inside the frame. "
         "PAL turns a lecture video into an interactive session whose question difficulty adapts through reinforcement "
         "learning [10], yet it also leaves the video itself untouched."))
add(h2("Multi-Agent AI in Education"))
add(body("EduPlanner uses evaluator, optimizer and analyst agents that refine lesson plans adversarially [3]; GenMentor "
         "coordinates agents for goal-oriented tutoring [4]. Both operate on text and use a fixed, in-house agent set. Baarslag "
         "et al. identify the lack of standard interoperability and of a trust gate before an agent’s decision takes effect "
         "as open challenges for autonomous agents [11]. LOOM uses the A2A protocol [20] for the first and a Critic loop for "
         "the second."))
add(h2("Content Safety for Young Viewers"))
add(body("Ayadi combines visual semantics with emotional context to classify content for young users [5]; Chuttur and "
         "Nazurally [6] and Yousaf and Nawaz [7] classify whole cartoon or YouTube videos. Classical texture classifiers such as "
         "optimized local ternary patterns likewise label whole images from a closed set [12]. Each of these outputs one "
         "decision per video or image; LOOM instead masks one object for one viewer and keeps the rest."))
add(h2("Generated Explanations and Self-Refinement"))
add(body("Animated concept maps improve cognitive achievement over static material, and structure rather than affect mediated "
         "the gain [13]; an AI digital teacher improved performance and achievement emotions in a randomized trial [14]. Both "
         "use material authored in advance. Self-Refine shows that LLM outputs improve through iterative self-feedback [15]; "
         "LOOM applies a bounded version of this idea to personalized media, with an independent Critic and a hard budget."))
add(h2("Perception Foundations"))
add(body("SAM 3 segments and tracks every instance of a concept named by a short phrase [16]. Grounding DINO offers open-set, "
         "text-prompted detection [17], CLIP aligns images with text [18], and Whisper provides robust speech recognition [19]."))

add(h1("System Architecture"))
add(body("LOOM is four services joined by four JSON contracts, each a JSON Schema validated by its producer before hand-off "
         "(Fig. 1). **Contract A** (concept graph) carries objects with per-instance time ranges, normalized boxes and "
         "per-second tracks, the transcript, on-screen text and concept nodes that link them. **Contract A2** (learner profile) "
         "holds a mastery value per concept, pace and a family safety profile. **Contract B** (candidate cut) lists threads with "
         "actions, explainer and redaction requests, a quiz and an agent trace. **Contract C** (verified cut) adds masks, "
         "explainer clips, Critic scores and the loop trace. **Contract D** (session log) records what the viewer did and is "
         "folded back into A2."))
add(body("Every agent publishes an A2A Agent Card at /.well-known/agent.json (name, version, skills with input and output) and "
         "is tasked only with JSON-RPC message/send, with contract JSON carried as a data part. The orchestrator keeps a "
         "registry of cards and selects agents by skill identifier, so a third-party agent joins by URL. In the evaluation, a "
         "separate-process “school policy” agent was registered at run time and its redaction requests were merged "
         "into sessions without code changes to LOOM."))
add(TWO_COL_END)
add(figure("architecture.png", "LOOM as built: four services joined by JSON contracts A–D. Every agent, including a "
           "third-party plug-in, is discovered through its A2A Agent Card; the verification loop sends structured Critic "
           "issues back to the mesh through the orchestrator’s revise_cut skill.", FULL_PT))
add(FULL_WIDTH_END)

add(h1("Methods"))
add(h2("Perception: From Pixels to a Concept Graph"))
add(body("Video is normalized with ffmpeg; speech is transcribed with Whisper large-v3-turbo [19] and on-screen text is read by "
         "Tesseract once per second, merging readings that occupy the same screen region so that a caption flickering over "
         "moving footage becomes one item. An LLM reads the transcript and on-screen text and proposes up to six visible, solid "
         "lesson objects; to these a fixed hazard vocabulary (broken glass, knife, open flame) is always appended, because "
         "redaction must not depend on a narrator happening to mention a hazard."))
add(body("SAM 3.1 requires a data-centre GPU, so on commodity hardware the grounding step uses the same concept-prompt "
         "interface with Grounding DINO [17] at one sample per second, greedy IoU tracking, and a verification step: each track "
         "is cropped from up to three frames and scored by CLIP [18] against all prompts plus generic distractors. Lesson "
         "objects must rank in the top two and beat every distractor; **hazard tracks must rank first against additional "
         "look-alikes** (intact glassware, a stirring rod, a red liquid) and persist for two samples. An LLM then fuses "
         "sentences, text and objects into concept nodes with prerequisites; a grounding check keeps only objects visible while "
         "the concept is on screen."))
add(h2("Agent Mesh: Building the Candidate Cut"))
add(body("The **Curator** partitions the timeline at sentence boundaries, so no thread starts or ends mid-sentence, and an LLM "
         "labels each thread’s role (intro, setup, core, safety, summary). The **Pedagogy** agent applies an auditable "
         "policy to the learner’s mastery m of the thread’s concepts:"))
add(equation("a(m) ∈ {skip, condense, keep, expand}", 1))
add(cont("chosen for m ≥ 0.80, m ≥ 0.60, m ≥ 0.35 and below 0.35 respectively, with thresholds shifted by the "
         "learner’s pace and role rules on top: core and safety content is condensed rather than skipped, a concept whose prerequisite is not "
         "mastered is never skipped, and explainers are spent only on core and setup threads. The **Personalizer** trims "
         "condensed threads to about half, ending on a sentence boundary and never before an on-screen formula has been shown "
         "for 3 s, anchors an automatic explainer after each expanded thread, and adds a tap-to-learn request for every concept "
         "with a tracked object. The **Assessment** agent writes multiple-choice checks grounded in transcript excerpts, "
         "prioritising the least-mastered concepts, and updates mastery from the session log after a correct answer as"))
add(equation("m ← m + 0.35 (1 − m)", 2))
add(cont("and after a wrong answer as m ← 0.75 m; each watched explainer adds 0.05 (1 − m)."))
add(h2("Verification: Guardian, Animator, Critic and the Bounded Loop"))
add(body("**Guardian.** Each tracked object is tagged from a fixed taxonomy with a severity by a dedicated safety model "
         "(gpt-oss-safeguard-20b), judged in lesson context and cached per video. For a viewer, an object is redacted if any tag "
         "is in the profile’s blocked tags, or if it exceeds the level’s severity threshold (standard 0.5 and "
         "child-unsafe, strict 0.2). The mesh’s requests are hints only: the Guardian reviews every visible object, so a "
         "hazard the mesh missed is still caught, and third-party requests are honoured because over-masking is the safe side. "
         "Masks follow the object’s per-second track with 4% spatial padding and are padded in time by one sampling "
         "interval, since an object seen at sample t may be on screen anywhere in (t−1 s, t+1 s)."))
add(body("**Animator.** For a concept and learner level, an LLM returns a spoken storyboard and Manim Community [21] code. "
         "Before execution, the code passes an AST allow-list (imports limited to manim, math and numpy; no open, exec, eval, "
         "dunder access, external media or LaTeX when unavailable). It is rendered in a subprocess with a timeout; a compile or "
         "render error is returned to the LLM for up to two repairs. The storyboard is narrated with text-to-speech and the "
         "clip is cached by concept and level, so later learners receive it instantly."))
add(body("**Critic.** Three scores in [0, 1] are computed from auditable checks. Safety is the fraction of flagged-object screen "
         "time inside the cut that is covered by a mask, with H the set of 0.1 s instants inside the cut where a flagged object "
         "is visible and M the instants covered by one of its masks:"))
add(equation("S_safety = |H ∩ M| / |H|", 3))
add(cont("Coherence starts at 1 and is penalized for overlapping or unordered threads (0.25), a thread ending mid-sentence "
         "(0.15), a missing prerequisite for a learner below 0.35 mastery (0.10) and an unavailable explainer (0.10). "
         "Factuality is the share of generated claims — every quiz question with its marked answer and every storyboard "
         "sentence — that an LLM judge finds supported by the lesson transcript and on-screen text. A cut is approved only "
         "if S_safety = 1, coherence and factuality are at least 0.8, **and no individual check raised an issue**: averages hide "
         "individual failures, so one unsupported sentence in one explainer blocks delivery. An explainer clip that has passed "
         "once is recorded and not re-judged, because it is immutable."))
add(body("**Bounded loop.** Each pass runs four phases. ~~Perceive~~: the Guardian builds masks for the cut and the Animator "
         "renders the cut’s automatic explainers in parallel, from cache when possible. ~~Plan~~: the Critic scores the cut "
         "and emits structured issues {code, message, target}. ~~Verify~~: if approved, the cut is delivered and recorded as the "
         "last verified cut for this video and learner. ~~Act~~: otherwise verification fixes what it owns — it re-renders "
         "an unfaithful explainer with the Critic’s reasons (once, then drops it) or forces a mask on an unmasked hazard "
         "— and sends the remaining issues to the orchestrator’s revise_cut skill over A2A for the next candidate. The "
         "budget is three passes. When it is spent, the viewer receives the last verified cut for this video and learner or, if "
         "none exists, a conservative baseline: the full lesson with every safety-tagged object masked under the strict policy "
         "and no generated content. Tap-to-learn explainers follow the same rule with a budget of two."))
add(h2("Delivery and Memory"))
add(body("A Next.js player plays only the verified threads, pauses at each automatic explainer, and composites masks "
         "client-side as blurred regions that follow interpolated tracks, so the base video is never re-encoded per viewer. "
         "Tappable regions are drawn for tracked objects that belong to a concept and never on top of a mask. Loop progress "
         "streams to the player over server-sent events; at the end, the quiz result is posted as a session log and the updated "
         "mastery graph seeds the next session."))

add(h1("Experimental Setup"))
add(body(f"**Lesson.** A {dur:.1f} s narrated lesson on acid–base neutralization was assembled from five royalty-free "
         "Pexels clips, with narration synthesized by text-to-speech and three burned-in text cards (the reaction NaOH + HCl "
         "→ NaCl + H₂O, “pH 7 = neutral”, and a summary). One segment shows a glass jar shattering on a table. "
         "Because the lesson was built for the study, its ground truth is exact: the narration script, every card’s text "
         f"and time range, and the hazard window (shards visible from {gt['hazards'][0]['start'] + 0.8:.2f} s to "
         f"{gt['hazards'][0]['end']:.2f} s)."))
add(body("**Viewers.** Alex (expert, prior mastery 0.85, condensed pace, no redaction), Priya (beginner, prior 0.2, detailed "
         "pace, no redaction) and Parent + child (prior 0.4, standard redaction, blocked tags sharp_object and injury_risk)."))
add(body("**Implementation.** Python 3.11 services behind FastAPI; a Next.js 15 player; LLMs served by Groq (gpt-oss-120b for "
         "agents and the Critic, gpt-oss-safeguard-20b for the Guardian, Qwen3 as automatic fallback); Whisper large-v3-turbo; "
         "Grounding DINO-tiny and CLIP ViT-B/32 on an Apple-silicon laptop; Manim Community 0.21; loop budget 3. Every number "
         "below is produced by the project’s evaluation script (scripts/evaluate.py), and the raw results are kept with "
         "the code (data/eval)."))

add(h1("Results"))
add(h2("Perception"))
add(body(f"Speech recognition reached a word error rate of {pct(perception['asr']['wer'])} over "
         f"{perception['asr']['ref_words']} reference words (on synthesized narration, which is easier than classroom speech). "
         "After fusion, which corrected raw Tesseract confusions such as “HCI” → “HCl” and “H20” "
         f"→ “H₂O”, {pct(perception['ocr']['recall_at_0.8'])} of the burned-in text cards were recovered at "
         f"≥ 0.8 character similarity with a mean temporal IoU of {f2(perception['ocr']['mean_temporal_iou'])}. Fusion "
         f"produced {len(graph['concept_nodes'])} concept nodes with a prerequisite chain. Table I isolates the effect of "
         "verification on hazard grounding."))
add(table("Hazard Grounding Against Ground Truth (False = Safe Footage Flagged)",
          ["Configuration", "Tracks", "Hazard", "Prec.", "Rec.", "False"],
          [["Detector + tracking", ab_det["tracks"], ab_det["hazard_tracks"], f2(ab_det["precision"]), f2(ab_det["recall"]), f"{ab_det['false_block_s']} s"],
           ["+ CLIP, generic negatives", ab_gen["tracks"], ab_gen["hazard_tracks"], f2(ab_gen["precision"]), f2(ab_gen["recall"]), f"{ab_gen['false_block_s']} s"],
           ["+ CLIP, hazard look-alikes", ab_loom["tracks"], ab_loom["hazard_tracks"], f2(ab_loom["precision"]), f2(ab_loom["recall"]), f"{ab_loom['false_block_s']} s"]],
          [76, 36, 38, 30, 30, 33]))
add(body(f"Raw open-vocabulary detection fired on intact beakers, a stirring rod and a red liquid when prompted with hazard "
         f"phrases, flagging {ab_det['false_block_s']} s of safe footage. Generic CLIP distractors reduced this to "
         f"{ab_gen['false_block_s']} s; requiring hazards to beat visual look-alikes removed every false hazard while keeping the "
         f"real one. The price is recall ({f2(ab_det['recall'])} → {f2(ab_loom['recall'])}), which the Guardian’s "
         "temporal padding recovers (Section VI-D). The detector-only row is recomputed from cached detections with the "
         "pipeline’s tracking code; the two CLIP rows were measured on the same cached detections during development, and "
         "the last row equals the concept graph used in all other experiments."))
add(h2("The Critic Catches Injected Faults"))
add(body(f"{critic['faults']} faults were planted in real candidate cuts across six families, and {critic['controls']} correct "
         f"items were presented as controls (Table II). The Critic flagged and blocked every fault (detection "
         f"{pct(critic['detection_rate'])}) and rejected {critic['false_rejections']} of {critic['controls']} controls."))
fam_counts = critic["by_family"]
add(table("Fault Injection: Flagged and Blocked / Injected", ["Fault family", "Check", "Caught"],
          [["F1 hazard mask removed or cut short", "safety coverage", fam_counts["F1"]],
           ["F2 wrong answer marked in quiz", "LLM judge", fam_counts["F2"]],
           ["F3 false sentence in explainer", "LLM judge", fam_counts["F3"]],
           ["F4 thread ends mid-sentence", "coherence", fam_counts["F4"]],
           ["F5 prerequisite dropped (beginner)", "coherence", fam_counts["F5"]],
           ["F6 overlapping threads", "coherence", fam_counts["F6"]],
           ["Controls wrongly rejected", "all", f"{critic['false_rejections']}/{critic['controls']}"]],
          [132, 62, 40]))
add(body("The first version of the Critic approved a cut whose factuality averaged 0.93 although one explainer was "
         "unsupported, and approved a mid-sentence cut because its penalty left coherence at 0.85. Both were fixed by the rule "
         "that any individual issue blocks approval; F3 and F4 in Table II are measured after that change."))
add(h2("The Loop Repairs What It Finds"))
add(body("In Priya’s first session the Animator’s explainer for the indicator concept claimed that the indicator "
         "“is red in acidic solution and turns green when the pH reaches 7”. The lesson never states colours, so the "
         "Critic rejected pass 1 (factuality 0.889) with that sentence as feedback. In the Act phase the Animator re-rendered the "
         "explainer with the feedback, and pass 2 was approved with factuality 1.00 — the viewer never saw the invented "
         "detail."))
rv, rvb = fam["redaction_vs_truth"], fam_before["redaction_vs_truth"]
add(h2("Per-Object Redaction"))
add(body(f"For the Parent + child viewer the Guardian masked only the shards; nothing else in the lesson was blocked (Fig. 2). "
         f"Against the ground-truth hazard window, time-level precision was {f2(rv['precision'])} and recall {f2(rv['recall'])} "
         f"({rv['missed_s']} s unmasked, {rv['false_block_s']} s of safe content blocked). Without temporal padding recall was "
         f"{f2(rvb['recall'])} ({rvb['missed_s']} s unmasked): one-second sampling and the two-sample persistence rule start "
         "the mask late. The Critic scored safety 1.00 in both cases — it can only verify coverage of hazards that "
         "perception detected."))
add(TWO_COL_END)
add(figure("redaction_pair.png", "Per-object redaction. Left: source frame at 60.5 s. Right: what the Parent + child viewer "
           "sees — only the broken glass is blurred and labelled; the rest of the lesson plays normally.", FULL_PT))
add(figure("weaves.png", "Same threads, a different weave per viewer: verified cuts for the three profiles over the 74.6 s "
           "source (amber: kept, light: condensed, grey: skipped, purple: generated explainer, pink: per-object mask).", FULL_PT))
add(figure("explainer_strip.png", "Frames of an Animator-generated Manim explainer for the neutralization concept (H⁺ and "
           "OH⁻ merge into H₂O; Na⁺ and Cl⁻ form NaCl). The last two frames show a label-overlap defect "
           "that the Critic does not check.", FULL_PT))
add(FULL_WIDTH_END)

add(h2("Three Viewers, Three Weaves"))
ready = [r["time_to_first_frame_s"] for r in (alex, priya, fam)]
add(body(f"Fig. 3 shows the verified cuts. Alex received {alex['source_kept_s']} s ({pct(alex['source_ratio'])}) of condensed "
         "threads: the intro was skipped, and core and safety ideas were kept as refreshers. Priya received the full lesson "
         f"with {priya['explainers']} generated Manim explainers ({priya['explainer_s']} s) after the core threads. Parent + "
         f"child received the full lesson with {fam['masks']} object mask. All cuts were approved; with warm caches, a verified "
         f"cut was ready {min(ready)}–{max(ready)} s after pressing play (Table III); the cost of generating explainers "
         "fresh is reported below."))
add(table("Personalized Cuts of the Same 74.6 s Source", ["Viewer", "Kept", "Explainers", "Masks", "Quiz", "Passes"],
          [[n, pct(r["source_ratio"]), r["explainers"], r["masks"], r["quiz"], r["pass_count"]]
           for n, r in (("Alex (expert)", alex), ("Priya (beginner)", priya), ("Parent + child", fam))],
          [64, 36, 50, 34, 28, 31]))
add(h2("Animator"))
add(body(f"Generating {animator['explainers']} fresh explainers (six concepts at two levels), "
         f"{pct(animator['render_success_rate'])} rendered successfully, {pct(animator['first_attempt_compile_rate'])} on the "
         f"first attempt (mean {animator['mean_attempts']} attempts), with a median of {animator['median_render_s']} s from "
         "request to narrated clip; the AST gate was never triggered by generated code and rejected all five unsafe patterns in "
         f"unit tests. Only {pct(animator['critic_pass_rate_first_draft'])} of first drafts passed the Critic unchanged. Of the "
         f"{len(rejected)} rejected drafts, one invented a fact the lesson never states (indicator colours), two overstated it "
         "(“harmless” products; “always … immediately”) and two described scene details the source does "
         "not support. Code that compiles is therefore not the bottleneck; faithfulness is, and without the Critic "
         f"{len(rejected)} of {animator['explainers']} explainers would have reached viewers unchecked. Expert-level drafts, "
         "which add more detail, were rejected more often than beginner drafts "
         f"({sum(r['level'] == 'expert' for r in rejected)} vs {sum(r['level'] == 'beginner' for r in rejected)} of "
         f"{animator['explainers'] // 2})."))

add(h1("Discussion and Limitations"))
add(bullet("**SAM 3.1 was not run.** It needs a data-centre GPU; Grounding DINO with tracking and CLIP verification was used "
           "behind the same concept-prompt interface, so the object-level design can be exercised on a laptop. Masks are "
           "boxes, not pixel-accurate segments, and a few stray shards far from the main pile remained visible."))
add(bullet("**Verification is bounded by perception.** The Critic can prove that detected hazards are covered, not that every "
           f"hazard was detected; the {rv['missed_s']} s of unmasked shards is invisible to it. Temporal padding and denser "
           "sampling on hazards reduce, but do not remove, this gap."))
add(bullet("**Same-family judge.** Explainers and the factuality judge both use LLMs from one provider; self-preference bias "
           "is possible. The Critic’s safety and coherence checks are deterministic for this reason, and the judge is "
           "grounded only in the lesson’s own transcript."))
add(bullet("**Layout is not verified.** The Critic checks explainer facts and code safety, not visual layout; one explainer "
           "drew overlapping labels (Fig. 4)."))
add(bullet("**Scale of the study.** One short lesson with synthesized narration and three scripted profiles; no user study. "
           "The system ingests uploads and links (a 3.5-minute YouTube lesson on Newton’s laws was ingested end to end), "
           "but engagement and learning gains remain to be measured with learners."))
add(bullet("**LLM variance.** The object vocabulary changed between runs, once dropping the hazard entirely; this motivated "
           "the always-on hazard list and is a reminder that safety-relevant steps should not rest on a single LLM output."))

add(h1("Conclusion"))
add(body("LOOM shows that personalization can operate on the objects inside an instructional video rather than on the video "
         "as a whole, and that it can do so safely: every cut, mask, quiz and generated animation passes a bounded, auditable "
         "Critic loop before a viewer sees it, and agents interoperate through open A2A Agent Cards. Future work includes "
         "pixel-accurate SAM 3.1 masks on GPU hardware, denser sampling for hazards, a vision-based layout check for generated "
         "animations, independent judge models, and a classroom study measuring engagement past the two-minute attention "
         "cliff."))

add(h5("Acknowledgment"))
add(body("The authors thank Dr. J Sangeetha, Associate Professor, Department of Computer Science and Engineering, Ramaiah "
         "Institute of Technology, for supervising this project. Lesson footage is royalty-free material from Pexels."))

REFS = [
    "T. Sanal Kumar and R. Thandeeswaran, “An improved adaptive personalization model for instructional video-based e-learning environments,” J. Comput. Educ., 2024, doi: 10.1007/s40692-023-00310-x.",
    "G. Hardaker and L. Glenn, “Artificial intelligence for personalized learning: a systematic literature review,” Int. J. Inf. Learn. Technol., vol. 42, no. 1, pp. 1–14, 2025, doi: 10.1108/IJILT-07-2024-0160.",
    "X. Zhang, C. Zhang, J. Sun, J. Xiao, Y. Yang, and Y. Luo, “EduPlanner: LLM-based multiagent systems for customized and intelligent instructional design,” IEEE Trans. Learn. Technol., vol. 18, pp. 416–427, 2025, doi: 10.1109/TLT.2025.3561332.",
    "T. Wang et al., “LLM-powered multi-agent framework for goal-oriented learning in intelligent tutoring system,” 2025, arXiv:2501.15749.",
    "Y. Ayadi, “Automatic moderation of visual content: integration of emotions and semantic analysis through deep learning for the safety of young users,” J. Ambient Intell. Humaniz. Comput., vol. 16, pp. 817–830, 2025, doi: 10.1007/s12652-025-04979-z.",
    "M. Chuttur and A. Nazurally, “A multi-modal approach to detect inappropriate cartoon video contents using deep learning networks,” Multimed. Tools Appl., vol. 81, no. 12, pp. 16881–16900, 2022, doi: 10.1007/s11042-022-12709-2.",
    "K. Yousaf and T. Nawaz, “A deep learning-based approach for inappropriate content detection and classification of YouTube videos,” IEEE Access, vol. 10, pp. 16283–16298, 2022, doi: 10.1109/ACCESS.2022.3147519.",
    "A. Cattaneo, H. van der Meij, C. Aprea, F. Sauli, and C. Zahn, “A model for designing hypervideo-based instructional scenarios,” Interact. Learn. Environ., vol. 27, no. 4, pp. 508–529, 2019, doi: 10.1080/10494820.2018.1486860.",
    "C. Halkiopoulos and E. Gkintoni, “Leveraging AI in e-learning: personalized learning and adaptive assessment through cognitive neuropsychology—a systematic analysis,” Electronics, vol. 13, no. 18, art. 3762, 2024, doi: 10.3390/electronics13183762.",
    "M. Chakraborty et al., “PAL: Personal adaptive learner,” in Proc. AAAI Conf. Artif. Intell., 2026, arXiv:2604.13017.",
    "T. Baarslag, M. Kaisers, E. Gerding, C. Jonker, and J. Gratch, “Computers that negotiate on our behalf: major challenges for self-sufficient, self-directed, and interdependent negotiating agents,” in Autonomous Agents and Multiagent Systems, LNCS 10643, 2017, pp. 143–163, doi: 10.1007/978-3-319-71679-4_10.",
    "G. Madasamy Raja, M. Thaha, R. Latha, and A. Karthikeyan, “Texture classification using optimized local ternary patterns with nonlinear diffusion as pre-processing,” Multimed. Tools Appl., vol. 79, pp. 3831–3846, 2020, doi: 10.1007/s11042-019-7197-0.",
    "C. Chiou, “Assessing the impact of integrating augmented reality technology and animated multidimensional concept maps into multimedia learning materials for enhancing positive emotions and cognitive achievements,” Smart Learn. Environ., 2026, doi: 10.1186/s40561-026-00462-0.",
    "Y. Sun and F. Liu, “The impact of an AI digital teacher on human-AI collaborative learning in higher education,” Smart Learn. Environ., vol. 13, art. 30, 2026, doi: 10.1186/s40561-026-00454-0.",
    "A. Madaan et al., “Self-Refine: iterative refinement with self-feedback,” in Adv. Neural Inf. Process. Syst., 2023, arXiv:2303.17651.",
    "N. Carion et al., “SAM 3: segment anything with concepts,” 2025, arXiv:2511.16719.",
    "S. Liu et al., “Grounding DINO: marrying DINO with grounded pre-training for open-set object detection,” in Proc. ECCV, 2024, arXiv:2303.05499.",
    "A. Radford et al., “Learning transferable visual models from natural language supervision,” in Proc. ICML, 2021, arXiv:2103.00020.",
    "A. Radford et al., “Robust speech recognition via large-scale weak supervision,” in Proc. ICML, 2023, arXiv:2212.04356.",
    "Google, “Agent2Agent (A2A) protocol specification,” 2025. [Online]. Available: https://a2a-protocol.org",
    "The Manim Community Developers, “Manim – mathematical animation framework,” v0.21, 2026. [Online]. Available: https://www.manim.community",
]
add(h5("References"))
for r in REFS:
    add(para("references", r, '<w:ind w:start="17.70pt" w:hanging="17.70pt"/>'))

# ---------------------------------------------------------------- assemble inside the template


def build():
    work = pathlib.Path(tempfile.mkdtemp(prefix="loom_ieee_"))
    with zipfile.ZipFile(TEMPLATE) as z:
        z.extractall(work)
    doc_path = work / "word" / "document.xml"
    x = doc_path.read_text(encoding="utf-8")
    head, rest = x.split("<w:body>", 1)
    paras = re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", rest.split("</w:body>")[0], re.S)

    title_ppr = re.search(r"<w:pPr>.*?</w:pPr>", paras[0], re.S).group(0)
    title = f'<w:p>{title_ppr}<w:r><w:rPr><w:kern w:val="48"/></w:rPr><w:t xml:space="preserve">{escape(TITLE)}</w:t></w:r></w:p>'
    title_section = title + paras[2] + paras[3]          # spacer + the title section break (first-page footer)

    abstract = ('<w:p><w:pPr><w:pStyle w:val="Abstract"/></w:pPr><w:r><w:rPr><w:i/><w:iCs/></w:rPr><w:t>Abstract</w:t></w:r>'
                f'<w:r><w:t>—</w:t></w:r>{runs(ABSTRACT)}</w:p>')
    keywords = f'<w:p><w:pPr><w:pStyle w:val="Keywords"/></w:pPr><w:r><w:t>Keywords—</w:t></w:r>{runs(KEYWORDS)}</w:p>'

    new_body = ("<w:body>" + title_section + authors_xml + abstract + keywords + "".join(content)
                + sect(2, "18pt") + "</w:body>")
    doc_path.write_text(head + new_body + x[x.index("</w:body>") + len("</w:body>"):], encoding="utf-8")

    # images: media files, relationships, content type
    media = work / "word" / "media"
    media.mkdir(exist_ok=True)
    rels_path = work / "word" / "_rels" / "document.xml.rels"
    rels = rels_path.read_text(encoding="utf-8")
    for rid, src, name in IMAGES:
        shutil.copy(src, media / name)
        rels = rels.replace("</Relationships>", f'<Relationship Id="{rid}" Type="{IMG_REL}" Target="media/{name}"/></Relationships>')
    rels_path.write_text(rels, encoding="utf-8")
    ct_path = work / "[Content_Types].xml"
    ct = ct_path.read_text(encoding="utf-8")
    if 'Extension="png"' not in ct:
        ct = ct.replace("<Default ", '<Default Extension="png" ContentType="image/png"/><Default ', 1)
    ct_path.write_text(ct, encoding="utf-8")

    # remove the template's placeholder copyright line from the first-page footer
    footer = work / "word" / "footer1.xml"
    footer.write_text(footer.read_text(encoding="utf-8").replace("XXX-X-XXXX-XXXX-X/XX/$XX.00 ©20XX IEEE", ""),
                      encoding="utf-8")

    core = work / "docProps" / "core.xml"
    if core.exists():
        c = core.read_text(encoding="utf-8")
        c = re.sub(r"<dc:title>.*?</dc:title>|<dc:title/>", f"<dc:title>{escape(TITLE)}</dc:title>", c)
        core.write_text(c, encoding="utf-8")

    if OUT.exists():
        OUT.unlink()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(work / "[Content_Types].xml", "[Content_Types].xml")
        for p in sorted(work.rglob("*")):
            if p.is_file() and p.name != "[Content_Types].xml":
                z.write(p, p.relative_to(work).as_posix())
    shutil.rmtree(work)
    print("wrote", OUT)


if __name__ == "__main__":
    build()
