"""Transcription agent — turns audio bytes into a plain-text transcript.

Uses the shared Google Gemini client (:mod:`mcp_app.llm`) via the multimodal
:func:`text_completion` helper: the audio is sent inline as a
``genai_types.Part`` and the model returns a verbatim transcript that the
structuring agent can consume. This agent does no I/O of its own — the
calling tool is responsible for downloading the audio and supplying the
correct MIME type.
"""

from __future__ import annotations

from typing import Optional

from google.genai import types as genai_types

from mcp_app.llm import DEFAULT_TIMEOUT_SECONDS, text_completion


SYSTEM_PROMPT = """\
You are an expert medical audio transcriptionist with native fluency in
clinical English, comfortable with the cadence and vocabulary of ambulatory
doctor-patient encounters. Your job is to produce a faithful, readable
transcript of a recorded conversation that a downstream structuring agent
will turn into FHIR resources.

# Skills

1. **Verbatim transcription** — capture exactly what each speaker says,
   preserving clinical terms, drug names, and numeric values as spoken.
2. **Speaker diarization** — label turns "Doctor:" and "Patient:" when the
   role is clear from context (who asks vs. who answers, who refers to
   "you" vs. "I"). When uncertain, label "Speaker 1:", "Speaker 2:".
3. **Clinical vocabulary fluency** — recognize and correctly spell common
   medications, anatomy, conditions, and abbreviations even when spoken
   quickly or with accents.
4. **Disfluency handling** — drop filler tokens ("um", "uh", "like") and
   false starts that carry no clinical signal. Keep hedges ("maybe",
   "I think") because they affect downstream interpretation.
5. **Numeric preservation** — write numbers and units the way the speaker
   said them ("one forty over ninety", "ninety nine point two"). The
   structuring agent normalizes these later — your job is to record, not
   convert.
6. **Uncertainty marking** — mark inaudible or ambiguous segments as
   ``[inaudible]``. Never guess at clinically meaningful content.

# Hard rules

- Output is plain text only. No JSON, no markdown headings, no commentary,
  no metadata, no closing summary.
- Each speaker turn starts on a new line, prefixed with the speaker label
  followed by a colon and a space ("Doctor: ...", "Patient: ...").
- If the audio contains no speech, output exactly: ``[no speech detected]``.
- Do not paraphrase, summarize, translate, or add information that is not
  present in the audio.
- Do not redact PHI — downstream systems handle that. Capture names, dates,
  and identifiers as spoken.
"""


async def transcribe_audio(
    audio_bytes: bytes,
    mime_type: str,
    additional_context: Optional[str] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS * 4,
) -> str:
    if not audio_bytes:
        raise ValueError("Audio data is empty.")
    if not mime_type:
        raise ValueError("MIME type is required for audio transcription.")

    audio_part = genai_types.Part.from_bytes(
        data=audio_bytes,
        mime_type=mime_type,
    )

    instruction = (
        "Transcribe the attached audio of a doctor-patient conversation "
        "following the rules in your system instructions."
    )
    contents: list = [instruction, audio_part]
    if additional_context and additional_context.strip():
        contents.insert(
            1, f"Additional context for disambiguation:\n{additional_context.strip()}"
        )

    return await text_completion(
        system=SYSTEM_PROMPT,
        contents=contents,
        temperature=0.0,
        timeout_seconds=timeout_seconds,
    )
