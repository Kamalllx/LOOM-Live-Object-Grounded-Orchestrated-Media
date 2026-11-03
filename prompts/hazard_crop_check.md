---
id: hazard_crop_check
version: 1
model_role: brain
think: false
---
## system
You verify one detection from an educational video. A detector proposed that the attached crops (the same object at
different moments) show: "{{param:phrase}}". Things that are often confused with it: {{param:lookalikes}}.
Decide whether the crops really show "{{param:phrase}}". Answer is_phrase=true only if you can see it; if the crops
show one of the look-alikes or something else, answer false and give better_label. confidence is your probability
(0 to 1) that the crops show "{{param:phrase}}".
## user
Crops of the proposed "{{param:phrase}}" are attached.
