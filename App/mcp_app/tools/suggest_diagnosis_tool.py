"""SuggestDiagnosis — Claude Opus 4.7 differential / next-steps with FHIR history.

When called as an MCP tool by the platform LLM, this tool *itself* fetches the
patient's FHIR history (using the inbound MCP context) and pre-loads it into
Claude's prompt. We do not run a nested Claude tool-use loop here — the
platform LLM is the orchestrator.
"""

from __future__ import annotations

import json
import os
from typing import Annotated, Any, Dict, Optional

import anthropic
from mcp.server.fastmcp import Context
from pydantic import Field

from backend.fhir.schemas import DiagnosisSuggestion, StructuredEncounterPayload
from mcp_app.fhir_client import FhirClient
from mcp_app.fhir_context import get_fhir_context, get_patient_id_if_context_exists
from mcp_app.tools.patient_history_tool import _RESOURCE_TYPES, _summarize


SYSTEM_PROMPT = """\
You are a clinical decision-support assistant. You will receive:

1. A structured summary of a current visit (chief complaint, vitals, conditions
   discussed, medications mentioned, allergies).
2. The patient's prior FHIR history (encounters, conditions, observations,
   medications, allergies, prior clinical impressions).

Produce a single JSON object — no prose, no code fences — matching exactly:

{
  "differential": [string, ...],
  "recommended_next_steps": [
    {"title": string, "rationale": string, "priority": "urgent"|"routine"|"optional"},
    ...
  ],
  "red_flags": [string, ...],
  "history_signals_used": [string, ...],
  "summary": string
}

Rules:
- `differential` is ranked most-likely first.
- `red_flags` are items the physician must not miss given the history.
- `history_signals_used` lists specific items from prior records that
  influenced the suggestion. Empty array if no history was retrieved.
- `summary` is one paragraph the physician can read in 10 seconds.
- Do NOT prescribe — recommend evaluations, referrals, follow-up tests.
"""


_anthropic_client: Optional[anthropic.Anthropic] = None


def _get_anthropic() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not configured for the MCP server."
            )
        _anthropic_client = anthropic.Anthropic(api_key=api_key)
    return _anthropic_client


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
        encounter_dict = json.loads(structuredEncounter) if isinstance(structuredEncounter, str) else structuredEncounter
    except json.JSONDecodeError as exc:
        raise ValueError(f"structuredEncounter is not valid JSON: {exc}") from exc
    payload = StructuredEncounterPayload.model_validate(encounter_dict)

    if not patientId:
        patientId = get_patient_id_if_context_exists(ctx)

    history_summary: Dict[str, Any] = {}
    if patientId:
        fhir_context = get_fhir_context(ctx)
        if fhir_context:
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
        f"Prior FHIR history:\n{json.dumps(history_summary, indent=2) if history_summary else '(none)'}"
    )

    response = _get_anthropic().messages.create(
        model=os.getenv("DIAGNOSIS_MODEL", "claude-opus-4-7"),
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(b.text for b in response.content if b.type == "text").strip()

    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Diagnosis model did not return JSON: {text!r}")
    parsed = json.loads(text[start : end + 1])
    suggestion = DiagnosisSuggestion.model_validate(parsed)
    return suggestion.model_dump_json(indent=2)
