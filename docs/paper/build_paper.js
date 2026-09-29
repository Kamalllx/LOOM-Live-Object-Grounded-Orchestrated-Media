// Builds docs/paper/LOOM_IEEE_Paper.docx (IEEE conference format, two columns).
// Every reported number is read from data/eval/*.json so the paper cannot drift from the measurements.
//   node docs/paper/build_paper.js
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell, AlignmentType, WidthType,
  BorderStyle, SectionType, ShadingType, LevelFormat, HeadingLevel, TabStopType,
} = require("docx");

const ROOT = path.resolve(__dirname, "..", "..");
const EVAL = path.join(ROOT, "data", "eval");
const FIG = path.join(ROOT, "docs", "figures");
const load = (n) => { try { return JSON.parse(fs.readFileSync(path.join(EVAL, n + ".json"), "utf8")); } catch { return null; } };
const perception = load("perception");
const critic = load("critic");
const animator = load("animator");
const sessions = load("sessions");
const sessionsBefore = load("sessions_before_time_padding");
const graph = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "graphs", "vid_demo_neutralization.json"), "utf8"));
const gt = JSON.parse(fs.readFileSync(path.join(EVAL, "groundtruth_vid_demo_neutralization.json"), "utf8"));

// Animator production log: every explainer rendered while running the system (not only the eval).
const prodRuns = fs.existsSync(path.join(ROOT, "data", "cache", "animator_stats.jsonl"))
  ? fs.readFileSync(path.join(ROOT, "data", "cache", "animator_stats.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l))
  : [];

const f2 = (x) => (x == null ? "n/a" : Number(x).toFixed(2));
const f3 = (x) => (x == null ? "n/a" : Number(x).toFixed(3));
const pct = (x) => (x == null ? "n/a" : `${(100 * x).toFixed(1)}%`);
const run = (learner, which = "first", src = sessions) => src?.runs.find((r) => r.learner === learner && r.run === which);

// ---------------------------------------------------------------- typography
const FONT = "Times New Roman";
const BODY = 20;      // 10 pt
const SMALL = 16;     // 8 pt
const t = (text, o = {}) => new TextRun({ text, font: FONT, size: o.size || BODY, bold: o.bold, italics: o.italics,
  smallCaps: o.smallCaps, superScript: o.sup, subScript: o.sub, color: o.color });

function P(runs, o = {}) {
  const children = (Array.isArray(runs) ? runs : [runs]).map((r) => (typeof r === "string" ? t(r, o) : r));
  return new Paragraph({ children, alignment: o.align ?? AlignmentType.JUSTIFIED,
    indent: o.noIndent ? undefined : { firstLine: 202 }, spacing: { after: o.after ?? 0, before: o.before ?? 0, line: 228 },
    keepNext: o.keepNext });
}
const para = (text) => P(rich(text));

// **bold**, _italic_, and [n] citations stay plain text; lightweight inline markup for readability.
function rich(s) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|_[^_]+_)/g;
  let last = 0, m;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(t(s.slice(last, m.index)));
    const tok = m[0];
    out.push(tok.startsWith("**") ? t(tok.slice(2, -2), { bold: true }) : t(tok.slice(1, -1), { italics: true }));
    last = m.index + tok.length;
  }
  if (last < s.length) out.push(t(s.slice(last)));
  return out;
}

let secNo = 0;
const ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"];
const H1 = (text) => new Paragraph({ children: [t(`${ROMAN[secNo++]}. ${text}`, { smallCaps: true, color: "000000" })],
  alignment: AlignmentType.CENTER, spacing: { before: 160, after: 80 }, keepNext: true, heading: HeadingLevel.HEADING_1 });
let subNo = 0;
const H2 = (text) => new Paragraph({ children: [t(`${String.fromCharCode(65 + subNo++)}. ${text}`, { italics: true, color: "000000" })],
  spacing: { before: 80, after: 40 }, keepNext: true, heading: HeadingLevel.HEADING_2 });
const newSection = (text) => { subNo = 0; return H1(text); };

const bullet = (text) => new Paragraph({ children: rich(text), numbering: { reference: "bullets", level: 0 },
  alignment: AlignmentType.JUSTIFIED, spacing: { line: 228 } });
const numbered = (text) => new Paragraph({ children: rich(text), numbering: { reference: "steps", level: 0 },
  alignment: AlignmentType.LEFT, spacing: { line: 228 } });
const eq = (text, no) => new Paragraph({ children: [t(text, { italics: true, size: 18 }), t(`\t(${no})`, { size: 18 })],
  tabStops: [{ type: TabStopType.RIGHT, position: 5040 }], alignment: AlignmentType.CENTER, spacing: { before: 60, after: 60 } });

// ---------------------------------------------------------------- tables & figures
const COL_W = 5040;   // one column, DXA
const FULL_W = 10440;
const border = { style: BorderStyle.SINGLE, size: 4, color: "000000" };
const none = { style: BorderStyle.NONE, size: 0, color: "FFFFFF" };

