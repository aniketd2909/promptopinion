"""UpdatePatientDemographics — edit name / contact info on an existing patient."""

from __future__ import annotations

import json
from typing import Annotated, Any, Dict, List, Optional

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists


async def update_patient_demographics(
    patientId: Annotated[  # noqa: N803
        Optional[str],
        Field(description="The patient's FHIR id. Optional if patient context is set."),
    ] = None,
    firstName: Annotated[  # noqa: N803
        Optional[str],
        Field(description="New first (given) name."),
    ] = None,
    lastName: Annotated[  # noqa: N803
        Optional[str],
        Field(description="New last (family) name."),
    ] = None,
    birthDate: Annotated[  # noqa: N803
        Optional[str],
        Field(description="New date of birth in YYYY-MM-DD format."),
    ] = None,
    gender: Annotated[
        Optional[str],
        Field(description="One of: male | female | other | unknown."),
    ] = None,
    phone: Annotated[
        Optional[str],
        Field(description="Replace primary phone number."),
    ] = None,
    email: Annotated[
        Optional[str],
        Field(description="Replace primary email."),
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

    existing = await fhir_client.read(f"Patient/{patientId}")
    if not existing:
        raise ValueError(f"Patient {patientId} not found.")

    if firstName or lastName:
        names = existing.get("name") or [{}]
        primary = names[0]
        if firstName:
            primary["given"] = [firstName]
        if lastName:
            primary["family"] = lastName
        names[0] = primary
        existing["name"] = names
    if birthDate:
        existing["birthDate"] = birthDate
    if gender:
        existing["gender"] = gender

    if phone or email:
        telecom: List[Dict[str, Any]] = [
            t for t in (existing.get("telecom") or [])
            if not (
                (phone and t.get("system") == "phone")
                or (email and t.get("system") == "email")
            )
        ]
        if phone:
            telecom.append({"system": "phone", "value": phone, "use": "mobile"})
        if email:
            telecom.append({"system": "email", "value": email})
        existing["telecom"] = telecom

    updated = await fhir_client.update("Patient", patientId, existing)
    return json.dumps(
        {
            "id": updated.get("id"),
            "name": (updated.get("name") or [{}])[0],
            "updated": True,
        },
        indent=2,
    )
