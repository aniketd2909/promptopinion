"""AddAllergy — record a new allergy / intolerance for the patient."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Optional

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists


async def add_allergy(
    substance: Annotated[
        str,
        Field(
            description="What the patient is allergic to, e.g. 'Penicillin', 'Peanuts'."
        ),
    ],
    reaction: Annotated[
        Optional[str],
        Field(description="Free-text description of the reaction."),
    ] = None,
    severity: Annotated[
        Optional[str],
        Field(description="Severity: 'mild' | 'moderate' | 'severe'."),
    ] = None,
    criticality: Annotated[
        Optional[str],
        Field(
            description=(
                "Risk level: 'low' | 'high' | 'unable-to-assess'."
            )
        ),
    ] = None,
    category: Annotated[
        Optional[str],
        Field(
            description=(
                "Allergy category: 'food' | 'medication' | 'environment' | 'biologic'."
            )
        ),
    ] = None,
    patientId: Annotated[  # noqa: N803
        Optional[str],
        Field(description="Patient FHIR id. Optional if patient context is set."),
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
    fhir_client = FhirClient(base_url=fhir_context.url, token=fhir_context.token)

    allergy: Dict[str, Any] = {
        "resourceType": "AllergyIntolerance",
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
                    "code": "active",
                }
            ]
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
                    "code": "confirmed",
                }
            ]
        },
        "code": {"text": substance},
        "patient": {"reference": f"Patient/{patientId}"},
        "recordedDate": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if category:
        allergy["category"] = [category]
    if criticality:
        allergy["criticality"] = criticality
    if reaction:
        rx: Dict[str, Any] = {"manifestation": [{"text": reaction}]}
        if severity:
            rx["severity"] = severity
        allergy["reaction"] = [rx]

    created = await fhir_client.create("AllergyIntolerance", allergy)
    return json.dumps(
        {
            "id": created.get("id"),
            "patient_id": patientId,
            "substance": substance,
            "reaction": reaction,
            "severity": severity,
        },
        indent=2,
    )
