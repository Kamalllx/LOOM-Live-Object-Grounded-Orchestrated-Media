"""Pre-load native libraries once, before a demo.

On macOS the first load of each native library (.so/.dylib) triggers a security scan that can take
minutes; after that it is cached and loads instantly.

    .venv/bin/python scripts/warmup.py          # what the demo needs (backend, agents, Manim) - fast
    .venv/bin/python scripts/warmup.py --all    # also the perception stack (torch/transformers/whisper),
                                                # only needed to ingest NEW videos; can take a long time
"""
import importlib
import sys
import time

DEMO = ["numpy", "PIL.Image", "PIL.ImageFont", "PIL.ImageFilter", "groq", "httpx", "fastapi", "uvicorn",
        "pydantic", "jsonschema", "manimpango", "cairo", "networkx", "manim"]
PERCEPTION = ["cv2", "pytesseract", "torch", "torchvision", "transformers", "whisper"]

for name in DEMO + (PERCEPTION if "--all" in sys.argv else []):
    t = time.time()
    try:
        importlib.import_module(name)
        if name == "PIL.ImageFont":
            from PIL import ImageFont
            ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 12)
        status = "ok"
    except Exception as e:  # report and continue: one missing optional module should not stop the warm-up
        status = f"FAILED: {e}"
    print(f"{name:18s} {time.time() - t:6.1f}s  {status}", flush=True)
print("warm-up done" + ("" if "--all" in sys.argv else " (demo only; add --all before ingesting new videos)"))
