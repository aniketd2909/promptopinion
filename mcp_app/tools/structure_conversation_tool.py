"""StructureClinicalConversation — transcript -> FHIR-shaped JSON via Gemini."""

from __future__ import annotations

from typing import Annotated, Optional

from pydantic import Field

from shared.agents.structurer import structure_transcript


async def structure_clinical_conversation(
    transcript: Annotated[
        str,
        Field(description="Raw transcript of a doctor-patient conversation."),
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
    if not transcript or not transcript.strip():
        raise ValueError("Transcript is empty.")

    payload = await structure_transcript(
        transcript=transcript,
        additional_context=additionalContext,
    )
    return payload.model_dump_json(indent=2)
