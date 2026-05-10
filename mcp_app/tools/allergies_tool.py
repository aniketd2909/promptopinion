"""GetAllergies — search FHIR AllergyIntolerance for the patient.

Maps to FHIR R4 AllergyIntolerance search:
https://www.hl7.org/fhir/allergyintolerance.html#search
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Dict, List, Optional
from urllib.parse import urlencode

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists


async def get_allergies(
    patientId: Annotated[  # noqa: N803
        Optional[str],
        Field(description="The patient's FHIR id. Optional if patient context is set."),
    ] = None,
    clinicalStatus: Annotated[  # noqa: N803
        Optional[str],
        Field(
            description=(
                "FHIR `clinical-status` filter: 'active' | 'inactive' | 'resolved'."
            )
        ),
    ] = None,
    verificationStatus: Annotated[  # noqa: N803
        Optional[str],
        Field(
            description=(
                "FHIR `verification-status` filter: 'unconfirmed' | 'confirmed' "
                "| 'refuted' | 'entered-in-error'."
            )
        ),
    ] = None,
    category: Annotated[
        Optional[str],
        Field(
            description=(
                "FHIR `category` filter: 'food' | 'medication' | 'environment' "
                "| 'biologic'."
            )
        ),
    ] = None,
    criticality: Annotated[
        Optional[str],
        Field(
            description=(
                "FHIR `criticality` filter: 'low' | 'high' | 'unable-to-assess'."
            )
        ),
    ] = None,
    type: Annotated[
        Optional[str],
        Field(description="FHIR `type` filter: 'allergy' | 'intolerance'."),
    ] = None,
    code: Annotated[
        Optional[str],
        Field(description="FHIR `code` filter (system|code) for the substance."),
    ] = None,
    limit: Annotated[
        int,
        Field(description="Max allergies to return (default 50).", ge=1, le=200),
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
        "_count": str(limit),
    }
    if clinicalStatus:
        params["clinical-status"] = clinicalStatus
    if verificationStatus:
        params["verification-status"] = verificationStatus
    if category:
        params["category"] = category
    if criticality:
        params["criticality"] = criticality
    if type:
        params["type"] = type
    if code:
        params["code"] = code

    bundle = await fhir_client.search("AllergyIntolerance", params)
    allergies: List[Dict[str, Any]] = []
    if bundle and bundle.get("entry"):
        for entry in bundle["entry"]:
            r = entry.get("resource") or {}
            allergies.append(
                {
                    "id": r.get("id"),
                    "substance": (r.get("code") or {}).get("text"),
                    "category": r.get("category") or [],
                    "criticality": r.get("criticality"),
                    "type": r.get("type"),
                    "clinicalStatus": (
                        (r.get("clinicalStatus") or {}).get("coding") or [{}]
                    )[0].get("code"),
                    "reaction": [
                        {
                            "manifestation": [
                                (m.get("text") or "")
                                for m in (rx.get("manifestation") or [])
                            ],
                            "severity": rx.get("severity"),
                        }
                        for rx in (r.get("reaction") or [])
                    ],
                    "recordedDate": r.get("recordedDate"),
                }
            )

    return json.dumps(
        {
            "patient_id": patientId,
            "search_url": f"{fhir_client.base_url}/AllergyIntolerance?{urlencode(params)}",
            "count": len(allergies),
            "allergies": allergies,
        },
        indent=2,
    )
