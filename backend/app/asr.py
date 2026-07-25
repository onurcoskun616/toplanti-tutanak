"""Speech-to-text for the live meeting-minutes feature (Faz 1).

Turkish transcription via faster-whisper, CPU-only. No diarization/voice
matching happens here (that's Faz 2) — this module only turns one short audio
chunk into text. The optional ``faster_whisper`` import is guarded: if the
package (or its model weights) isn't available, the app still boots — ASR
just stays disabled and the audio-chunk endpoint answers 503.
"""
import logging
import os
import tempfile
import threading

from .config import settings

logger = logging.getLogger("tutanak.asr")

try:
    from faster_whisper import WhisperModel

    _ASR_LIB_OK = True
except Exception:  # pragma: no cover - only hit if the optional dep is absent
    _ASR_LIB_OK = False


def asr_available() -> bool:
    return _ASR_LIB_OK


_model = None
# Concurrent chunk uploads land on different worker threads (see
# asyncio.to_thread in routers/meetings.py). Without this lock, each one
# that finds `_model` still None would kick off its own WhisperModel(...)
# construction (download + init) in parallel — competing for the same
# limited CPU/RAM/network on a constrained host and making a slow first
# load even slower. The lock makes only one thread do the real work; the
# rest block on it (and may still 503 on the per-request timeout upstream,
# but won't each start a redundant load).
_model_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:  # re-check: another thread may have finished first
                _model = WhisperModel(
                    settings.asr_model_size,
                    device=settings.asr_device,
                    compute_type=settings.asr_compute_type,
                )
    return _model


def transcribe(audio_bytes: bytes) -> str:
    """Transcribe one short audio chunk (webm/opus, wav, …) to Turkish text.

    Blocking/CPU-bound — callers should run this off the event loop (e.g. via
    ``asyncio.to_thread``). The chunk is written to a temp file only for the
    duration of the call and always removed afterwards; audio is never
    persisted (see MeetingTranscriptSegment in models.py).
    """
    if not _ASR_LIB_OK:
        raise RuntimeError("faster-whisper is not installed")

    fd, path = tempfile.mkstemp(suffix=".webm")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(audio_bytes)
        model = _get_model()
        segments, info = model.transcribe(path, language=settings.asr_language)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        logger.info(
            "transcribed %d bytes -> duration=%.2fs lang=%s(p=%.2f) text=%r",
            len(audio_bytes),
            info.duration,
            info.language,
            info.language_probability,
            text,
        )
        return text
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