let tableNo = 0;
function table(caption, header, rows, widths) {
  const total = widths.reduce((a, b) => a + b, 0);
  const cell = (text, head, i, isLast) => new TableCell({
    width: { size: widths[i], type: WidthType.DXA },
    margins: { top: 30, bottom: 30, left: 60, right: 60 },
    borders: { top: head ? border : none, bottom: head || isLast ? border : none, left: none, right: none },
    shading: head ? { type: ShadingType.CLEAR, color: "auto", fill: "F2F2F2" } : undefined,
    children: [new Paragraph({ children: [t(String(text), { size: SMALL, bold: head })],
      alignment: i === 0 ? AlignmentType.LEFT : AlignmentType.CENTER })],
  });
  tableNo++;
  return [
    new Paragraph({ children: [t(`TABLE ${ROMAN[tableNo - 1]}`, { size: SMALL, smallCaps: true })], alignment: AlignmentType.CENTER,
      spacing: { before: 120 }, keepNext: true }),
    new Paragraph({ children: [t(caption, { size: SMALL, smallCaps: true })], alignment: AlignmentType.CENTER,
      spacing: { after: 60 }, keepNext: true }),
    new Table({ width: { size: total, type: WidthType.DXA }, columnWidths: widths, alignment: AlignmentType.CENTER,
      rows: [new TableRow({ tableHeader: true, children: header.map((h, i) => cell(h, true, i, false)) }),
        ...rows.map((r, ri) => new TableRow({ children: r.map((c, i) => cell(c, false, i, ri === rows.length - 1)) }))] }),
    new Paragraph({ children: [], spacing: { after: 80 } }),
  ];
}

let figNo = 0;
function figure(file, caption, widthPx) {
  const buf = fs.readFileSync(path.join(FIG, file));
  const w = buf.readUInt32BE(16), h = buf.readUInt32BE(20);   // PNG IHDR
  figNo++;
  return [
    new Paragraph({ children: [new ImageRun({ type: "png", data: buf,
      transformation: { width: widthPx, height: Math.round((widthPx * h) / w) } })], alignment: AlignmentType.CENTER,
      spacing: { before: 100 }, keepNext: true }),
    new Paragraph({ children: [t(`Fig. ${figNo}. `, { size: SMALL }), t(caption, { size: SMALL })],
      alignment: AlignmentType.JUSTIFIED, spacing: { after: 120 } }),
  ];
}

// ---------------------------------------------------------------- content
const dur = graph.duration_seconds;
const meta = graph.perception_meta;
const fam = run("learner_family"), famBefore = run("learner_family", "first", sessionsBefore);
const alex = run("learner_alex"), priya = run("learner_priya");
const ab = perception?.grounding?.ablation || {};
const abRow = (name, label) => {
  const a = ab[name];
  return a ? [label, a.tracks, a.hazard_tracks, f2(a.precision), f2(a.recall), `${a.false_block_s}s`] : [label, "n/a", "n/a", "n/a", "n/a", "n/a"];
};
const prodOk = prodRuns.filter((r) => r.ok);
const prodFirst = prodOk.filter((r) => r.attempts === 1).length;
const median = (xs) => { const s = [...xs].sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : null; };

const title = [
  new Paragraph({ children: [t("LOOM: Live, Object-Grounded, Orchestrated Media — A Verified Multi-Agent System for Object-Level Personalization of Instructional Video", { size: 44 })],
    alignment: AlignmentType.CENTER, spacing: { after: 200 } }),
  new Paragraph({ children: [
    t("Manya Ravishankar", { size: 22 }), t("   ·   ", { size: 22 }), t("Rana Adiba", { size: 22 }), t("   ·   ", { size: 22 }),
    t("Kamal Karteek U", { size: 22 }), t("   ·   ", { size: 22 }), t("Jeevika R", { size: 22 })],
    alignment: AlignmentType.CENTER }),
  new Paragraph({ children: [t("1MS23CS227 · 1MS23CS228 · 1MS23CS229 · 1MS23CS230", { size: 18 })], alignment: AlignmentType.CENTER }),
  new Paragraph({ children: [t("Department of Computer Science and Engineering, Ramaiah Institute of Technology, Bengaluru, India", { size: 18, italics: true })],
    alignment: AlignmentType.CENTER }),
  new Paragraph({ children: [t("Supervised by Dr. J Sangeetha, Associate Professor, Department of CSE", { size: 18, italics: true })],
    alignment: AlignmentType.CENTER, spacing: { after: 240 } }),
];

