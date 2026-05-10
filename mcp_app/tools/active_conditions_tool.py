"""GetActiveConditions — search FHIR Condition for the patient's problem list.

Maps to FHIR R4 Condition search:
https://www.hl7.org/fhir/condition.html#search
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Dict, List, Optional
from urllib.parse import urlencode

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists


async def get_active_conditions(
    patientId: Annotated[  # noqa: N803
        Optional[str],
        Field(description="The patient's FHIR id. Optional if patient context is set."),
    ] = None,
    clinicalStatus: Annotated[  # noqa: N803
        str,
        Field(
            description=(
                "FHIR `clinical-status` filter: 'active' | 'recurrence' | 'relapse' "
                "| 'inactive' | 'remission' | 'resolved'. Default 'active'. "
                "Pass empty string to disable the filter and return all."
            )
        ),
    ] = "active",
    category: Annotated[
        Optional[str],
        Field(
            description=(
                "FHIR `category` filter: 'problem-list-item' | 'encounter-diagnosis' "
                "| 'health-concern'."
            )
        ),
    ] = None,
    code: Annotated[
        Optional[str],
        Field(
            description=(
                "FHIR `code` filter (system|code or just code), e.g. "
                "'http://snomed.info/sct|44054006' for Type 2 diabetes."
            )
        ),
    ] = None,
    severity: Annotated[
        Optional[str],
        Field(
            description="FHIR `severity` token: 'mild' | 'moderate' | 'severe'."
        ),
    ] = None,
    recordedDate: Annotated[  # noqa: N803
        Optional[str],
        Field(
            description=(
                "FHIR `recorded-date` filter — supports prefixes like 'gt2024-01-01'."
            )
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Max conditions to return (default 50).", ge=1, le=200),
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
        "subject": f"Patient/{patientId}",
        "_sort": "-recorded-date",
        "_count": str(limit),
    }
    if clinicalStatus:
        params["clinical-status"] = clinicalStatus
    if category:
        params["category"] = category
    if code:
        params["code"] = code
    if severity:
        params["severity"] = severity
    if recordedDate:
        params["recorded-date"] = recordedDate

    bundle = await fhir_client.search("Condition", params)
    conditions: List[Dict[str, Any]] = []
    if bundle and bundle.get("entry"):
        for entry in bundle["entry"]:
            r = entry.get("resource") or {}
            conditions.append(
                {
                    "id": r.get("id"),
                    "code": (r.get("code") or {}).get("text"),
                    "category": [
                        (c.get("text") or "")
                        for c in (r.get("category") or [])
                    ],
                    "clinicalStatus": (
                        (r.get("clinicalStatus") or {}).get("coding") or [{}]
                    )[0].get("code"),
                    "severity": (r.get("severity") or {}).get("text"),
                    "onset": r.get("onsetDateTime") or r.get("onsetString"),
                    "recordedDate": r.get("recordedDate"),
                }
            )

    return json.dumps(
        {
            "patient_id": patientId,
            "search_url": f"{fhir_client.base_url}/Condition?{urlencode(params)}",
            "count": len(conditions),
            "conditions": conditions,
        },
        indent=2,
    )
