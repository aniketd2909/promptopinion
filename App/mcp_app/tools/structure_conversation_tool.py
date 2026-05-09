"""StructureClinicalConversation — transcript -> FHIR-shaped JSON via GPT-4o."""

from __future__ import annotations

import json
import os
from typing import Annotated, Optional

from pydantic import Field

from backend.agents.fhir_structurer import structure_transcript


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
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError(
            "OPENAI_API_KEY is not configured for the MCP server. The "
            "structuring tool needs OpenAI access."
        )
    if not transcript or not transcript.strip():
        raise ValueError("Transcript is empty.")

    payload = structure_transcript(
        transcript=transcript,
        additional_context=additionalContext,
    )
    return json.dumps(payload.model_dump(), indent=2)