const abstract = [
  P([t("Abstract—", { bold: true, italics: true, size: 18 }), t(
    `Every platform that plays instructional video can pause, speed up, reorder, or block a video, but none can act on a single object inside a frame. ` +
    `LOOM keeps one set of source material — footage, transcript, on-screen text and individually tracked objects — and weaves a different, verified cut for each viewer. ` +
    `A perception pipeline fuses Whisper speech recognition, OCR and text-prompted open-vocabulary grounding into a spatio-temporal concept graph; ` +
    `a mesh of specialist agents that discover and task each other through Agent2Agent (A2A) Agent Cards builds a personalized candidate cut; ` +
    `and a bounded Perceive–Plan–Act–Verify loop, gated by a Critic agent, checks every cut before delivery. ` +
    `A Guardian agent masks only the unsafe object for a given viewer, and an Animator agent writes, statically checks, renders and caches Manim explainer animations on demand. ` +
    `On a narrated chemistry lesson with ground truth, the Critic caught ${critic ? `${critic.faults - Math.round(critic.faults * (1 - critic.detection_rate))} of ${critic.faults}` : "all"} injected faults with ` +
    `${critic ? critic.false_rejections : 0} false rejections, per-object redaction reached a temporal precision of ${f2(fam?.redaction_vs_truth?.precision)} and recall of ${f2(fam?.redaction_vs_truth?.recall)} with no safe content blocked, ` +
    `and three viewer profiles received cuts of ${pct(alex?.source_ratio)}, ${pct(priya?.source_ratio)} (+${priya?.explainers ?? "n/a"} generated explainers) and ${pct(fam?.source_ratio)} (+${fam?.masks ?? "n/a"} object mask) of the same source.`,
    { size: 18, bold: true })], { noIndent: true, after: 80 }),
  P([t("Index Terms—", { bold: true, italics: true, size: 18 }), t(
    "multi-agent systems, Agent2Agent protocol, open-vocabulary grounding, personalized video learning, content redaction, verification loops, generative animation.",
    { size: 18, bold: true })], { noIndent: true, after: 120 }),
];

const body = [
  ...abstract,
  newSection("Introduction"),
  para("Picture one ten-minute instructional video watched by three people. An expert who already knows the basics leaves before the one new idea at minute eight; a beginner falls behind by minute two because the video assumes background they lack; and a parent watching with a child closes the whole video because of one unwanted moment. All three failures have one cause: a video file is a single fixed sequence of pixels, and every tool built on top of it — hosting, quiz overlays, dubbing, analytics — operates on the asset as a whole."),
  para("Adaptive-video research personalizes at the level of whole clips or chapters [1], [2]; multi-agent tutors personalize the learning path around a video but never the video itself [3], [4]; and moderation systems return one label per video, forcing a block-or-allow decision [5]–[7]. None of them can reach inside the frame. LOOM (Live, Object-grounded, Orchestrated Media) moves the unit of personalization from “which video plays” to “which object, in which frame, for this viewer”, and does so without shipping anything unchecked."),
  para("This paper makes five contributions:"),
  bullet("**Object-grounded perception with safety-first vocabulary.** The transcript and on-screen text decide which objects to ground, while a fixed hazard vocabulary is always searched; hazard detections must additionally beat visual look-alikes under CLIP verification (Section IV-A)."),
  bullet("**An open agent mesh.** Curator, Pedagogy, Personalizer and Assessment agents, plus any third-party agent, are discovered and tasked only through A2A Agent Cards and JSON-RPC, over versioned JSON contracts (Section IV-B)."),
  bullet("**A bounded, Critic-gated verification loop** with structured issues, local repair, mesh revision, a fixed budget and a fallback to the last verified cut (Section IV-C)."),
  bullet("**Per-object, per-viewer redaction** and **agent-authored Manim explainers** that pass an AST safety gate, a repair loop and a fact-check before any viewer sees them."),
  bullet("**An evaluation with ground truth and fault injection**, including the failure modes we found while building the system and how each was fixed (Sections V–VII)."),

  newSection("Related Work"),
  H2("Adaptive and interactive instructional video"),
  para("Hypervideo models add navigation and interaction around a fixed video [8]. Sanal Kumar and Thandeeswaran deliver pre-segmented instructional videos according to a learner’s style [1]; reviews of AI-based personalized learning [2], [9] describe the same granularity: content is selected, sequenced or paced, but never altered inside the frame. PAL turns a lecture video into an interactive session whose question difficulty adapts through reinforcement learning [10], yet it also leaves the video itself untouched."),
  H2("Multi-agent AI in education"),
  para("EduPlanner uses evaluator, optimizer and analyst agents that refine lesson plans adversarially [3]; GenMentor coordinates agents for goal-oriented tutoring [4]. Both operate on text and use a fixed, in-house agent set. Baarslag et al. identify the lack of standard interoperability and of a trust gate before an agent’s decision takes effect as open challenges for autonomous agents [11]. LOOM uses the A2A protocol for the first and a Critic loop for the second."),
  H2("Content safety for young viewers"),
  para("Ayadi combines visual semantics with emotional context to classify content for young users [5]; Chuttur and Nazurally [6] and Yousaf and Nawaz [7] classify whole cartoon or YouTube videos. Classical texture classifiers such as optimized local ternary patterns likewise label whole images from a closed set [12]. Each of these outputs one decision per video or image; LOOM instead masks one object for one viewer and keeps the rest."),
  H2("Generated explanations and self-refinement"),
  para("Animated concept maps improve cognitive achievement over static material, and structure rather than affect mediated the gain [13]; an AI digital teacher improved performance and achievement emotions in a randomized trial [14]. Both use material authored in advance. Self-Refine shows that LLM outputs improve through iterative self-feedback [15]; LOOM applies a bounded version of this idea to personalized media, with an independent Critic and hard budget."),
  H2("Perception foundations"),
  para("SAM 3 segments and tracks every instance of a concept named by a short phrase [16]. Grounding DINO offers open-set, text-prompted detection [17], CLIP aligns images with text [18], and Whisper provides robust speech recognition [19]."),

  newSection("System Architecture"),
  para(`LOOM is four services joined by four JSON contracts, each a JSON Schema validated by its producer before hand-off (Fig. 1). **Contract A** (concept graph) carries objects with per-instance time ranges, normalized boxes and per-second tracks, the transcript, on-screen text and concept nodes that link them. **Contract A2** (learner profile) holds a mastery value per concept, pace and a family safety profile. **Contract B** (candidate cut) lists threads with actions, explainer and redaction requests, a quiz and an agent trace. **Contract C** (verified cut) adds masks, explainer clips, Critic scores and the loop trace. **Contract D** (session log) records what the viewer did and is folded back into A2.`),
  para("Every agent publishes an Agent2Agent (A2A) [20] Agent Card at /.well-known/agent.json (name, version, skills with input/output) and is tasked only with JSON-RPC message/send, with contract JSON carried as a data part. The orchestrator keeps a registry of cards and selects agents by skill id, so a third-party agent joins by URL. For the evaluation, a separate-process “school policy” agent was registered at run time and its redaction requests were merged into sessions without code changes to LOOM."),
];

