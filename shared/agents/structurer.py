"""Structuring agent — turns a transcript into a FHIR-shaped payload.

Uses the shared Google Gemini client (:mod:`mcp_app.llm`) with structured
output: the model is forced to emit JSON matching the
:class:`StructuredEncounterPayload` schema, which is then validated. Downstream
code translates the validated payload into real FHIR resources via
:func:`shared.fhir.bundle.build_resources_from_payload`.
"""

from __future__ import annotations

from typing import Optional

from mcp_app.llm import structured_completion
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

async def structure_transcript(
    transcript: str,
    additional_context: Optional[str] = None,
) -> StructuredEncounterPayload:
    transcript = transcript.strip()
    if not transcript:
        raise ValueError("Transcript is empty.")

    user_parts = [f"Transcript:\n\n{transcript}"]
    if additional_context and additional_context.strip():
        user_parts.append(f"\n\nAdditional context:\n{additional_context.strip()}")

    return await structured_completion(
        system=SYSTEM_PROMPT,
        user="\n".join(user_parts),
        schema=StructuredEncounterPayload,
    )
