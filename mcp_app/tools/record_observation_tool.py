"""RecordObservation — write a single vital sign or lab result to FHIR."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Optional

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists


async def record_observation(
    code: Annotated[
        str,
        Field(
            description=(
                "Free-text label for what was measured, e.g. 'Blood pressure', "
                "'Heart rate', 'Hemoglobin A1c'."
            )
        ),
    ],
    value: Annotated[
        str,
        Field(
            description=(
                "The measured value as a string, e.g. '120/80', '72', '6.2'."
            )
        ),
    ],
    unit: Annotated[
        Optional[str],
        Field(description="Unit, e.g. 'mmHg', 'bpm', '%'."),
    ] = None,
    category: Annotated[
        str,
        Field(
            description=(
                "FHIR observation category: 'vital-signs' | 'laboratory' | "
                "'imaging' | 'social-history' | 'survey'."
            )
        ),
    ] = "vital-signs",
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

    observation: Dict[str, Any] = {
        "resourceType": "Observation",
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": category,
                        "display": category.replace("-", " ").title(),
                    }
                ],
                "text": category,
            }
        ],
        "code": {"text": code},
        "subject": {"reference": f"Patient/{patientId}"},
        "effectiveDateTime": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }

    try:
        numeric = float(value)
        q: Dict[str, Any] = {"value": numeric}
        if unit:
            q["unit"] = unit
        observation["valueQuantity"] = q
    except ValueError:
        observation["valueString"] = value if not unit else f"{value} {unit}"

    created = await fhir_client.create("Observation", observation)
    return json.dumps(
        {
            "id": created.get("id"),
            "patient_id": patientId,
            "code": code,
            "value": value,
            "unit": unit,
            "category": category,
        },
        indent=2,
    )
