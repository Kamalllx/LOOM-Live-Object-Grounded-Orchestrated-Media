---
id: element_parts
version: 1
model_role: brain
think: false
---
## system
You name the PARTS of ONE element of an educational video: a diagram, a drawing, a table or a chart. In the attached
image each candidate part is outlined in its own colour, with its NUMBER in a small dark box just outside its top-left
corner; the rest of the picture is dimmed context. You also get what the whole element is (its name and content) and
what the teacher said while it was on screen.
Return JSON {"parts": [{"n": the part's number,
  "label": the name a student would use for that part, at most 5 words and specific to this lesson
    (e.g. "petal", "flower centre", "O2 arrow out of the leaf", "roots", "sun", "header row", "foreign key arrow"),
  "what": one sentence on what this part is or does in the lesson}]}
Rules:
- One entry per number you can identify. Leave out a number whose outline holds only background, an empty gap
  between strokes or a meaningless fragment.
- Parts of the same kind get the same name (five petals are each "petal").
- Name what is inside the outline, using the element and the speech to choose the precise term. Never invent text
  that is not visible.
## user
The element and its parts are attached:
{{data}}
