# LOOM for YouTube (Chrome extension)

A Manifest V3 extension with plain JS and no build step. On a YouTube watch page it adds:

- the LOOM panel (docked on the right, collapsible to a slim tab)
- exact-shape masks drawn over the video
- tracked objects you can click while the video plays
- Ask, Animate it, Quiz me and a Library, with the same scene player as the web workspace
- Loom agent activity and Critic scores, a concept Graph, and a similarity Map that highlights retrieved evidence
- session quiz grading and a **Save to my mastery** action for the next cut

All data comes from your local LOOM gateway at `http://127.0.0.1:8000`.

## Files

| File | What it does |
| --- | --- |
| `manifest.json` | Runs the content scripts on `youtube.com` and grants access to `127.0.0.1:8000`. |
| `background.js` | Service worker. It is the only place that calls the gateway: content scripts send `{path, method, body}` and get back `{ok, status, data}`. Clips are returned as base64 when `as: "base64"` is set. It never caches responses. |
| `rle.js` | Mask decoder (`rle:<h>x<w>:<counts>`). It exposes `self.LoomRle` to `content.js`. |
| `views.js` | Renders the concept graph and similarity map for the YouTube panel. |
| `content.js` | The panel, the overlay over the video, the click popover, the explainer modal and the YouTube SPA navigation handling. |
| `content.css` | All styles, scoped to `#loom-root`, `#loom-modal`, `.loom-pop` and `.loom-layer`. |

## Load it (unpacked)

1. Start the gateway: `uv run loom gateway` (it must answer on `http://127.0.0.1:8000`).
2. In Chrome, open `chrome://extensions` and switch on **Developer mode** (top right).
3. Click **Load unpacked** and pick this `extension/` folder.
4. Open a processed lesson, e.g. https://www.youtube.com/watch?v=ZZO-v10h8tc

## Reload after edits

1. On `chrome://extensions`, click the circular **Reload** arrow on the LOOM card.
2. **Refresh the YouTube tab.** Content scripts in tabs that were already open keep running the old code; until you refresh, LOOM shows "LOOM was reloaded".

The web player and extension use the same gateway and lesson data, but the extension keeps its own YouTube-focused interface. The current extension is version 3.1.0; confirm that Chrome loaded the `remake/extension` folder rather than the older extension in the parent project.

To debug the service worker, click "service worker" on the LOOM card. To debug the page, use the YouTube tab's DevTools console; LOOM only logs overlay warnings there.

## Manual test (about 6 minutes)

1. **Connect.** Open `https://www.youtube.com/watch?v=ZZO-v10h8tc`. The LOOM panel appears on the right with "gateway ready", the video is not covered, and the tab collapses or expands the panel. Stop the gateway and refresh: the panel says "Start LOOM: uv run loom gateway" and reconnects by itself once you start it again.
2. **Weave a cut.** Pick **Parent + child** and press **Weave my cut**. You should see scores, a timeline and a list of masks. Press **Show** on "bottle 1:07–1:09": the bottle, gloves and goggles are blurred in their *exact* outline, with coral edges and a "Masked for Parent + child: … why?" chip. Click **why?** to read the reason. Try theatre mode and fullscreen: the masks stay locked to the picture.
3. **Skip to cut.** Switch the viewer to **Alex**, weave, then seek to 0:05 and play. LOOM jumps to 0:31 with a toast giving the reason. Now drag the YouTube progress bar back into 0:00–0:31: LOOM respects that seek and does not jump you out.
4. **Click an object.** While the video plays (e.g. near 1:02), hover the glass pipette: it lights up in blue with its exact shape. Click it: the video pauses and a popover asks "What do you want to learn about the glass pipette?" Press **Just answer**. Within about 5–25 s you get the answer, a "Found in video" badge, "Jump to 0:15" buttons that seek and play, follow-up chips, and a line like `loom-retriever.answer via A2A · 3.8 s`. Esc closes the popover. Clicks on the YouTube controls bar still work as usual.
5. **Make an animation.** Click an object again, type a question and press Enter (or **Make an animation**). The stepper moves through Writing → Safety check → Rendering → Fact-checking → Narrating; this takes 1–4 min and keeps going if you close the popover. When it is done, a modal plays the narrated clip. Esc or **Back to the lesson** closes it. Open the **Library** tab: the explainer is listed, and clicking it reopens the modal.
6. **Quiz.** In the "Quiz me on…" bar at the bottom, type `broken glass cleanup` and press **Quiz**. Questions appear in the Ask tab (about 15–30 s). Pick an answer: it is graded by the server (green if right, coral if wrong) with a rationale and "Hear it at 0:15" links. Then click a recommended video to check navigation: the masks and popover of the old video disappear and the panel re-initialises for the new one (or offers **Process with LOOM** if it is new).
