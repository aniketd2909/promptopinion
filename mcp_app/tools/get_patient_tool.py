"""GetPatient — fetch a patient's demographics by FHIR id."""

from __future__ import annotations

import json
from typing import Annotated, Any, Dict, Optional

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists


async def get_patient(
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
    fhir_client = FhirClient(base_url=fhir_context.url, token=fhir_context.token)

    patient = await fhir_client.read(f"Patient/{patientId}")
    if not patient:
        raise ValueError(f"Patient {patientId} not found.")

    return json.dumps(_summarize_patient(patient), indent=2)


def _summarize_patient(patient: Dict[str, Any]) -> Dict[str, Any]:
    names = patient.get("name") or []
    primary_name = names[0] if names else {}
    given = " ".join(primary_name.get("given") or [])
    family = primary_name.get("family") or ""

    telecom = patient.get("telecom") or []
    contacts = [
        {"system": t.get("system"), "value": t.get("value"), "use": t.get("use")}
        for t in telecom
    ]

    address = patient.get("address") or []

    return {
        "id": patient.get("id"),
        "name": f"{given} {family}".strip(),
        "gender": patient.get("gender"),
        "birthDate": patient.get("birthDate"),
        "deceased": patient.get("deceasedBoolean") or patient.get("deceasedDateTime"),
        "contacts": contacts,
        "address": address,
        "maritalStatus": (patient.get("maritalStatus") or {}).get("text"),
    }