const afterArch = [
  newSection("Methods"),
  H2("Perception: from pixels to a concept graph"),
  para(`Video is normalized with ffmpeg; speech is transcribed with Whisper large-v3-turbo [19] and on-screen text is read by Tesseract once per second, merging readings that occupy the same screen region so that a caption flickering over moving footage becomes one item. An LLM reads the transcript and on-screen text and proposes up to six visible, solid lesson objects; to these we always append a fixed hazard vocabulary (broken glass, knife, open flame), because redaction must not depend on a narrator happening to mention a hazard.`),
  para(`SAM 3.1 requires a data-centre GPU, so on commodity hardware the grounding step uses the same concept-prompt interface with Grounding DINO [17] at one sample per second, greedy IoU tracking, and a verification step: each track is cropped from up to three frames and scored by CLIP [18] against all prompts plus generic distractors. Lesson objects must rank in the top two and beat every distractor; **hazard tracks must rank first against additional look-alikes** (intact glassware, a stirring rod, a red liquid) and persist for two samples. An LLM then fuses sentences, text and objects into concept nodes with prerequisites; a grounding check keeps only objects visible while the concept is on screen.`),
  H2("Agent mesh: building the candidate cut"),
  para("The **Curator** partitions the timeline at sentence boundaries, so no thread starts or ends mid-sentence, and an LLM labels each thread’s role (intro, setup, core, safety, summary). The **Pedagogy** agent applies an auditable policy to the learner’s mastery m of the thread’s concepts, shifted by pace:"),
  eq("a(m) = skip | condense | keep | expand  for  m ≥ 0.80 | 0.60 | 0.35 | else", 1),
  para("with role rules on top: core and safety content is condensed rather than skipped, a concept whose prerequisite is not mastered is never skipped, and explainers are spent only on core and setup threads. The **Personalizer** trims condensed threads to about half, ending on a sentence boundary and never before an on-screen formula has been shown for 3 s, anchors an automatic explainer after each expanded thread, and adds a tap-to-learn request for every concept with a tracked object. The **Assessment** agent writes multiple-choice checks grounded in transcript excerpts, prioritising the least-mastered concepts, and updates mastery from the session log (each watched explainer adds 0.05(1\u2212m)):"),
  eq("m ← m + 0.35(1−m)  if correct,   m ← 0.75 m  if wrong", 2),
  H2("Verification: Guardian, Animator, Critic and the bounded loop"),
  para("**Guardian.** Each tracked object is tagged from a fixed taxonomy with a severity by a dedicated safety model (gpt-oss-safeguard-20b), judged in lesson context and cached per video. For a viewer, an object is redacted if any tag is in the profile’s blocked tags, or if it exceeds the level’s severity threshold (standard 0.5 and child-unsafe, strict 0.2). The mesh’s requests are hints only: the Guardian reviews every visible object, so a hazard the mesh missed is still caught, and third-party requests are honoured because over-masking is the safe side. Masks follow the object’s per-second track with 4% spatial padding and are padded in time by one sampling interval, since an object seen at sample t may be on screen anywhere in (t−1 s, t+1 s)."),
  para("**Animator.** For a concept and learner level, an LLM returns a spoken storyboard and Manim Community [21] code. Before execution, the code passes an AST allow-list (imports limited to manim, math and numpy; no open, exec, eval, dunder access, external media or LaTeX when unavailable). It is rendered in a subprocess with a timeout; a compile or render error is returned to the LLM for up to two repairs. The storyboard is narrated with text-to-speech and the clip is cached by concept and level, so later learners receive it instantly."),
  para("**Critic.** Three scores in [0, 1] are computed from auditable checks. Safety is the fraction of flagged-object screen time inside the cut that is covered by a mask, with H the set of 0.1 s instants inside the cut where a flagged object is visible and M the instants covered by one of its masks:"),
  eq("S_safety = |H ∩ M| / |H|", 3),
  para("Coherence starts at 1 and is penalized for overlapping or unordered threads (0.25), a thread ending mid-sentence (0.15), a missing prerequisite for a learner below 0.35 mastery (0.10) and an unavailable explainer (0.10). Factuality is the share of generated claims — every quiz question with its marked answer and every storyboard sentence — that an LLM judge finds supported by the lesson transcript and on-screen text. A cut is approved only if S_safety = 1, coherence and factuality are at least 0.8, **and no individual check raised an issue**: averages hide individual failures, so one unsupported sentence in one explainer blocks delivery. An explainer clip that has passed once is recorded and not re-judged, because it is immutable."),
  para("**Bounded loop.** Each pass runs four phases:"),
  numbered("**Perceive**: the Guardian builds masks for the cut; the Animator renders the cut’s automatic explainers in parallel (from cache when possible)."),
  numbered("**Plan**: the Critic scores the cut and emits structured issues {code, message, target}."),
  numbered("**Verify**: if approved, deliver and record the cut as the last verified cut for this video and learner."),
  numbered("**Act**: otherwise fix locally what verification owns — re-render an unfaithful explainer with the Critic’s reasons (once, then drop it) or force a mask on an unmasked hazard — and send the remaining issues to the orchestrator’s revise_cut skill over A2A for the next candidate."),
  para("The budget is three passes. When it is spent, the viewer receives the last verified cut for this video and learner or, if none exists, a conservative baseline: the full lesson with every safety-tagged object masked under the strict policy and no generated content. Tap-to-learn explainers follow the same rule with a budget of two."),
  H2("Delivery and memory"),
  para("A Next.js player plays only the verified threads, pauses at each automatic explainer, and composites masks client-side as blurred regions that follow interpolated tracks, so the base video is never re-encoded per viewer. Tappable regions are drawn for tracked objects that belong to a concept and never on top of a mask. Loop progress streams to the player over server-sent events; at the end, the quiz result is posted as a session log and the updated mastery graph seeds the next session."),

  newSection("Experimental Setup"),
  para(`**Lesson.** We assembled a ${dur.toFixed(1)} s narrated lesson on acid–base neutralization from five royalty-free Pexels clips, with narration synthesized by text-to-speech and three burned-in text cards (the reaction NaOH + HCl → NaCl + H₂O, “pH 7 = neutral”, a summary). One segment shows a glass jar shattering on a table. Because we built the lesson, its ground truth is exact: the narration script, every card’s text and time range, and the hazard window (shards visible from ${(gt.hazards[0].start + 0.8).toFixed(2)} s to ${gt.hazards[0].end.toFixed(2)} s).`),
  para(`**Viewers.** Alex (expert, prior mastery 0.85, condensed pace, no redaction), Priya (beginner, prior 0.2, detailed pace, no redaction) and Parent + child (prior 0.4, standard redaction, blocked tags sharp_object and injury_risk).`),
  para(`**Implementation.** Python 3.11 services behind FastAPI; Next.js 15 player; LLMs served by Groq (gpt-oss-120b for agents and the Critic, gpt-oss-safeguard-20b for the Guardian, Qwen3 as automatic fallback); Whisper large-v3-turbo; Grounding DINO-tiny and CLIP ViT-B/32 on an Apple-silicon laptop (MPS); Manim Community 0.21; loop budget 3. The code, contracts, fixtures and evaluation scripts are in the project repository; every number below is produced by scripts/evaluate.py.`),

  newSection("Results"),
  H2("Perception"),
  para(perception
    ? `Speech recognition reached a word error rate of ${pct(perception.asr.wer)} over ${perception.asr.ref_words} reference words (on synthesized narration, which is easier than classroom speech). After fusion, which corrected raw Tesseract confusions such as “HCI” → “HCl” and “H20” → “H₂O”, ${pct(perception.ocr["recall_at_0.8"])} of the burned-in text cards were recovered at ≥ 0.8 character similarity with a mean temporal IoU of ${f2(perception.ocr.mean_temporal_iou)}. Fusion produced ${graph.concept_nodes.length} concept nodes with a prerequisite chain. Table I isolates the effect of verification on hazard grounding.`
    : `Fusion produced ${graph.concept_nodes.length} concept nodes with a prerequisite chain and corrected OCR confusions such as “HCI” → “HCl”. Table I isolates the effect of verification on hazard grounding.`),
  ...table("Hazard grounding against ground truth (time-level)", ["Configuration", "Tracks", "Hazard tracks", "Prec.", "Rec.", "Wrongly flagged"],
    [abRow("detector_only", "Detector + tracking"), abRow("+clip_verify_generic", "+ CLIP, generic negatives"),
      abRow("+clip_verify_hazard_lookalikes (LOOM)", "+ CLIP, hazard look-alikes")], [1700, 620, 760, 600, 600, 760]),
  para(`Raw open-vocabulary detection fired on intact beakers, a stirring rod and a red liquid when prompted with hazard phrases, flagging ${ab.detector_only?.false_block_s ?? "n/a"} s of safe footage. Generic CLIP distractors reduced this to ${ab["+clip_verify_generic"]?.false_block_s ?? "n/a"} s; requiring hazards to beat visual look-alikes removed every false hazard while keeping the real one. The price is recall (${f2(ab.detector_only?.recall)} → ${f2(ab["+clip_verify_hazard_lookalikes (LOOM)"]?.recall)}), which the Guardian’s temporal padding recovers (Section VI-D). The detector-only row is recomputed from the cached detections with the pipeline’s tracking code; the two CLIP rows were measured on the same cached detections during development, and the last row equals the concept graph used in all other experiments.`),
  H2("The Critic catches injected faults"),
  para(critic
    ? `We planted ${critic.faults} faults in real candidate cuts across six families and presented ${critic.controls} correct items as controls (Table II). The Critic flagged and blocked every fault (detection ${pct(critic.detection_rate)}) and rejected ${critic.false_rejections} of ${critic.controls} controls.`
    : "Fault-injection results were not available when this document was generated."),
  ...table("Fault injection: flagged and blocked / injected", ["Fault family", "Check", "Caught"],
    [["F1 hazard mask removed or cut short", "safety coverage", critic?.by_family.F1 ?? "n/a"],
      ["F2 wrong answer marked in quiz", "LLM judge", critic?.by_family.F2 ?? "n/a"],
      ["F3 false sentence in explainer", "LLM judge", critic?.by_family.F3 ?? "n/a"],
      ["F4 thread ends mid-sentence", "coherence", critic?.by_family.F4 ?? "n/a"],
      ["F5 prerequisite dropped (beginner)", "coherence", critic?.by_family.F5 ?? "n/a"],
      ["F6 overlapping threads", "coherence", critic?.by_family.F6 ?? "n/a"],
      ["Controls wrongly rejected", "all", critic ? `${critic.false_rejections}/${critic.controls}` : "n/a"]], [2700, 1300, 1040]),
  para("The first version of the Critic approved a cut whose factuality averaged 0.93 although one explainer was unsupported, and approved a mid-sentence cut because its penalty left coherence at 0.85. Both were fixed by the rule that any individual issue blocks approval; F3 and F4 in Table II are measured after that change."),
  H2("The loop repairs what it finds"),
  para("In Priya’s first session the Animator’s explainer for the indicator concept claimed that the indicator “is red in acidic solution and turns green when the pH reaches 7”. The lesson never states colours, so the Critic rejected pass 1 (factuality 0.889) with that sentence as feedback. In the Act phase the Animator re-rendered the explainer with the feedback, and pass 2 was approved with factuality 1.00 — the viewer never saw the invented detail."),
  H2("Per-object redaction"),
  para(fam?.redaction_vs_truth
    ? `For the Parent + child viewer the Guardian masked only the shards; nothing else in the lesson was blocked (Fig. 2). Against the ground-truth hazard window, time-level precision was ${f2(fam.redaction_vs_truth.precision)} and recall ${f2(fam.redaction_vs_truth.recall)} (${fam.redaction_vs_truth.missed_s} s unmasked, ${fam.redaction_vs_truth.false_block_s} s of safe content blocked). Without temporal padding recall was ${f2(famBefore?.redaction_vs_truth?.recall)} (${famBefore?.redaction_vs_truth?.missed_s} s unmasked): one-second sampling and the two-sample persistence rule start the mask late. Note that the Critic scored safety 1.00 in both cases — it can only verify coverage of hazards that perception detected.`
    : "Redaction results were not available when this document was generated."),
];

