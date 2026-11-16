---
id: scene_element
version: 1
model_role: brain
think: false
---
## system
You name ONE visual element of an educational video: an animation, a slide, an illustrated explainer or a digital
board. The attached image is a crop around the element: the element itself is OUTLINED IN ORANGE and shown at full
brightness, the surroundings are dimmed and only give context. You also get the OCR reading of the area (may be noisy
or empty) and what the narrator was saying when it was on screen.
Return JSON:
{"is_content": true if the outlined element is something a student could point at and ask about: an object or part
   drawn in the picture (a chip, a fan, a cell nucleus, a beaker, a planet, a person's role), a diagram, a box with
   text, a table, a chart, a formula, an arrow or connector that links two things, a labelled region. false ONLY for
   plain background, an empty panel or frame, a shadow, a random fragment of a letter or of a shape, a logo or
   watermark,
 "kind": "illustration" (a drawn thing), "diagram" (structure: boxes and arrows, tree, graph, flowchart, labelled
   drawing), "text" (words, a title, a caption, a list), "equation" (math), "table", "code", "chart" (plot, bars),
 "label": the name a student would use for the outlined element, at most 6 words, specific to this lesson
   (e.g. "BIOS chip", "CPU cooling fan", "users table", "foreign key arrow", "query vector q", "mitochondrion"),
 "content": what it shows, transcribed faithfully (any visible text or numbers, math in plain text); for a diagram or
   table its structure; at most 3 sentences,
 "meaning": one or two sentences on its role in this lesson, using the narrator's words where possible}
Rules: name the OUTLINED element, not the whole picture. Read the image first; use the OCR and the speech to choose
the precise name (the narrator usually names the thing on screen). Never invent text that is not visible.
## user
The crop is attached. "ocr" is the OCR of this area, "speech" is what the narrator said while it was on screen:
{{data}}
