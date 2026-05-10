"""GetImmunizations — search FHIR Immunization for the patient.

Maps to FHIR R4 Immunization search:
https://www.hl7.org/fhir/immunization.html#search
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Dict, List, Optional
from urllib.parse import urlencode

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists


async def get_immunizations(
    patientId: Annotated[  # noqa: N803
        Optional[str],
        Field(description="The patient's FHIR id. Optional if patient context is set."),
    ] = None,
    status: Annotated[
        Optional[str],
        Field(
            description=(
                "FHIR `status` filter: 'completed' | 'entered-in-error' | "
                "'not-done'."
            )
        ),
    ] = None,
    vaccineCode: Annotated[  # noqa: N803
        Optional[str],
        Field(
            description=(
                "FHIR `vaccine-code` filter (system|code), e.g. CVX or SNOMED code."
            )
        ),
    ] = None,
    date: Annotated[
        Optional[str],
        Field(
            description=(
                "FHIR `date` filter — supports prefixes 'gt', 'ge', 'lt', 'le'."
            )
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Max immunizations to return (default 50).", ge=1, le=200),
    ] = 50,
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
        "patient": f"Patient/{patientId}",
        "_sort": "-date",
        "_count": str(limit),
    }
    if status:
        params["status"] = status
    if vaccineCode:
        params["vaccine-code"] = vaccineCode
    if date:
        params["date"] = date

    bundle = await fhir_client.search("Immunization", params)
    immunizations: List[Dict[str, Any]] = []
    if bundle and bundle.get("entry"):
        for entry in bundle["entry"]:
            r = entry.get("resource") or {}
            immunizations.append(
                {
                    "id": r.get("id"),
                    "vaccine": (r.get("vaccineCode") or {}).get("text"),
                    "status": r.get("status"),
                    "occurrenceDateTime": r.get("occurrenceDateTime"),
                    "lotNumber": r.get("lotNumber"),
                    "site": (r.get("site") or {}).get("text"),
                    "doseQuantity": r.get("doseQuantity"),
                }
            )

    return json.dumps(
        {
            "patient_id": patientId,
            "search_url": f"{fhir_client.base_url}/Immunization?{urlencode(params)}",
            "count": len(immunizations),
            "immunizations": immunizations,
        },
        indent=2,
    )
