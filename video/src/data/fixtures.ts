// The film's on-screen data comes straight from the repo's contract fixtures.
import conceptGraph from "../../../fixtures/concept-graph.sample.json";
import candidateCut from "../../../fixtures/candidate-cut.sample.json";
import verifiedCut from "../../../fixtures/verified-cut.sample.json";
import learnerProfile from "../../../fixtures/learner-profile.sample.json";

export { conceptGraph, candidateCut, verifiedCut, learnerProfile };

export const beaker = conceptGraph.objects[0];
export const transcriptLine = conceptGraph.transcript[0];
export const ocrLine = conceptGraph.on_screen_text[0];
export const conceptNode = conceptGraph.concept_nodes[0];
export const mastery = learnerProfile.mastery_graph[0];
export const redaction = verifiedCut.redaction_masks[0];

export const fmtTime = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** Where things actually sit in the generated footage, in 0–1 frame coordinates. */
export const FOOTAGE = {
  demo: { src: "footage/demo.mp4", beaker: { x: 0.196, y: 0.339, w: 0.271, h: 0.581 } },
  hazard: { src: "footage/hazard.mp4", shards: { x: 0.47, y: 0.7, w: 0.405, h: 0.225 } },
};

export const demoFrames = Array.from({ length: 12 }, (_, i) => `footage/frames/demo_${String(i + 1).padStart(2, "0")}.jpg`);
export const hazardFrames = Array.from({ length: 4 }, (_, i) => `footage/frames/hazard_${String(i + 1).padStart(2, "0")}.jpg`);
