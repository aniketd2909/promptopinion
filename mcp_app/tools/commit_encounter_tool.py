"""CommitEncounter — write the doctor-approved structured visit to FHIR.

Translates the StructuredEncounterPayload into a FHIR transaction Bundle and
POSTs it to the connected FHIR server using the inbound MCP context.
"""

from __future__ import annotations

import json
from typing import Annotated, Optional

from mcp.server.fastmcp import Context
from pydantic import Field

from backend.fhir.schemas import StructuredEncounterPayload
from backend.fhir.store import build_resources_from_payload
from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists


async def commit_encounter(
    approvedEncounter: Annotated[  # noqa: N803
        str,
        Field(
            description=(
                "JSON object matching StructuredEncounterPayload — the doctor-"
                "approved visit data to persist."
            )
        ),
    ],
    patientId: Annotated[  # noqa: N803
        Optional[str],
        Field(description="Patient FHIR id. Optional if patient context is set."),
    ] = None,
    diagnosisSummary: Annotated[  # noqa: N803
        Optional[str],
        Field(
            description=(
                "Final diagnosis summary string from SuggestDiagnosis. When "
                "provided, written as a ClinicalImpression in the same Bundle."
            )
        ),
    ] = None,
    ctx: Context = None,
) -> str:
    try:
        encounter_dict = json.loads(approvedEncounter) if isinstance(approvedEncounter, str) else approvedEncounter
    except json.JSONDecodeError as exc:
        raise ValueError(f"approvedEncounter is not valid JSON: {exc}") from exc
    payload = StructuredEncounterPayload.model_validate(encounter_dict)

    if not patientId:
        patientId = get_patient_id_if_context_exists(ctx)
    if not patientId:
        raise ValueError("No patient id provided and no patient context found.")

    fhir_context = get_fhir_context(ctx)
    if not fhir_context:
        raise ValueError(
            "No FHIR context found. The platform must send the "
            "x-fhir-server-url and x-fhir-access-token headers."
        )

    resources = build_resources_from_payload(
        patient_id=patientId,
        payload=payload,
        diagnosis_summary=diagnosisSummary,
    )
    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {"resource": r, "request": {"method": "POST", "url": r["resourceType"]}}
            for r in resources
        ],
    }

    fhir_client = FhirClient(base_url=fhir_context.url, token=fhir_context.token)
    response = await fhir_client.post_bundle(bundle)

    return json.dumps(
        {
            "patient_id": patientId,
            "resources_written": [
                {"resourceType": r["resourceType"], "id": r["id"]} for r in resources
            ],
            "fhir_response_type": response.get("type"),
        },
        indent=2,
    )
