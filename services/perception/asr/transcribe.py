"""ASR: speech-to-text with sentence-level timestamps.

Primary: Whisper large-v3-turbo hosted on Groq (fast). Fallback: local openai-whisper "base".
Output items match concept-graph.transcript: {start, end, speaker, text}.
"""
import os
import pathlib
import subprocess
import tempfile


def extract_audio(video_path):
    out = pathlib.Path(tempfile.mkdtemp(prefix="loom_asr_")) / "audio.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000",
                    "-b:a", "48k", str(out)], check=True)
    return out


def _clean(segments):
    items = []
    for s in segments:
        text = (s["text"] or "").strip()
        if text:
            items.append({"start": round(float(s["start"]), 2), "end": round(float(s["end"]), 2),
                          "speaker": "narrator", "text": text})
    return items


def _groq(audio):
    from groq import Groq
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    with open(audio, "rb") as f:
        r = client.audio.transcriptions.create(file=(audio.name, f.read()), model="whisper-large-v3-turbo",
                                               response_format="verbose_json", language="en", temperature=0)
    segs = r.segments if hasattr(r, "segments") else r["segments"]
    return _clean([{"start": s["start"], "end": s["end"], "text": s["text"]} if isinstance(s, dict)
                   else {"start": s.start, "end": s.end, "text": s.text} for s in segs])


def _local(audio):
    import whisper
    model = whisper.load_model("base")
    return _clean(model.transcribe(str(audio), language="en", fp16=False)["segments"])


def transcribe(video_path):
    """Returns (transcript, engine_name)."""
    audio = extract_audio(video_path)
    if os.getenv("GROQ_API_KEY"):
        try:
            return _groq(audio), "whisper-large-v3-turbo (Groq)"
        except Exception as e:
            print(f"[asr] Groq Whisper failed ({e}); falling back to local whisper")
    return _local(audio), "whisper-base (local)"
