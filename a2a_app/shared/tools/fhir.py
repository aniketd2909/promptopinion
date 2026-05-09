"""FHIR R4 tools for the ADK clinical-scribe agent.

Each tool reads `fhir_url`, `fhir_token`, and `patient_id` from session state
(populated by `extract_fhir_context`) so the agent's LLM never sees credentials.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import httpx
from google.adk.tools import ToolContext


logger = logging.getLogger(__name__)


def _client(state: Dict[str, Any]) -> tuple[httpx.AsyncClient, str] | None:
    fhir_url = state.get("fhir_url")
    if not fhir_url:
        return None
    headers = {"Accept": "application/fhir+json"}
    token = state.get("fhir_token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.AsyncClient(base_url=fhir_url.rstrip("/"), headers=headers, timeout=30.0), fhir_url


def _missing_credentials() -> Dict[str, Any]:
    return {
        "status": "error",
        "error": (
            "FHIR credentials are not available in session state. The caller "
            "must include fhir-context metadata (fhirUrl, fhirToken, patientId) "
            "in the A2A message."
        ),
    }


def _missing_patient() -> Dict[str, Any]:
    return {
        "status": "error",
        "error": "patient_id is not available in session state.",
    }


async def get_patient_demographics(tool_context: ToolContext) -> Dict[str, Any]:
    """Return name, gender, birthDate, contact info for the active patient."""
    state = tool_context.state
    patient_id = state.get("patient_id")
    if not patient_id:
        return _missing_patient()
    setup = _client(state)
    if not setup:
        return _missing_credentials()
    client, _ = setup
    try:
        async with client:
            r = await client.get(f"/Patient/{patient_id}")
            if r.status_code == 404:
                return {"status": "not_found", "patient_id": patient_id}
            r.raise_for_status()
            patient = r.json()
    except httpx.HTTPError as exc:
        logger.warning("tool_get_patient_demographics http_error=%s", exc)
        return {"status": "error", "error": str(exc)}

    names = patient.get("name") or []
    name_label = ""
    if names:
        n = names[0]
        name_label = " ".join(n.get("given") or []) + " " + (n.get("family") or "")
    return {
        "status": "success",
        "patient_id": patient_id,
        "name": name_label.strip(),
        "gender": patient.get("gender"),
        "birthDate": patient.get("birthDate"),
        "telecom": patient.get("telecom"),
        "address": patient.get("address"),
    }


async def _search(state: Dict[str, Any], rt: str, search_param: str = "subject") -> List[Dict[str, Any]] | Dict[str, Any]:
    patient_id = state.get("patient_id")
    if not patient_id:
        return _missing_patient()
    setup = _client(state)
    if not setup:
        return _missing_credentials()
    client, _ = setup
    try:
        async with client:
            r = await client.get(f"/{rt}", params={search_param: f"Patient/{patient_id}"})
            r.raise_for_status()
            bundle = r.json()
    except httpx.HTTPError as exc:
        logger.warning("tool_search %s http_error=%s", rt, exc)
        return {"status": "error", "error": str(exc)}
    return [e["resource"] for e in (bundle.get("entry") or []) if e.get("resource")]


async def get_active_conditions(tool_context: ToolContext) -> Dict[str, Any]:
    """Return the patient's active conditions (problem list)."""
    result = await _search(tool_context.state, "Condition")
    if isinstance(result, dict):
        return result
    conditions = []
    for c in result:
        status = ((c.get("clinicalStatus") or {}).get("coding") or [{}])[0].get("code")
        if status and status != "active":
            continue
        conditions.append(
            {
                "id": c.get("id"),
                "code": (c.get("code") or {}).get("text"),
                "onset": c.get("onsetString") or c.get("onsetDateTime"),
                "recordedDate": c.get("recordedDate"),
            }
        )
    return {"status": "success", "conditions": conditions}


async def get_active_medications(tool_context: ToolContext) -> Dict[str, Any]:
    """Return medications the patient is currently taking or was prescribed."""
    medications: List[Dict[str, Any]] = []
    for rt in ("MedicationStatement", "MedicationRequest"):
        result = await _search(tool_context.state, rt)
        if isinstance(result, dict):
            return result
        for m in result:
            med = m.get("medicationCodeableConcept") or {}
            medications.append(
                {
                    "id": m.get("id"),
                    "kind": rt,
                    "status": m.get("status"),
                    "medication": med.get("text"),
                    "dosage": [d.get("text") for d in (m.get("dosage") or []) if d.get("text")],
                }
            )
    return {"status": "success", "medications": medications}


async def get_recent_observations(tool_context: ToolContext) -> Dict[str, Any]:
    """Return recent observations (vitals, lab values)."""
    result = await _search(tool_context.state, "Observation")
    if isinstance(result, dict):
        return result
    observations = [
        {
            "id": o.get("id"),
            "code": (o.get("code") or {}).get("text"),
            "value": o.get("valueString")
            or o.get("valueQuantity")
            or o.get("valueCodeableConcept"),
            "effectiveDateTime": o.get("effectiveDateTime"),
        }
        for o in result
    ]
    return {"status": "success", "observations": observations}


async def get_allergies(tool_context: ToolContext) -> Dict[str, Any]:
    """Return the patient's recorded allergies."""
    result = await _search(tool_context.state, "AllergyIntolerance", search_param="patient")
    if isinstance(result, dict):
        return result
    allergies = [
        {
            "id": a.get("id"),
            "substance": (a.get("code") or {}).get("text"),
            "criticality": a.get("criticality"),
        }
        for a in result
    ]
    return {"status": "success", "allergies": allergies}
