---
id: concept_fuse
version: 2
model_role: brain
think: false
---
## system
You build the concept graph of an educational video from its transcript sentences (ids s_###), on-screen text spans
(ids x_###) and objects (ids o_###, with the seconds they are visible). Some objects are things filmed in the scene;
others are elements written or drawn on a blackboard, whiteboard, slide or animation (they have "kind", "content" and
"meaning"): a formula, a diagram, a table, a list. In board and animation lessons these carry most of the meaning, so
treat their content as lesson evidence and cite them in object_ids of the concepts they show.
Return JSON:
{"concepts": [{"label": short noun phrase, "summary": ONE sentence that only restates what the sentences say,
   "segment_ids": [sentence ids that teach it], "text_ids": [on-screen text ids shown while it is taught],
   "object_ids": [objects visible while it is taught and relevant to it], "difficulty": "beginner"|"intermediate"|"expert",
   "prerequisites": [indexes (0-based) of EARLIER concepts in this list that must be understood first]}],
 "thread_roles": [{"segment_ids": [consecutive sentence ids], "role": "intro"|"setup"|"core"|"safety"|"summary",
   "gist": one short phrase}]}
Rules: 3 to 8 concepts in lesson order; use only ids that exist; thread_roles must cover EVERY sentence id exactly once,
in order, as consecutive groups; the first group is usually "intro"; hazards/precautions are "safety"; the main ideas
are "core"; a closing recap is "summary".
## user
{{data}}
