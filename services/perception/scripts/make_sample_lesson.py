"""Builds samples/lesson.mp4: a 30 s narrated lab lesson for end-to-end testing of the real models.

Footage: the two Veo clips in video/public/footage (neutralization demo, broken-glass bench).
Narration: Google Cloud Text-to-Speech (gcloud auth). On-screen text: burned-in equation and title.

    python scripts/make_sample_lesson.py [--project curiora-studios]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FOOTAGE = REPO / "video" / "public" / "footage"
OUT = HERE.parent / "samples" / "lesson.mp4"

NARRATION = [
    (0.5, "In this experiment, we add a base to an acid."),
    (3.6, "Combine the two solutions slowly, and watch the beaker."),
    (8.6, "The pink colour fades as sodium hydroxide neutralizes hydrochloric acid, making salt and water."),
    (16.6, "Now, a safety note."),
    (18.6, "If a test tube breaks, never pick up the broken glass with your hands."),
    (24.0, "Sweep the shards into a sharps bin."),
]
FONT = "C\\:/Windows/Fonts/arialbd.ttf" if os.name == "nt" else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def tts(text: str, out: Path, project: str) -> None:
    token = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True, shell=os.name == "nt", check=True).stdout.strip()
    body = {
        "input": {"text": text},
        "voice": {"languageCode": "en-US", "name": "en-US-Chirp3-HD-Charon"},
        "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000},
    }
    req = urllib.request.Request(
        "https://texttospeech.googleapis.com/v1/text:synthesize",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "x-goog-user-project": project, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        out.write_bytes(base64.b64decode(json.loads(r.read())["audioContent"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=os.environ.get("GCP_PROJECT", "curiora-studios"))
    a = ap.parse_args()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    clips = []
    for i, (_, text) in enumerate(NARRATION):
        p = tmp / f"n{i}.wav"
        tts(text, p, a.project)
        clips.append(p)

    inputs = ["-i", str(FOOTAGE / "demo.mp4"), "-i", str(FOOTAGE / "hazard.mp4")]
    for c in clips:
        inputs += ["-i", str(c)]
    video = (
        "[0:v]setpts=2.0*PTS,scale=1280:720,fps=24[a];"
        "[1:v]setpts=1.75*PTS,scale=1280:720,fps=24[b];"
        "[a][b]concat=n=2:v=1:a=0[cat];"
        f"[cat]drawtext=fontfile='{FONT}':text='NaOH + HCl -> NaCl + H2O':fontsize=44:fontcolor=white:"
        "box=1:boxcolor=black@0.65:boxborderw=18:x=(w-text_w)/2:y=48:enable='between(t,9,16)',"
        f"drawtext=fontfile='{FONT}':text='LAB SAFETY':fontsize=52:fontcolor=white:"
        "box=1:boxcolor=0xC0392B@0.85:boxborderw=18:x=60:y=48:enable='between(t,16.5,22)'[v]"
    )
    audio = "".join(f"[{i + 2}:a]adelay={int(t * 1000)}|{int(t * 1000)}[d{i}];" for i, (t, _) in enumerate(NARRATION))
    audio += "".join(f"[d{i}]" for i in range(len(NARRATION))) + f"amix=inputs={len(NARRATION)}:normalize=0,apad[aud]"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", video + ";" + audio, "-map", "[v]", "-map", "[aud]", "-t", "30",
         "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", str(OUT)],
        check=True,
    )
    print(OUT)


if __name__ == "__main__":
    main()
