"""GetRecentObservations — search FHIR Observation (vitals, labs, etc.).

Maps to FHIR R4 Observation search:
https://www.hl7.org/fhir/observation.html#search
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Dict, List, Optional
from urllib.parse import urlencode

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists


async def get_recent_observations(
    patientId: Annotated[  # noqa: N803
        Optional[str],
        Field(description="The patient's FHIR id. Optional if patient context is set."),
    ] = None,
    category: Annotated[
        Optional[str],
        Field(
            description=(
                "FHIR `category` filter: 'vital-signs' | 'laboratory' | 'imaging' "
                "| 'social-history' | 'survey' | 'exam' | 'therapy' | 'activity'."
            )
        ),
    ] = None,
    code: Annotated[
        Optional[str],
        Field(
            description=(
                "FHIR `code` filter (system|code), e.g. LOINC code "
                "'http://loinc.org|8867-4' for heart rate."
            )
        ),
    ] = None,
    status: Annotated[
        str,
        Field(
            description=(
                "FHIR `status` filter, comma-separated. Default 'final,amended'. "
                "Valid: registered | preliminary | final | amended | corrected | "
                "cancelled | entered-in-error | unknown."
            )
        ),
    ] = "final,amended",
    date: Annotated[
        Optional[str],
        Field(
            description=(
                "FHIR `date` filter — supports prefixes 'gt', 'ge', 'lt', 'le'. "
                "Example 'gt2024-01-01' for observations after that date."
            )
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Max observations to return (default 20).", ge=1, le=100),
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
    if category:
        params["category"] = category
    if code:
        params["code"] = code
    if status:
        params["status"] = status
    if date:
        params["date"] = date

    bundle = await fhir_client.search("Observation", params)
    observations: List[Dict[str, Any]] = []
    if bundle and bundle.get("entry"):
        for entry in bundle["entry"]:
            r = entry.get("resource") or {}
            observations.append(
                {
                    "id": r.get("id"),
                    "code": (r.get("code") or {}).get("text"),
                    "category": [
                        (c.get("text") or "")
                        for c in (r.get("category") or [])
                    ],
                    "value": _format_value(r),
                    "unit": ((r.get("valueQuantity") or {}).get("unit")),
                    "effectiveDateTime": r.get("effectiveDateTime")
                    or (r.get("effectivePeriod") or {}).get("start"),
                    "status": r.get("status"),
                }
            )

    return json.dumps(
        {
            "patient_id": patientId,
            "search_url": f"{fhir_client.base_url}/Observation?{urlencode(params)}",
            "count": len(observations),
            "observations": observations,
        },
        indent=2,
    )


def _format_value(r: Dict[str, Any]) -> Any:
    if "valueQuantity" in r:
        q = r["valueQuantity"]
        return f"{q.get('value')} {q.get('unit', '')}".strip()
    if "valueString" in r:
        return r["valueString"]
    if "valueCodeableConcept" in r:
        return (r["valueCodeableConcept"] or {}).get("text")
    if "valueBoolean" in r:
        return r["valueBoolean"]
    if "valueInteger" in r:
        return r["valueInteger"]
    return None
