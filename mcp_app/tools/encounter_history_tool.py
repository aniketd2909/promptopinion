"""GetEncounterHistory — search FHIR Encounter for the patient's visits.

Maps to FHIR R4 Encounter search:
https://www.hl7.org/fhir/encounter.html#search
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Dict, List, Optional
from urllib.parse import urlencode

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists


async def get_encounter_history(
    patientId: Annotated[  # noqa: N803
        Optional[str],
        Field(description="The patient's FHIR id. Optional if patient context is set."),
    ] = None,
    status: Annotated[
        Optional[str],
        Field(
            description=(
                "FHIR `status` filter, comma-separated. Valid: planned | "
                "arrived | triaged | in-progress | onleave | finished | "
                "cancelled."
            )
        ),
    ] = None,
    encounterClass: Annotated[  # noqa: N803
        Optional[str],
        Field(
            description=(
                "FHIR `class` filter — v3 ActCode: AMB (ambulatory) | EMER "
                "(emergency) | IMP (inpatient) | HH (home health) | VR (virtual)."
            )
        ),
    ] = None,
    type: Annotated[
        Optional[str],
        Field(description="FHIR `type` filter (system|code) for encounter type."),
    ] = None,
    date: Annotated[
        Optional[str],
        Field(
            description=(
                "FHIR `date` filter — supports prefixes 'gt', 'ge', 'lt', 'le'. "
                "Example 'gt2024-01-01'."
            )
        ),
    ] = None,
    reasonCode: Annotated[  # noqa: N803
        Optional[str],
        Field(description="FHIR `reason-code` filter."),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Max encounters to return (default 20).", ge=1, le=100),
    ] = 20,
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

    params: Dict[str, str] = {
        "subject": f"Patient/{patientId}",
        "_sort": "-date",
        "_count": str(limit),
    }
    if status:
        params["status"] = status
    if encounterClass:
        params["class"] = encounterClass
    if type:
        params["type"] = type
    if date:
        params["date"] = date
    if reasonCode:
        params["reason-code"] = reasonCode

    bundle = await fhir_client.search("Encounter", params)
    encounters: List[Dict[str, Any]] = []
    if bundle and bundle.get("entry"):
        for entry in bundle["entry"]:
            r = entry.get("resource") or {}
            encounters.append(
                {
                    "id": r.get("id"),
                    "status": r.get("status"),
                    "class": (r.get("class") or {}).get("code"),
                    "type": [
                        (t.get("text") or "") for t in (r.get("type") or [])
                    ],
                    "reason": [
                        (rc.get("text") or "")
                        for rc in (r.get("reasonCode") or [])
                    ],
                    "period": r.get("period"),
                    "serviceProvider": (
                        (r.get("serviceProvider") or {}).get("display")
                    ),
                }
            )

    return json.dumps(
        {
            "patient_id": patientId,
            "search_url": f"{fhir_client.base_url}/Encounter?{urlencode(params)}",
            "count": len(encounters),
            "encounters": encounters,
        },
        indent=2,
    )
