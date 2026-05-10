"""SuggestDiagnosis — Gemini differential / next-steps with FHIR history.

When called as an MCP tool by the platform LLM, this tool *itself* fetches the
patient's FHIR history (using the inbound MCP context) and hands it, along
with the structured encounter, to :mod:`shared.agents.diagnoser`. We do not
run a nested tool-use loop here — the platform LLM is the orchestrator. The
diagnosis itself is produced via Gemini's native structured-output mode, so
the response is already validated as a :class:`DiagnosisSuggestion` before it
returns to the caller.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Dict, Optional

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists
from mcp_app.tools.patient_history_tool import _RESOURCE_TYPES, _summarize
from shared.agents.diagnoser import suggest_diagnosis_for_encounter
from shared.fhir.schemas import StructuredEncounterPayload


async def suggest_diagnosis(
    structuredEncounter: Annotated[  # noqa: N803
        str,
        Field(
            description=(
                "JSON object matching the StructuredEncounterPayload schema "
                "(typically the output of StructureClinicalConversation)."
            )
        ),
    ],
    patientId: Annotated[  # noqa: N803
        Optional[str],
        Field(description="Patient FHIR id. Optional if patient context is set."),
    ] = None,
    ctx: Context = None,
) -> str:
    try:
        encounter_dict = (
            json.loads(structuredEncounter)
            if isinstance(structuredEncounter, str)
            else structuredEncounter
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"structuredEncounter is not valid JSON: {exc}") from exc
    payload = StructuredEncounterPayload.model_validate(encounter_dict)

    if not patientId:
        patientId = get_patient_id_if_context_exists(ctx)

    history_summary: Dict[str, Any] = {}
    if patientId:
        fhir_context = get_fhir_context(ctx)
        fhir_client = FhirClient(
            base_url=fhir_context.url, token=fhir_context.token
        )
        for rt, search_param in _RESOURCE_TYPES:
            bundle = await fhir_client.search(
                rt, {search_param: f"Patient/{patientId}"}
            )
            if bundle and bundle.get("entry"):
                resources = [
                    e["resource"] for e in bundle["entry"] if e.get("resource")
                ]
                if resources:
                    history_summary[rt] = [_summarize(r) for r in resources]

    suggestion = await suggest_diagnosis_for_encounter(
        payload=payload,
        history_summary=history_summary,
        patient_id=patientId,
    )
    return suggestion.model_dump_json(indent=2)
