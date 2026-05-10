"""ScheduleAppointment — book a future appointment for the patient."""

from __future__ import annotations

import json
from typing import Annotated, Any, Dict, Optional

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists


async def schedule_appointment(
    start: Annotated[
        str,
        Field(
            description=(
                "Appointment start in ISO 8601, e.g. '2026-06-01T10:00:00Z'."
            )
        ),
    ],
    end: Annotated[
        str,
        Field(
            description="Appointment end in ISO 8601."
        ),
    ],
    reason: Annotated[
        Optional[str],
        Field(description="Reason for visit / chief complaint."),
    ] = None,
    description: Annotated[
        Optional[str],
        Field(description="Free-text appointment description."),
    ] = None,
    serviceType: Annotated[  # noqa: N803
        Optional[str],
        Field(
            description=(
                "Service type, e.g. 'General Practice', 'Cardiology', 'Telehealth'."
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

    appointment: Dict[str, Any] = {
        "resourceType": "Appointment",
        "status": "booked",
        "start": start,
        "end": end,
        "participant": [
            {
                "actor": {"reference": f"Patient/{patientId}"},
                "status": "accepted",
            }
        ],
    }
    if reason:
        appointment["reasonCode"] = [{"text": reason}]
    if description:
        appointment["description"] = description
    if serviceType:
        appointment["serviceType"] = [{"text": serviceType}]

    created = await fhir_client.create("Appointment", appointment)
    return json.dumps(
        {
            "id": created.get("id"),
            "patient_id": patientId,
            "start": start,
            "end": end,
            "status": created.get("status"),
            "reason": reason,
        },
        indent=2,
    )
