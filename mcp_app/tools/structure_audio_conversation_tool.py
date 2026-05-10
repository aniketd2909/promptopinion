"""StructureAudioConversation — audio URL -> transcript -> structured payload.

Convenience wrapper for callers that hand the platform a URL to a recorded
encounter rather than a typed transcript. The tool:

1. Downloads the audio from the URL using the shared httpx client.
2. Calls :mod:`shared.agents.transcriber` to produce a verbatim transcript.
3. Forwards that transcript to :func:`structure_clinical_conversation` so the
   downstream caller gets the same StructuredEncounterPayload JSON it would
   get from a text-based transcript.

Inline audio is capped at ~20 MB per Gemini's request size limits — files
larger than this should be uploaded via the Files API (not yet wired up).
"""

from __future__ import annotations

import os
from typing import Annotated, Optional
from urllib.parse import urlparse

import httpx
from pydantic import Field

from mcp_app.http import get_http_client
from mcp_app.tools.structure_conversation_tool import structure_clinical_conversation
from shared.agents.transcriber import transcribe_audio


_MAX_AUDIO_BYTES = 20 * 1024 * 1024  # 20 MB

_EXTENSION_MIME = {
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
    ".webm": "audio/webm",
}


def _mime_from_url(url: str) -> Optional[str]:
    path = urlparse(url).path.lower()
    ext = os.path.splitext(path)[1]
    return _EXTENSION_MIME.get(ext)


def _resolve_mime(response: httpx.Response, url: str) -> str:
    header = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if header.startswith("audio/"):
        return header
    guessed = _mime_from_url(url)
    if guessed:
        return guessed
    raise ValueError(
        f"Could not determine audio MIME type for {url!r}. "
        f"Server returned Content-Type={header or '(none)'} and the URL has "
        f"no recognised audio extension."
    )


async def structure_audio_conversation(
    audioUrl: Annotated[  # noqa: N803
        str,
        Field(
            description=(
                "HTTP(S) URL pointing to a recorded doctor-patient conversation. "
                "Supported audio formats: mp3, wav, ogg, flac, aac, m4a/mp4, "
                "aiff, webm. Maximum size ~20 MB."
            )
        ),
    ],
    additionalContext: Annotated[  # noqa: N803
        Optional[str],
        Field(
            description=(
                "Optional extra context the structuring model should consider — "
                "e.g. the chief complaint as recorded by the front desk."
            )
        ),
    ] = None,
) -> str:
    if not audioUrl or not audioUrl.strip():
        raise ValueError("audioUrl is empty.")

    parsed = urlparse(audioUrl)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"audioUrl must be an http(s) URL; got scheme {parsed.scheme!r}."
        )

    client = get_http_client()
    try:
        response = await client.get(audioUrl, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Failed to download audio from {audioUrl}: {exc}") from exc

    audio_bytes = response.content
    if not audio_bytes:
        raise ValueError(f"Downloaded audio from {audioUrl} is empty.")
    if len(audio_bytes) > _MAX_AUDIO_BYTES:
        raise ValueError(
            f"Audio file is {len(audio_bytes)} bytes, exceeding the "
            f"{_MAX_AUDIO_BYTES}-byte inline limit."
        )

    mime_type = _resolve_mime(response, audioUrl)

    transcript = await transcribe_audio(
        audio_bytes=audio_bytes,
        mime_type=mime_type,
        additional_context=additionalContext,
    )

    return await structure_clinical_conversation(
        transcript=transcript,
        additionalContext=additionalContext,
    )