const afterFigs = [
  H2("Three viewers, three weaves"),
  para(`Fig. 3 shows the verified cuts. Alex received ${alex?.source_kept_s ?? "n/a"} s (${pct(alex?.source_ratio)}) of condensed threads: the intro was skipped, core and safety ideas kept as refreshers. Priya received the full lesson with ${priya?.explainers ?? "n/a"} generated Manim explainers (${priya?.explainer_s ?? "n/a"} s) after the core threads. Parent + child received the full lesson with ${fam?.masks ?? "n/a"} object mask. All cuts were approved; with warm caches, a verified cut was ready ${Math.min(...[alex, priya, fam].map((r) => r?.time_to_first_frame_s ?? 99))}–${Math.max(...[alex, priya, fam].map((r) => r?.time_to_first_frame_s ?? 0))} s after pressing play; the cost of generating explainers fresh is reported below.`),
  ...table("Personalized cuts of the same 74.6 s source", ["Viewer", "Source kept", "Explainers", "Masks", "Quiz", "Passes"],
    [["Alex (expert)", pct(alex?.source_ratio), alex?.explainers, alex?.masks, alex?.quiz, alex?.pass_count],
      ["Priya (beginner)", pct(priya?.source_ratio), priya?.explainers, priya?.masks, priya?.quiz, priya?.pass_count],
      ["Parent + child", pct(fam?.source_ratio), fam?.explainers, fam?.masks, fam?.quiz, fam?.pass_count]].map((r) => r.map((x) => x ?? "n/a")),
    [1400, 860, 980, 620, 540, 640]),
  H2("Animator"),
  para(animator
    ? `Generating ${animator.explainers} fresh explainers (six concepts at two levels), ${pct(animator.render_success_rate)} rendered successfully, ${pct(animator.first_attempt_compile_rate)} on the first attempt (mean ${animator.mean_attempts} attempts), with a median of ${animator.median_render_s} s from request to narrated clip; the AST gate was never triggered by generated code and rejected all five unsafe patterns in unit tests. Only ${pct(animator.critic_pass_rate_first_draft)} of first drafts passed the Critic unchanged. Of the ${animator.runs.filter((r) => !r.critic_pass).length} rejected drafts, one invented a fact the lesson never states (indicator colours), two overstated it (“harmless” products; “always … immediately”) and two described scene details the source does not support. Code that compiles is therefore not the bottleneck; faithfulness is, and without the Critic ${animator.runs.filter((r) => !r.critic_pass).length} of ${animator.explainers} explainers would have reached viewers unchecked. Expert-level drafts, which add more detail, were rejected more often than beginner drafts (${animator.runs.filter((r) => r.level === "expert" && !r.critic_pass).length} vs ${animator.runs.filter((r) => r.level === "beginner" && !r.critic_pass).length} of ${animator.explainers / 2}).`
    : `Across the ${prodRuns.length} explainers generated while running the system, ${prodOk.length} rendered successfully, ${prodFirst} of them on the first attempt, with a median of ${median(prodOk.map((r) => r.render_s)) ?? "n/a"} s from request to narrated clip (LLM code generation, rendering and narration). Later requests for the same concept and level are served from cache in milliseconds. The AST gate rejected all five unsafe patterns in our unit tests (file access, os/subprocess import, dunder access, LaTeX without a TeX installation).`),

  newSection("Discussion and Limitations"),
  bullet("**SAM 3.1 was not run.** It needs a data-centre GPU; we used Grounding DINO with tracking and CLIP verification behind the same concept-prompt interface, so the stated object-level design can be exercised on a laptop. Masks are boxes, not pixel-accurate segments, and a few stray shards far from the main pile remained visible."),
  bullet("**Verification is bounded by perception.** The Critic can prove that detected hazards are covered, not that every hazard was detected; the 1.3 s of unmasked shards is invisible to it. Temporal padding and denser sampling on hazards reduce, but do not remove, this gap."),
  bullet("**Same-family judge.** Explainers and the factuality judge both use LLMs from one provider; self-preference bias is possible. The Critic’s safety and coherence checks are deterministic for this reason, and the judge is grounded only in the lesson’s own transcript."),
  bullet("**Layout is not verified.** The Critic checks explainer facts and code safety, not visual layout; one explainer drew overlapping labels (Fig. 4)."),
  bullet("**Scale of the study.** One short, synthesized-narration lesson and three scripted profiles; no user study. The system ingests uploads and links, but engagement and learning gains remain to be measured with learners."),
  bullet("**LLM variance.** The object vocabulary changed between runs, once dropping the hazard entirely; this motivated the always-on hazard list and is a reminder that safety-relevant steps should not rest on a single LLM output."),

  newSection("Conclusion"),
  para("LOOM shows that personalization can operate on the objects inside an instructional video rather than on the video as a whole, and that it can do so safely: every cut, mask, quiz and generated animation passes a bounded, auditable Critic loop before a viewer sees it, and agents interoperate through open A2A Agent Cards. Future work includes pixel-accurate SAM 3.1 masks on GPU hardware, denser sampling for hazards, a vision-based layout check for generated animations, independent judge models, and a classroom study measuring engagement past the two-minute attention cliff."),
];

