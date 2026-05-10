"""GetMedications — search FHIR for the patient's medications.

Aggregates two resource types in one call:
- MedicationStatement (https://www.hl7.org/fhir/medicationstatement.html#search)
- MedicationRequest   (https://www.hl7.org/fhir/medicationrequest.html#search)
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Dict, List, Optional
from urllib.parse import urlencode

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists


async def get_medications(
    patientId: Annotated[  # noqa: N803
        Optional[str],
        Field(description="The patient's FHIR id. Optional if patient context is set."),
    ] = None,
    status: Annotated[
        str,
        Field(
            description=(
                "FHIR `status` filter — comma-separated values allowed. Default "
                "'active'. For MedicationStatement: active | completed | "
                "intended | stopped | on-hold. For MedicationRequest: active | "
                "completed | cancelled | draft. Pass empty string to disable."
            )
        ),
    ] = "active",
    code: Annotated[
        Optional[str],
        Field(
            description=(
                "FHIR `code` filter (system|code), e.g. RxNorm code of the medication."
            )
        ),
    ] = None,
    includeRequests: Annotated[  # noqa: N803
        bool,
        Field(
            description=(
                "Whether to also include MedicationRequest results (prescriptions) "
                "in addition to MedicationStatement (taken). Default true."
            )
        ),
    ] = True,
    limit: Annotated[
        int,
        Field(description="Max medications per resource type (default 50).", ge=1, le=200),
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

    base_params: Dict[str, str] = {
        "subject": f"Patient/{patientId}",
        "_count": str(limit),
    }
    if status:
        base_params["status"] = status
    if code:
        base_params["code"] = code

    statements = await fhir_client.search("MedicationStatement", base_params)
    requests = (
        await fhir_client.search("MedicationRequest", base_params)
        if includeRequests
        else None
    )

    meds: List[Dict[str, Any]] = []
    for bundle, source in ((statements, "statement"), (requests, "request")):
        if not bundle or not bundle.get("entry"):
            continue
        for entry in bundle["entry"]:
            r = entry.get("resource") or {}
            med = r.get("medicationCodeableConcept") or {}
            meds.append(
                {
                    "id": r.get("id"),
                    "source": source,
                    "name": med.get("text"),
                    "status": r.get("status"),
                    "dosage": [
                        (d.get("text") or "")
                        for d in (r.get("dosage") or r.get("dosageInstruction") or [])
                    ],
                    "effectivePeriod": r.get("effectivePeriod"),
                    "authoredOn": r.get("authoredOn"),
                }
            )

    return json.dumps(
        {
            "patient_id": patientId,
            "search_url_statement": f"{fhir_client.base_url}/MedicationStatement?{urlencode(base_params)}",
            "search_url_request": (
                f"{fhir_client.base_url}/MedicationRequest?{urlencode(base_params)}"
                if includeRequests
                else None
            ),
            "count": len(meds),
            "medications": meds,
        },
        indent=2,
    )
