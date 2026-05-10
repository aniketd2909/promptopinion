"""SuggestDiagnosis — Gemini differential / next-steps with FHIR history.

When called as an MCP tool by the platform LLM, this tool *itself* fetches the
patient's FHIR history (using the inbound MCP context) and pre-loads it into
the model's prompt. We do not run a nested tool-use loop here — the platform
LLM is the orchestrator. The diagnosis itself is produced via Gemini's native
structured-output mode, so the response is already validated as a
:class:`DiagnosisSuggestion` before it returns to the caller.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Dict, Optional

from mcp.server.fastmcp import Context
from pydantic import Field

from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists
from mcp_app.llm import structured_completion
from mcp_app.tools.patient_history_tool import _RESOURCE_TYPES, _summarize
from shared.fhir.schemas import DiagnosisSuggestion, StructuredEncounterPayload


SYSTEM_PROMPT = """\
You are a clinical decision-support assistant. You will receive:

1. A structured summary of a current visit (chief complaint, vitals, conditions
   discussed, medications mentioned, allergies).
2. The patient's prior FHIR history (encounters, conditions, observations,
   medications, allergies, prior clinical impressions).

Produce a JSON object matching the DiagnosisSuggestion schema you've been given.

Rules:
- `differential` is ranked most-likely first.
- `red_flags` are items the physician must not miss given the history.
- `history_signals_used` lists specific items from prior records that
  influenced the suggestion. Empty array if no history was retrieved.
- `summary` is one paragraph the physician can read in 10 seconds.
- Do NOT prescribe — recommend evaluations, referrals, follow-up tests.
"""


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

    user_msg = (
        f"patient_id: {patientId or '[not provided]'}\n\n"
        f"Today's visit (structured):\n{payload.model_dump_json(indent=2)}\n\n"
        f"Prior FHIR history:\n"
        f"{json.dumps(history_summary, indent=2) if history_summary else '(none)'}"
    )

    suggestion = await structured_completion(
        system=SYSTEM_PROMPT,
        user=user_msg,
        schema=DiagnosisSuggestion,
    )
    return suggestion.model_dump_json(indent=2)