const refs = [
  "T. Sanal Kumar and R. Thandeeswaran, “An improved adaptive personalization model for instructional video-based e-learning environments,” J. Comput. Educ., 2024, doi: 10.1007/s40692-023-00310-x.",
  "G. Hardaker and L. Glenn, “Artificial intelligence for personalized learning: a systematic literature review,” Int. J. Inf. Learn. Technol., vol. 42, no. 1, pp. 1–14, 2025, doi: 10.1108/IJILT-07-2024-0160.",
  "X. Zhang, C. Zhang, J. Sun, J. Xiao, Y. Yang, and Y. Luo, “EduPlanner: LLM-based multiagent systems for customized and intelligent instructional design,” IEEE Trans. Learn. Technol., vol. 18, pp. 416–427, 2025, doi: 10.1109/TLT.2025.3561332.",
  "T. Wang et al., “LLM-powered multi-agent framework for goal-oriented learning in intelligent tutoring system,” arXiv:2501.15749, 2025.",
  "Y. Ayadi, “Automatic moderation of visual content: integration of emotions and semantic analysis through deep learning for the safety of young users,” J. Ambient Intell. Humaniz. Comput., vol. 16, pp. 817–830, 2025, doi: 10.1007/s12652-025-04979-z.",
  "M. Chuttur and A. Nazurally, “A multi-modal approach to detect inappropriate cartoon video contents using deep learning networks,” Multimed. Tools Appl., vol. 81, no. 12, pp. 16881–16900, 2022, doi: 10.1007/s11042-022-12709-2.",
  "K. Yousaf and T. Nawaz, “A deep learning-based approach for inappropriate content detection and classification of YouTube videos,” IEEE Access, vol. 10, pp. 16283–16298, 2022, doi: 10.1109/ACCESS.2022.3147519.",
  "A. Cattaneo, H. van der Meij, C. Aprea, F. Sauli, and C. Zahn, “A model for designing hypervideo-based instructional scenarios,” Interact. Learn. Environ., vol. 27, no. 4, pp. 508–529, 2019, doi: 10.1080/10494820.2018.1486860.",
  "C. Halkiopoulos and E. Gkintoni, “Leveraging AI in e-learning: personalized learning and adaptive assessment through cognitive neuropsychology—a systematic analysis,” Electronics, vol. 13, no. 18, art. 3762, 2024, doi: 10.3390/electronics13183762.",
  "M. Chakraborty et al., “PAL: Personal Adaptive Learner,” in Proc. AAAI Conf. Artif. Intell., 2026; arXiv:2604.13017.",
  "T. Baarslag, M. Kaisers, E. Gerding, C. Jonker, and J. Gratch, “Computers that negotiate on our behalf: major challenges for self-sufficient, self-directed, and interdependent negotiating agents,” in Autonomous Agents and Multiagent Systems (LNCS 10643), 2017, pp. 143–163, doi: 10.1007/978-3-319-71679-4_10.",
  "G. Madasamy Raja, M. Thaha, R. Latha, and A. Karthikeyan, “Texture classification using optimized local ternary patterns with nonlinear diffusion as pre-processing,” Multimed. Tools Appl., vol. 79, pp. 3831–3846, 2020, doi: 10.1007/s11042-019-7197-0.",
  "C. Chiou, “Assessing the impact of integrating augmented reality technology and animated multidimensional concept maps into multimedia learning materials for enhancing positive emotions and cognitive achievements,” Smart Learn. Environ., 2026, doi: 10.1186/s40561-026-00462-0.",
  "Y. Sun and F. Liu, “The impact of an AI digital teacher on human-AI collaborative learning in higher education,” Smart Learn. Environ., vol. 13, art. 30, 2026, doi: 10.1186/s40561-026-00454-0.",
  "A. Madaan et al., “Self-Refine: iterative refinement with self-feedback,” in Adv. Neural Inf. Process. Syst. (NeurIPS), 2023; arXiv:2303.17651.",
  "N. Carion et al., “SAM 3: Segment anything with concepts,” arXiv:2511.16719, 2025.",
  "S. Liu et al., “Grounding DINO: marrying DINO with grounded pre-training for open-set object detection,” in Proc. ECCV, 2024; arXiv:2303.05499.",
  "A. Radford et al., “Learning transferable visual models from natural language supervision,” in Proc. ICML, 2021; arXiv:2103.00020.",
  "A. Radford et al., “Robust speech recognition via large-scale weak supervision,” in Proc. ICML, 2023; arXiv:2212.04356.",
  "Google, “Agent2Agent (A2A) protocol specification,” 2025. [Online]. Available: https://a2a-protocol.org",
  "The Manim Community Developers, “Manim – mathematical animation framework,” v0.21, 2026. [Online]. Available: https://www.manim.community",
];
const refParas = [new Paragraph({ children: [t("References", { smallCaps: true })], alignment: AlignmentType.CENTER, spacing: { before: 160, after: 80 } }),
  ...refs.map((r, i) => new Paragraph({ children: [t(`[${i + 1}]`, { size: SMALL }), t(`\t${r}`, { size: SMALL })],
    tabStops: [{ type: TabStopType.LEFT, position: 360 }], indent: { left: 360, hanging: 360 }, alignment: AlignmentType.JUSTIFIED,
    spacing: { after: 20 } }))];

