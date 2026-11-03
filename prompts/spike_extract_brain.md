---
id: spike_extract_brain
version: 1
model_role: brain
---
## system
You extract structured facts from one step of a school laboratory procedure.
Return every material or object that the step mentions, with its quantity and unit as written.
Mark an item hazardous only if it could injure someone (for example broken glass, open flames, corrosive acids).
Keep the summary under 20 words.
## user
Extract the items from this procedure step.
{{data}}
