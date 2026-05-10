"""CreatePatient — register a new patient on the FHIR server."""

from __future__ import annotations

import json
from typing import Annotated, Any, Dict, List, Optional

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context


async def create_patient(
    firstName: Annotated[str, Field(description="The patient's first (given) name")],  # noqa: N803
    lastName: Annotated[str, Field(description="The patient's last (family) name")],  # noqa: N803
    birthDate: Annotated[  # noqa: N803
        Optional[str],
        Field(description="Date of birth in YYYY-MM-DD format."),
    ] = None,
    gender: Annotated[
        Optional[str],
        Field(description="One of: male | female | other | unknown."),
    ] = None,
    phone: Annotated[
        Optional[str],
        Field(description="Phone number."),
    ] = None,
    email: Annotated[
        Optional[str],
        Field(description="Email address."),
    ] = None,
    ctx: Context = None,
) -> str:
    fhir_context = get_fhir_context(ctx)
    fhir_client = FhirClient(base_url=fhir_context.url, token=fhir_context.token)

    telecom: List[Dict[str, Any]] = []
    if phone:
        telecom.append({"system": "phone", "value": phone, "use": "mobile"})
    if email:
        telecom.append({"system": "email", "value": email})

    patient: Dict[str, Any] = {
        "resourceType": "Patient",
        "active": True,
        "name": [{"given": [firstName], "family": lastName}],
    }
    if birthDate:
        patient["birthDate"] = birthDate
    if gender:
        patient["gender"] = gender
    if telecom:
        patient["telecom"] = telecom

    created = await fhir_client.create("Patient", patient)
    return json.dumps(
        {
            "id": created.get("id"),
            "name": f"{firstName} {lastName}",
            "resourceType": created.get("resourceType"),
        },
        indent=2,
    )