const page = { size: { width: 12240, height: 15840 }, margin: { top: 1080, bottom: 1440, left: 900, right: 900 } };
const twoCol = { page, type: SectionType.CONTINUOUS, column: { count: 2, space: 360, equalWidth: true } };
const oneCol = { page, type: SectionType.CONTINUOUS, column: { count: 1 } };

const doc = new Document({
  creator: "LOOM team", title: "LOOM - IEEE paper",
  styles: { default: { document: { run: { font: FONT, size: BODY } } } },
  numbering: { config: [
    { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 280, hanging: 180 } } } }] },
    { reference: "steps", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1)", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 360, hanging: 260 } } } }] },
  ] },
  sections: [
    { properties: { page }, children: title },
    { properties: twoCol, children: body },
    { properties: oneCol, children: figure("architecture.png", "LOOM as built: four services joined by JSON contracts A–D; every agent, including a third-party plug-in, is discovered through its A2A Agent Card. The verification loop sends structured Critic issues back to the mesh through the orchestrator’s revise_cut skill.", 690) },
    { properties: twoCol, children: afterArch },
    { properties: oneCol, children: [
      ...figure("redaction_pair.png", "Per-object redaction. Left: source frame at 60.5 s. Right: what the Parent + child viewer sees — only the broken glass is blurred and labelled; the rest of the lesson plays normally.", 690),
      ...figure("weaves.png", "Same threads, a different weave per viewer: verified cuts for the three profiles over the 74.6 s source (amber: kept, light: condensed, grey: skipped, purple: generated explainer, pink: per-object mask).", 690),
      ...figure("explainer_strip.png", "Frames of an Animator-generated Manim explainer for the neutralization concept (H⁺ and OH⁻ merge into H₂O; Na⁺ and Cl⁻ form NaCl). The last two frames show a label-overlap defect that the Critic does not check.", 690),
    ] },
    { properties: twoCol, children: [...afterFigs, ...refParas] },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  const out = path.join(__dirname, "LOOM_IEEE_Paper.docx");
  fs.writeFileSync(out, buf);
  console.log("wrote", out);
});
