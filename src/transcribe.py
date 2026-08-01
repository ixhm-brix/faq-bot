"""Speech-to-text for voice messages.

Channel-neutral, like src/chat.py: any adapter (Telegram voice notes today,
WhatsApp audio later) hands an audio file path here and gets back a transcript.
The channel is responsible for downloading the file; this module only knows
about audio in and text out.

Engine: faster-whisper (CTranslate2). Runs fully locally — no audio API — and
bundles its own decoding (PyAV), so no system ffmpeg is required. Whisper is
multilingual and auto-detects the spoken language.

Config is deployment-level (env vars, not the portal's settings.json) because
model tier and CPU-vs-GPU are infra choices:
  VOICE_MODEL_SIZE   - tiny | base | small | medium | large-v3   (default: base)
  VOICE_DEVICE       - cpu | cuda                                (default: cpu)
  VOICE_COMPUTE_TYPE - int8 | int8_float16 | float16 | float32   (default: int8
                       on CPU, float16 on GPU)
To use the machine's GPU, set VOICE_DEVICE=cuda (needs CUDA 12 + cuDNN 9).
"""
from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger("transcribe")

MODEL_SIZE = os.getenv("VOICE_MODEL_SIZE", "base")
DEVICE = os.getenv("VOICE_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv(
    "VOICE_COMPUTE_TYPE", "int8" if DEVICE == "cpu" else "float16"
)

# Loaded once, on first use. The model (~150 MB for "base") downloads from
# Hugging Face the first time and is then cached under ~/.cache.
_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel  # heavy import, keep it lazy

        log.info(
            "Loading Whisper model '%s' on %s (%s)", MODEL_SIZE, DEVICE, COMPUTE_TYPE
        )
        _model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
    return _model


def _transcribe_sync(path: str) -> str:
    # vad_filter drops silence so a note that's mostly dead air doesn't
    # hallucinate text. beam_size=5 is Whisper's usual quality default.
    segments, info = _get_model().transcribe(path, vad_filter=True, beam_size=5)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    log.info(
        "Transcribed %s: lang=%s (%.2f) chars=%d",
        os.path.basename(path),
        getattr(info, "language", "?"),
        getattr(info, "language_probability", 0.0),
        len(text),
    )
    return text


async def transcribe(path: str) -> str:
    """Transcribe an audio file to text.

    Runs the blocking model call in a worker thread so the bot's event loop
    keeps serving other users while a note is being transcribed. Returns an
    empty string if nothing intelligible was found or transcription failed —
    the caller decides how to phrase the "couldn't understand" reply.
    """
    try:
        return await asyncio.to_thread(_transcribe_sync, path)
    except Exception:
        log.exception("Transcription failed for %s", path)
        return ""
