"""Clinical-scribe tools: structure transcript, suggest diagnosis, commit encounter.

These wrap the shared structuring + FHIR-bundle helpers and expose them as
ADK tools that read FHIR context from session state.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

import httpx
from google.adk.tools import ToolContext

from shared.agents.structurer import structure_transcript
from shared.fhir.bundle import build_resources_from_payload
from shared.fhir.schemas import StructuredEncounterPayload


logger = logging.getLogger(__name__)


def structure_clinical_conversation(
    transcript: str,
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """Convert a doctor-patient transcript into a structured FHIR-shaped payload.

    Args:
        transcript: The raw transcript text.
    """
    if not transcript or not transcript.strip():
        return {"status": "error", "error": "transcript is empty"}
    try:
        payload = structure_transcript(transcript=transcript)
    except Exception as exc:  # noqa: BLE001
        logger.exception("tool_structure_clinical_conversation_error")
        return {"status": "error", "error": str(exc)}
    tool_context.state["last_structured_encounter"] = payload.model_dump()
    return {"status": "success", "structured": payload.model_dump()}


async def commit_encounter(
    structuredEncounterJson: str,  # noqa: N803
    tool_context: ToolContext,
    diagnosisSummary: str = "",  # noqa: N803
) -> Dict[str, Any]:
    """Persist a doctor-approved structured encounter to the FHIR server.

    Args:
        structuredEncounterJson: The approved StructuredEncounterPayload as JSON.
        diagnosisSummary: Optional diagnosis summary string from the diagnosis
                          step. When provided, written as a ClinicalImpression.
    """
    state = tool_context.state
    fhir_url = state.get("fhir_url")
    fhir_token = state.get("fhir_token")
    patient_id = state.get("patient_id")
    if not fhir_url:
        return {
            "status": "error",
            "error": "fhir_url not in session state — caller must send fhir-context",
        }
    if not patient_id:
        return {"status": "error", "error": "patient_id not in session state"}

    try:
        encounter_dict = json.loads(structuredEncounterJson)
    except json.JSONDecodeError as exc:
        return {"status": "error", "error": f"invalid JSON: {exc}"}

    try:
        payload = StructuredEncounterPayload.model_validate(encounter_dict)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"schema validation: {exc}"}

    resources = build_resources_from_payload(
        patient_id=patient_id,
        payload=payload,
        diagnosis_summary=diagnosisSummary or None,
    )
    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {"resource": r, "request": {"method": "POST", "url": r["resourceType"]}}
            for r in resources
        ],
    }
    headers = {
        "Accept": "application/fhir+json",
        "Content-Type": "application/fhir+json",
    }
    if fhir_token:
        headers["Authorization"] = f"Bearer {fhir_token}"
    try:
        async with httpx.AsyncClient(base_url=fhir_url.rstrip("/"), headers=headers, timeout=30.0) as client:
            r = await client.post("/", json=bundle)
            r.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("tool_commit_encounter http_error=%s", exc)
        return {"status": "error", "error": str(exc)}

    return {
        "status": "success",
        "patient_id": patient_id,
        "resources_written": [
            {"resourceType": r["resourceType"], "id": r["id"]} for r in resources
        ],
    }
