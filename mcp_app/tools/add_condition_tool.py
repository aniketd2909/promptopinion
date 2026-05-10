"""AddCondition — add a diagnosis / problem to the patient's record."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Optional

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists


async def add_condition(
    name: Annotated[
        str,
        Field(description="The condition / diagnosis name, e.g. 'Type 2 Diabetes'."),
    ],
    clinicalStatus: Annotated[  # noqa: N803
        str,
        Field(
            description=(
                "FHIR clinical status: 'active' | 'recurrence' | 'relapse' | "
                "'inactive' | 'remission' | 'resolved'."
            )
        ),
    ] = "active",
    onset: Annotated[
        Optional[str],
        Field(
            description="Onset description (free text or YYYY-MM-DD)."
        ),
    ] = None,
    severity: Annotated[
        Optional[str],
        Field(
            description="Severity: 'mild' | 'moderate' | 'severe'."
        ),
    ] = None,
    note: Annotated[
        Optional[str],
        Field(description="Free-text clinical note about this condition."),
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

    condition: Dict[str, Any] = {
        "resourceType": "Condition",
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": clinicalStatus,
                }
            ]
        },
        "code": {"text": name},
        "subject": {"reference": f"Patient/{patientId}"},
        "recordedDate": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if onset:
        # Try YYYY-MM-DD vs free text
        if len(onset) == 10 and onset.count("-") == 2:
            condition["onsetDateTime"] = onset
        else:
            condition["onsetString"] = onset
    if severity:
        condition["severity"] = {"text": severity}
    if note:
        condition["note"] = [{"text": note}]

    created = await fhir_client.create("Condition", condition)
    return json.dumps(
        {
            "id": created.get("id"),
            "patient_id": patientId,
            "name": name,
            "clinicalStatus": clinicalStatus,
        },
        indent=2,
    )
