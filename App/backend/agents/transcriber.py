"""Voice-to-text agent.

Uses OpenAI Whisper (``whisper-1``) — best-in-class for medical / accented
speech and gives us word-level timestamps. The agent is intentionally tiny:
its only job is bytes -> transcript text.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

from backend.config import get_settings


@dataclass
class TranscriptionResult:
    text: str
    language: Optional[str]
    duration_sec: Optional[float]


_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=get_settings().openai_api_key)
    return _client


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> TranscriptionResult:
    """Transcribe a raw audio blob.

    ``filename`` matters because Whisper sniffs the format from the extension.
    Browser MediaRecorder typically gives us ``audio/webm``, while uploads
    keep their original extension (wav/mp3/m4a/etc).
    """
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to App/.env to enable transcription."
        )

    file_like = io.BytesIO(audio_bytes)
    file_like.name = filename
    response = _get_client().audio.transcriptions.create(
        model=settings.whisper_model,
        file=file_like,
        response_format="verbose_json",
    )
    return TranscriptionResult(
        text=response.text,
        language=getattr(response, "language", None),
        duration_sec=getattr(response, "duration", None),
    )
