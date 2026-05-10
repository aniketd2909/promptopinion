"""Clinical-scribe tools: structure transcript, review draft, revise, undo, commit.

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
APPROVAL_SIGNAL = "APPROVE_ENCOUNTER"
UNDO_SIGNAL = "UNDO_PREVIOUS_CHANGE"


def _history_push(tool_context: ToolContext, payload_dict: Dict[str, Any]) -> None:
    history = tool_context.state.get("structured_encounter_history")
    if not isinstance(history, list):
        history = []
    history.append(payload_dict)
    tool_context.state["structured_encounter_history"] = history
    tool_context.state["last_structured_encounter"] = payload_dict


def _review_summary(payload: StructuredEncounterPayload) -> Dict[str, Any]:
    """Return a doctor-friendly draft summary for review inside chat."""
    observations = []
    for item in payload.observations:
        label = item.kind if not item.value else f"{item.kind}: {item.value}"
        observations.append(label)

    conditions = []
    for item in payload.conditions:
        label = item.name if not item.onset else f"{item.name} (onset: {item.onset})"
        conditions.append(label)

    medications = []
    for item in payload.medications:
        label = item.name if not item.dosage else f"{item.name} - {item.dosage}"
        medications.append(label)

    allergies = []
    for item in payload.allergies:
        label = item.substance
        if item.reaction:
            label = f"{label} ({item.reaction})"
        allergies.append(label)

    return {
        "chief_complaint": payload.encounter.reason,
        "encounter_summary": payload.encounter.summary,
        "observations": observations,
        "conditions": conditions,
        "medications": medications,
        "allergies": allergies,
    }


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
    payload_dict = payload.model_dump()
    tool_context.state["structured_encounter_history"] = [payload_dict]
    tool_context.state["last_structured_encounter"] = payload_dict
    return {
        "status": "success",
        "structured": payload_dict,
        "review_summary": _review_summary(payload),
        "approval_signal": APPROVAL_SIGNAL,
        "undo_signal": UNDO_SIGNAL,
        "doctor_reply_options": [
            APPROVAL_SIGNAL,
            "Edit: <corrections>",
            "Regenerate",
            UNDO_SIGNAL,
        ],
    }


def save_revised_encounter_draft(
    structuredEncounterJson: str,  # noqa: N803
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """Validate and persist a revised doctor-facing draft before approval."""
    try:
        encounter_dict = json.loads(structuredEncounterJson)
    except json.JSONDecodeError as exc:
        return {"status": "error", "error": f"invalid JSON: {exc}"}

    try:
        payload = StructuredEncounterPayload.model_validate(encounter_dict)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"schema validation: {exc}"}

    payload_dict = payload.model_dump()
    _history_push(tool_context, payload_dict)
    return {
        "status": "success",
        "structured": payload_dict,
        "review_summary": _review_summary(payload),
        "approval_signal": APPROVAL_SIGNAL,
        "undo_signal": UNDO_SIGNAL,
        "doctor_reply_options": [
            APPROVAL_SIGNAL,
            "Edit: <corrections>",
            "Regenerate",
            UNDO_SIGNAL,
        ],
    }


def undo_last_structured_change(tool_context: ToolContext) -> Dict[str, Any]:
    """Revert to the previous saved encounter draft during doctor review."""
    history = tool_context.state.get("structured_encounter_history")
    if not isinstance(history, list) or not history:
        return {"status": "error", "error": "no structured draft is available to undo"}
    if len(history) == 1:
        current = history[0]
        payload = StructuredEncounterPayload.model_validate(current)
        return {
            "status": "success",
            "message": "No later draft exists. Keeping the original structured draft.",
            "structured": current,
            "review_summary": _review_summary(payload),
            "approval_signal": APPROVAL_SIGNAL,
            "undo_signal": UNDO_SIGNAL,
            "doctor_reply_options": [
                APPROVAL_SIGNAL,
                "Edit: <corrections>",
                "Regenerate",
                UNDO_SIGNAL,
            ],
        }

    history.pop()
    previous = history[-1]
    tool_context.state["structured_encounter_history"] = history
    tool_context.state["last_structured_encounter"] = previous
    payload = StructuredEncounterPayload.model_validate(previous)
    return {
        "status": "success",
        "message": "Reverted to the previous saved draft.",
        "structured": previous,
        "review_summary": _review_summary(payload),
        "approval_signal": APPROVAL_SIGNAL,
        "undo_signal": UNDO_SIGNAL,
        "doctor_reply_options": [
            APPROVAL_SIGNAL,
            "Edit: <corrections>",
            "Regenerate",
            UNDO_SIGNAL,
        ],
    }


async def commit_encounter(
    structuredEncounterJson: str,  # noqa: N803
    tool_context: ToolContext,
    approvalSignal: str,  # noqa: N803
    diagnosisSummary: str = "",  # noqa: N803
) -> Dict[str, Any]:
    """Persist a doctor-approved structured encounter to the FHIR server.

    Args:
        structuredEncounterJson: The approved StructuredEncounterPayload as JSON.
        approvalSignal: Must exactly equal APPROVE_ENCOUNTER to prevent
                        accidental writes before the doctor approves.
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
    if approvalSignal != APPROVAL_SIGNAL:
        return {
            "status": "error",
            "error": (
                "doctor approval is required before commit. "
                f"Call this tool only after the doctor replies with {APPROVAL_SIGNAL}."
            ),
        }

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
        "approval_signal_used": approvalSignal,
        "resources_written": [
            {"resourceType": r["resourceType"], "id": r["id"]} for r in resources
        ],
    }
