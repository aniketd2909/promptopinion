"""Structuring agent — turns a transcript into a FHIR-shaped payload.

GPT-4o with the OpenAI structured-output mode (Pydantic schema) gives us a
strict, validated object back. We translate that into real FHIR resources
later in :mod:`backend.fhir.store`.
"""

from __future__ import annotations

from typing import Optional

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

from backend.config import get_settings
from backend.fhir.schemas import StructuredEncounterPayload


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
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to App/.env to enable structuring."
        )

    llm = ChatOpenAI(
        model=settings.structuring_model,
        api_key=settings.openai_api_key,
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
    # `with_structured_output` returns the Pydantic instance directly.
    if isinstance(result, StructuredEncounterPayload):
        return result
    return StructuredEncounterPayload.model_validate(result)
