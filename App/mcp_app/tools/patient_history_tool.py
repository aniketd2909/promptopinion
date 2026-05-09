"""GetPatientHistory — fetch the patient's clinical history from FHIR."""

from __future__ import annotations

import json
from typing import Annotated, Any, Dict, List, Optional

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists


_RESOURCE_TYPES = (
    ("Encounter", "subject"),
    ("Condition", "subject"),
    ("Observation", "subject"),
    ("MedicationStatement", "subject"),
    ("MedicationRequest", "subject"),
    ("AllergyIntolerance", "patient"),
    ("ClinicalImpression", "subject"),
)


async def get_patient_history(
    patientId: Annotated[  # noqa: N803
        Optional[str],
        Field(description="The patient's FHIR id. Optional if patient context is set."),
    ] = None,
    ctx: Context = None,
) -> str:
    if not patientId:
        patientId = get_patient_id_if_context_exists(ctx)
    if not patientId:
        raise ValueError(
            "No patient id provided and no patient context found in the request."
        )

    fhir_context = get_fhir_context(ctx)
    if not fhir_context:
        raise ValueError(
            "No FHIR context found. The platform must send the "
            "x-fhir-server-url and x-fhir-access-token headers."
        )

    fhir_client = FhirClient(base_url=fhir_context.url, token=fhir_context.token)

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    total = 0
    for rt, search_param in _RESOURCE_TYPES:
        bundle = await fhir_client.search(
            rt, {search_param: f"Patient/{patientId}"}
        )
        if not bundle or not bundle.get("entry"):
            continue
        resources = [e["resource"] for e in bundle["entry"] if e.get("resource")]
        if resources:
            grouped[rt] = [_summarize(r) for r in resources]
            total += len(resources)

    return json.dumps(
        {"patient_id": patientId, "total": total, "history": grouped},
        indent=2,
    )


def _summarize(resource: Dict[str, Any]) -> Dict[str, Any]:
    """Trim a FHIR resource to the fields the LLM actually uses for diagnosis."""
    rt = resource.get("resourceType")
    base = {"id": resource.get("id"), "resourceType": rt}

    if rt == "Encounter":
        base.update(
            {
                "status": resource.get("status"),
                "class": (resource.get("class") or {}).get("code"),
                "reason": [(rc.get("text") or "") for rc in (resource.get("reasonCode") or [])],
                "period": resource.get("period"),
            }
        )
    elif rt == "Condition":
        base.update(
            {
                "code": (resource.get("code") or {}).get("text"),
                "clinicalStatus": ((resource.get("clinicalStatus") or {}).get("coding") or [{}])[0].get("code"),
                "onsetString": resource.get("onsetString"),
                "recordedDate": resource.get("recordedDate"),
            }
        )
    elif rt == "Observation":
        base.update(
            {
                "code": (resource.get("code") or {}).get("text"),
                "value": resource.get("valueString")
                or resource.get("valueQuantity")
                or resource.get("valueCodeableConcept"),
                "effectiveDateTime": resource.get("effectiveDateTime"),
            }
        )
    elif rt in ("MedicationStatement", "MedicationRequest"):
        med = resource.get("medicationCodeableConcept") or {}
        base.update(
            {
                "status": resource.get("status"),
                "medication": med.get("text"),
                "dosage": [
                    (d.get("text") or "") for d in (resource.get("dosage") or [])
                ],
            }
        )
    elif rt == "AllergyIntolerance":
        base.update(
            {
                "substance": (resource.get("code") or {}).get("text"),
                "criticality": resource.get("criticality"),
            }
        )
    elif rt == "ClinicalImpression":
        base.update({"summary": resource.get("summary"), "date": resource.get("date")})

    return base
