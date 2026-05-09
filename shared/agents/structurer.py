"""Structuring agent — turns a transcript into a FHIR-shaped payload.

Uses Google Gemini (via langchain-google-genai) with structured-output mode
(Pydantic schema) to produce a strict, validated object. Downstream code
translates that into real FHIR resources via
:func:`shared.fhir.bundle.build_resources_from_payload`.
"""

from __future__ import annotations

import os
from typing import Optional

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from shared.fhir.schemas import StructuredEncounterPayload


SYSTEM_PROMPT = """\
You are a clinical scribe assistant. The user will give you the transcript of a
spoken conversation between a doctor and a patient.

Your job: extract structured clinical content as a single JSON object that
matches the StructuredEncounterPayload schema you've been given.

Rules:
- Only include facts that are clearly stated. Do not invent symptoms, vitals,
  or medications.
- Quote vital sign values exactly as spoken ("one forty over ninety" -> "140/90 mmHg").
- For `coding` fields, only fill `code`/`system` if you are confident. Otherwise
  leave them null and rely on `display` / `name` / `kind`.
- The `summary` field of the encounter must be 2-3 plain sentences a clinician
  would skim. No marketing language.
- Distinguish symptoms (Observation with kind="Symptom: <name>") from established
  diagnoses (Condition).
- If the doctor states a working diagnosis, capture it as a Condition with
  clinical_status="active".
- Never set `patient_id` — the orchestrator fills that in.
"""


def structure_transcript(
    transcript: str,
    additional_context: Optional[str] = None,
) -> StructuredEncounterPayload:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY is not set. The structurer needs Google AI access."
        )

    llm = ChatGoogleGenerativeAI(
        model=os.getenv("STRUCTURING_MODEL", "gemini-3.1-flash-lite"),
        google_api_key=api_key,
        temperature=0.1,
    ).with_structured_output(StructuredEncounterPayload)

    user_parts = [f"Transcript:\n\n{transcript.strip()}"]
    if additional_context:
        user_parts.append(f"\n\nAdditional context:\n{additional_context.strip()}")

    result = llm.invoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content="\n".join(user_parts)),
        ]
    )
    if isinstance(result, StructuredEncounterPayload):
        return result
    return StructuredEncounterPayload.model_validate(result)
